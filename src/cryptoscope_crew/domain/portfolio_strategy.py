# src/cryptoscope_crew/domain/portfolio_strategy.py
"""PortfolioStrategyEngine — SPOT-ONLY portfolio-aware strategy layer.

This system is SPOT ONLY:
  - No leverage, no short selling, no derivatives.
  - You can only BUY and HOLD spot tokens, or SELL spot tokens you own.
  - Cash (USDC) is always a valid position (risk-off = raise cash).

Combines:
  - current portfolio positions (quantity, avg_price, PnL, core/swing split,
    min_core_qty)
  - market regime (BULL / BEAR / RANGE)
  - multi-TF signal (SignalEngine output)
  - decision engine output (REDUCE_SWING / DEFENSIVE / HOLD_OR_ADD /
    ADD_SMALL / REBUILD_LADDER / WAIT)
  - risk_limits & decision_defaults from portfolio.json

Spot-compatible actions:
  ADD_SMALL       – small spot buy (add_small_cash_pct of portfolio)
  HOLD            – keep current position, no action
  WAIT            – no clear setup, stand aside
  REDUCE_SWING    – sell part of swing allocation (never below min_core_qty)
  DEFENSIVE       – no new buys, protect existing holdings
  REBUILD_LADDER  – staged buy ladder (buy_ladder_cash_pct steps)

Constraints enforced:
  1. Never sell below min_core_qty for any position.
  2. Always preserve cash_min_pct of total portfolio in USDC.
  3. Reductions only touch the swing portion.
  4. Buy ladders respect max_single_order_cash_pct per step.

Pure deterministic logic, no LLM.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional

from pydantic import BaseModel, Field

from cryptoscope_crew.domain.decision_engine import Action, DecisionResult, _get_entry
from cryptoscope_crew.domain.macro_regime import MacroRegime, MacroRegimeResult
from cryptoscope_crew.domain.regime import MarketRegime, RegimeResult
from cryptoscope_crew.domain.signal_engine import MultiTFSignal, SignalType

if TYPE_CHECKING:
    from cryptoscope_crew.domain.portfolio import (
        DecisionDefaults,
        Portfolio,
        Position,
        RiskLimits,
    )


# ------------------------------------------------------------------ #
#  Types
# ------------------------------------------------------------------ #

class StrategyAction(str, Enum):
    """Spot-only actions — no EXIT, no generic ADD/REDUCE."""

    ADD_SMALL       = "ADD_SMALL"
    HOLD            = "HOLD"
    WAIT            = "WAIT"
    REDUCE_SWING    = "REDUCE_SWING"
    DEFENSIVE       = "DEFENSIVE"
    REBUILD_LADDER  = "REBUILD_LADDER"


class PositionStrategy(BaseModel):
    """Strategy recommendation for a single position."""

    pair: str
    quantity: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    core_qty: float = 0.0           # core allocation in base units
    swing_qty: float = 0.0          # swing allocation in base units
    min_core_qty: float = 0.0       # floor — never sell below this
    strategy: StrategyAction
    adjustment: str = ""            # human-readable adjustment instruction
    regime: str = ""                # BULL / BEAR / RANGE
    signal: str = ""                # environment label from SignalEngine
    rationale: str = ""             # detailed explanation
    key_levels: Dict[str, str] = Field(default_factory=dict)


class PortfolioStrategyResult(BaseModel):
    """Full portfolio strategy output."""

    positions: List[PositionStrategy] = Field(default_factory=list)
    cash_usdc: float = 0.0
    total_value: float = 0.0
    cash_pct: float = 0.0
    cash_min_pct: float = 20.0     # target minimum from risk_limits
    overall_regime: str = ""        # dominant regime across pairs
    summary: str = ""               # one-liner for the report header
    raise_cash_plan: List[str] = Field(default_factory=list)  # étapes concrètes si cash < cible


# ------------------------------------------------------------------ #
#  Engine
# ------------------------------------------------------------------ #

class PortfolioStrategyEngine:
    """Deterministic SPOT-ONLY portfolio strategy engine.

    Takes the full picture (positions, regimes, signals, decisions)
    and produces actionable per-position strategies that respect
    spot constraints (min_core_qty, cash_min_pct, swing-only reductions,
    staged buy ladders).
    """

    @staticmethod
    def build(
        portfolio: "Portfolio",
        regimes: List[RegimeResult],
        signals: List[MultiTFSignal],
        decisions: List[DecisionResult],
        context_by_tf: Dict[str, dict],
        *,
        macro_regimes: Optional[List[MacroRegimeResult]] = None,
    ) -> PortfolioStrategyResult:
        """Build portfolio strategy for all positions.

        If *macro_regimes* is provided, BTC macro regime is used to
        gate aggressive actions (ADD_SMALL → HOLD, REBUILD_LADDER → WAIT)
        when BTC macro is BEAR.
        """
        from cryptoscope_crew.domain.portfolio import Portfolio

        regime_map = {r.pair: r for r in regimes}
        signal_map = {s.pair: s for s in signals}
        decision_map = {d.pair: d for d in decisions}

        rl = portfolio.risk_limits
        dd = portfolio.defaults

        # Extract BTC macro regime
        btc_macro: Optional[MacroRegime] = None
        if macro_regimes:
            for mr in macro_regimes:
                if mr.pair.split("/")[0].upper() == "BTC":
                    btc_macro = mr.macro
                    break

        position_strategies: List[PositionStrategy] = []

        for pos in portfolio.positions:
            pair = pos.pair
            regime = regime_map.get(pair)
            sig = signal_map.get(pair)
            dec = decision_map.get(pair)

            ps = PortfolioStrategyEngine._strategy_for_position(
                pos, regime, sig, dec, context_by_tf, rl, dd, portfolio,
                btc_macro=btc_macro,
            )
            position_strategies.append(ps)

        # Overall regime = majority vote
        regime_counts: Dict[str, int] = {}
        for r in regimes:
            regime_counts[r.regime.value] = regime_counts.get(r.regime.value, 0) + 1
        overall = max(regime_counts, key=regime_counts.get) if regime_counts else "RANGE"

        total_val = portfolio.total_value
        cash_pct = (portfolio.cash_usdc / total_val * 100) if total_val > 0 else 100.0

        # Summary line
        action_counts: Dict[str, int] = {}
        for ps in position_strategies:
            action_counts[ps.strategy.value] = action_counts.get(ps.strategy.value, 0) + 1
        parts = [f"{n} {a}" for a, n in action_counts.items() if n > 0]
        cash_ok = "OK" if cash_pct >= rl.cash_min_pct else "LOW"
        summary = (
            f"SPOT ONLY | Regime: {overall} | "
            f"Cash: {portfolio.cash_usdc:.0f} USDC ({cash_pct:.0f}% — {cash_ok}) | "
            + (", ".join(parts) if parts else "All WAIT")
        )

        # Plan de rééquilibrage : si le cash est sous la cible, proposer
        # des ventes de swing concrètes (jamais de constat sans action).
        raise_cash_plan: List[str] = []
        if total_val > 0 and cash_pct < rl.cash_min_pct:
            raise_cash_plan = PortfolioStrategyEngine._build_raise_cash_plan(
                portfolio, context_by_tf, rl
            )

        return PortfolioStrategyResult(
            positions=position_strategies,
            cash_usdc=portfolio.cash_usdc,
            total_value=total_val,
            cash_pct=round(cash_pct, 1),
            cash_min_pct=rl.cash_min_pct,
            overall_regime=overall,
            summary=summary,
            raise_cash_plan=raise_cash_plan,
        )

    # ────────────────────────────────────────────────────────────── #
    #  Raise-cash plan
    # ────────────────────────────────────────────────────────────── #

    @staticmethod
    def _build_raise_cash_plan(
        portfolio: "Portfolio",
        context_by_tf: Dict[str, dict],
        rl: "RiskLimits",
    ) -> List[str]:
        """Étapes concrètes pour remonter le cash à cash_min_pct.

        Vend le swing des paires structurellement les plus faibles d'abord
        (close 4H le plus loin sous EMA50 4H), sans jamais entamer le core
        ni min_core_qty. Indique le niveau d'exécution (sur force vers
        EMA50 4H plutôt qu'en panique).
        """
        total_val = portfolio.total_value or 0.0
        if total_val <= 0:
            return []
        cash_needed = total_val * (rl.cash_min_pct / 100) - portfolio.cash_usdc
        if cash_needed <= 0:
            return []

        ctx_4h = context_by_tf.get("4h", {})
        candidates = []
        for pos in portfolio.positions:
            core_qty = pos.quantity * (pos.core_pct / 100)
            sellable = max(0.0, pos.quantity - max(core_qty, pos.min_core_qty))
            if sellable <= 0 or pos.current_price <= 0:
                continue
            e4h = _get_entry(ctx_4h, pos.pair)
            # faiblesse = distance du close vs EMA50 4H (plus négatif = plus faible)
            weakness = 0.0
            ema50 = None
            if e4h and e4h.get("ema_slow"):
                ema50 = e4h["ema_slow"]
                weakness = (e4h["close"] - ema50) / ema50 * 100
            candidates.append((weakness, pos, sellable, ema50))
        candidates.sort(key=lambda c: c[0])  # structure la plus faible d'abord

        if not candidates:
            return [
                f"⚠ Aucun swing vendable (positions au floor core) — impossible de "
                f"remonter le cash à {rl.cash_min_pct:.0f}% sans entamer le core. "
                f"Décision manuelle requise."
            ]

        lines: List[str] = []
        remaining = cash_needed
        for step, (weakness, pos, sellable, ema50) in enumerate(candidates, 1):
            if remaining <= 0:
                break
            ticker = pos.pair.split("/")[0]
            qty = min(sellable, remaining / pos.current_price)
            proceeds = qty * pos.current_price
            if ema50 is not None:
                if pos.current_price < ema50:
                    level_txt = f" — exécuter sur rebond vers EMA50 4H ({ema50:.4f}), pas en panique sous support"
                else:
                    level_txt = f" — exécutable au prix courant (déjà > EMA50 4H {ema50:.4f})"
            else:
                level_txt = ""
            lines.append(
                f"{step}. Vendre ~{qty:.6f} {ticker} (~{proceeds:.0f} USDC) — swing {pos.pair}, "
                f"structure 4H {weakness:+.1f}% vs EMA50{level_txt}"
            )
            remaining -= proceeds

        if remaining > 0:
            lines.append(
                f"⚠ Swing vendable insuffisant : il manquera ~{remaining:.0f} USDC "
                f"pour atteindre {rl.cash_min_pct:.0f}% (core préservé)."
            )
        return lines

    # ────────────────────────────────────────────────────────────── #
    #  Per-position logic
    # ────────────────────────────────────────────────────────────── #

    @staticmethod
    def _strategy_for_position(
        pos: "Position",
        regime: Optional[RegimeResult],
        sig: Optional[MultiTFSignal],
        dec: Optional[DecisionResult],
        context_by_tf: Dict[str, dict],
        rl: "RiskLimits",
        dd: "DecisionDefaults",
        portfolio: "Portfolio",
        *,
        btc_macro: Optional[MacroRegime] = None,
    ) -> PositionStrategy:
        """Determine strategy for a single position.

        Enforces spot constraints:
        - Never sell below min_core_qty.
        - Cash must stay >= cash_min_pct of portfolio.
        - Reductions only touch swing portion.
        - Buy ladders respect max_single_order_cash_pct.
        """
        pair = pos.pair
        ticker = pair.split("/")[0]
        regime_val = regime.regime if regime else MarketRegime.RANGE
        regime_str = regime_val.value
        signal_env = sig.environment if sig else "unknown"
        signal_type = sig.signal if sig else SignalType.NEUTRAL
        dec_action = dec.suggested_action if dec else Action.WAIT

        # Derived quantities
        core_qty = pos.quantity * (pos.core_pct / 100)
        swing_qty = pos.quantity * (pos.swing_pct / 100)
        min_core = pos.min_core_qty

        # Available swing (what can actually be sold without breaking core)
        sellable_swing = max(0.0, pos.quantity - max(core_qty, min_core))

        # Cash budget for adds
        total_val = portfolio.total_value or 1.0
        cash_floor = total_val * (rl.cash_min_pct / 100)
        available_cash = max(0.0, portfolio.cash_usdc - cash_floor)

        # Key levels from 4H context
        key_levels: Dict[str, str] = {}
        e4h = _get_entry(context_by_tf.get("4h", {}), pair)
        if e4h:
            key_levels["EMA20_4H"] = f"{e4h['ema_fast']:.4f}"
            key_levels["EMA50_4H"] = f"{e4h['ema_slow']:.4f}"

        base = dict(
            pair=pair,
            quantity=pos.quantity,
            avg_price=pos.avg_price,
            current_price=pos.current_price,
            pnl_pct=pos.pnl_pct,
            core_qty=round(core_qty, 8),
            swing_qty=round(swing_qty, 8),
            min_core_qty=min_core,
            regime=regime_str,
            signal=signal_env,
            key_levels=key_levels,
        )

        # ── REDUCE_SWING ─────────────────────────────────────────
        if dec_action == Action.REDUCE_SWING:
            reduce_pct = dd.reduce_swing_pct_of_swing
            reduce_qty = swing_qty * (reduce_pct / 100)
            # Clamp to sellable swing (respect min_core_qty)
            reduce_qty = min(reduce_qty, sellable_swing)

            if reduce_qty <= 0:
                return PositionStrategy(
                    **base,
                    strategy=StrategyAction.HOLD,
                    adjustment=(
                        f"Swing already at floor (min_core_qty={min_core} {ticker}). "
                        f"Nothing to reduce."
                    ),
                    rationale=(
                        f"Decision engine suggests REDUCE_SWING but position is "
                        f"at or below min_core_qty. Hold."
                    ),
                )

            adj_text = (
                f"Sell ~{reduce_qty:.6f} {ticker} "
                f"({reduce_pct:.0f}% of swing={swing_qty:.6f})"
            )
            if e4h:
                adj_text += f" on strength near EMA20 4H ({e4h['ema_fast']:.4f})"
            adj_text += f" | Floor: keep >= {min_core} {ticker} (core)"

            return PositionStrategy(
                **base,
                strategy=StrategyAction.REDUCE_SWING,
                adjustment=adj_text,
                rationale=(
                    f"Counter-trend bounce in {regime_str} regime ({signal_env}). "
                    f"Lighten swing exposure, protect core >= {min_core} {ticker}."
                ),
            )

        # ── DEFENSIVE ─────────────────────────────────────────────
        if dec_action == Action.DEFENSIVE:
            invalidation = dec.invalidation or ""
            adj_text = "No new spot buys"
            if invalidation:
                adj_text += f"; avoid adding until {invalidation}"
            adj_text += f" | Hold core ({core_qty:.6f} {ticker})"

            return PositionStrategy(
                **base,
                strategy=StrategyAction.DEFENSIVE,
                adjustment=adj_text,
                rationale=(
                    f"Full bearish alignment ({signal_env}). "
                    f"Spot: protect existing holdings, keep cash >= "
                    f"{rl.cash_min_pct:.0f}%."
                ),
            )

        # ── REBUILD_LADDER (from R4 or decision engine) ───────────
        if dec_action == Action.REBUILD_LADDER:
            # Macro BEAR gate: don't build ladder in macro bear
            if btc_macro == MacroRegime.BEAR:
                return PositionStrategy(
                    **base,
                    strategy=StrategyAction.WAIT,
                    adjustment=(
                        f"Wait — BTC macro BEAR; ladder building suspended"
                    ),
                    rationale=(
                        f"Local setup supports rebuild ({signal_env}) but BTC macro "
                        f"is BEAR. Waiting for macro improvement before ladder."
                    ),
                )
            steps = dd.buy_ladder_cash_pct
            max_step = rl.max_single_order_cash_pct
            ladder_lines: List[str] = []
            for i, step_pct in enumerate(steps):
                capped = min(step_pct, max_step)
                cash_amount = total_val * (capped / 100)
                cash_amount = min(cash_amount, available_cash)
                if cash_amount <= 0:
                    ladder_lines.append(
                        f"  Step {i+1}: {capped:.0f}% — SKIP (cash floor reached)"
                    )
                else:
                    qty_est = (cash_amount / pos.current_price) if pos.current_price > 0 else 0
                    ladder_lines.append(
                        f"  Step {i+1}: ~{cash_amount:.0f} USDC "
                        f"(~{qty_est:.6f} {ticker}, {capped:.0f}% of portfolio)"
                    )
                    available_cash -= cash_amount

            adj_text = "Staged buy ladder:\n" + "\n".join(ladder_lines)
            if e4h:
                adj_text += f"\nEntry zone around EMA20 4H ({e4h['ema_fast']:.4f})"

            return PositionStrategy(
                **base,
                strategy=StrategyAction.REBUILD_LADDER,
                adjustment=adj_text,
                rationale=(
                    f"Daily bullish with pullback on lower TFs ({signal_env}). "
                    f"Rebuild position via staged ladder, respecting "
                    f"cash floor ({rl.cash_min_pct:.0f}%) and "
                    f"max order size ({max_step:.0f}%)."
                ),
            )

        # ── HOLD_OR_ADD ───────────────────────────────────────────
        if dec_action in (Action.HOLD_OR_ADD, Action.ADD_SMALL):
            # Macro BEAR gate: don't add in macro bear environment
            if btc_macro == MacroRegime.BEAR:
                return PositionStrategy(
                    **base,
                    strategy=StrategyAction.HOLD,
                    adjustment=(
                        f"Hold {pos.quantity:.6f} {ticker}; "
                        f"BTC macro BEAR prevents new adds"
                    ),
                    rationale=(
                        f"Local trend is bullish ({signal_env}) but BTC macro is BEAR. "
                        f"Spot: hold position, wait for macro confirmation before adding."
                    ),
                )
            if signal_type in (SignalType.ALIGNED_BULL, SignalType.BUY_DIP):
                add_cash = total_val * (dd.add_small_cash_pct / 100)
                add_cash = min(add_cash, available_cash)
                if add_cash <= 0:
                    return PositionStrategy(
                        **base,
                        strategy=StrategyAction.HOLD,
                        adjustment=(
                            f"Would add but cash at floor "
                            f"({rl.cash_min_pct:.0f}% reserve). Hold."
                        ),
                        rationale=(
                            f"Bullish setup ({signal_env}) but cash reserve "
                            f"constraint prevents new spot buys."
                        ),
                    )

                qty_est = (add_cash / pos.current_price) if pos.current_price > 0 else 0
                adj_text = (
                    f"Add small: ~{add_cash:.0f} USDC "
                    f"(~{qty_est:.6f} {ticker}, "
                    f"{dd.add_small_cash_pct:.0f}% of portfolio)"
                )
                if e4h:
                    adj_text += f" on pullback to EMA20 4H ({e4h['ema_fast']:.4f})"

                return PositionStrategy(
                    **base,
                    strategy=StrategyAction.ADD_SMALL,
                    adjustment=adj_text,
                    rationale=(
                        f"Bullish alignment ({signal_env}). "
                        f"Spot: small add respecting "
                        f"{rl.cash_min_pct:.0f}% cash reserve."
                    ),
                )

            # Bull but weakening — hold, don't add
            return PositionStrategy(
                **base,
                strategy=StrategyAction.HOLD,
                adjustment=f"Hold {pos.quantity:.6f} {ticker}; wait for 4H confirmation",
                rationale=(
                    f"Daily bullish but lower TFs hesitant ({signal_env}). "
                    f"Spot: hold position, no new buys yet."
                ),
            )

        # ── WAIT / fallback ───────────────────────────────────────
        watch_text = "Wait for clearer setup"
        if e4h:
            watch_text = (
                f"Watch EMA20 4H ({e4h['ema_fast']:.4f}) as potential entry; "
                f"risk below EMA50 4H ({e4h['ema_slow']:.4f})"
            )

        return PositionStrategy(
            **base,
            strategy=StrategyAction.WAIT,
            adjustment=watch_text,
            rationale=(
                f"No clear directional setup ({signal_env}). "
                f"Spot: maintain current position, keep cash."
            ),
        )


# ------------------------------------------------------------------ #
#  Markdown formatter
# ------------------------------------------------------------------ #

def portfolio_strategy_to_markdown(result: PortfolioStrategyResult) -> str:
    """Produce the '## Spot Portfolio Strategy' report section."""
    cash_status = "OK" if result.cash_pct >= result.cash_min_pct else "BELOW TARGET"
    lines = [
        "## Spot Portfolio Strategy",
        "",
        "> **SPOT ONLY** — no leverage, no shorts, no derivatives.",
        "",
        f"> {result.summary}",
        "",
    ]

    for ps in result.positions:
        ticker = ps.pair.split("/")[0]
        lines.append(f"### {ps.pair}")
        lines.append(f"- **Position:** {ps.quantity} {ticker}")
        if ps.core_qty > 0 or ps.swing_qty > 0:
            lines.append(
                f"- **Core / Swing:** {ps.core_qty:.6f} / "
                f"{ps.swing_qty:.6f} {ticker}"
            )
        if ps.min_core_qty > 0:
            lines.append(f"- **Min core (floor):** {ps.min_core_qty} {ticker}")
        if ps.current_price > 0:
            lines.append(f"- **Current price:** {ps.current_price:.4f}")
        if ps.avg_price > 0:
            lines.append(f"- **Avg entry:** {ps.avg_price:.4f}")
        if ps.pnl_pct != 0:
            sign = "+" if ps.pnl_pct > 0 else ""
            lines.append(f"- **PnL:** {sign}{ps.pnl_pct:.2f}%")
        lines.append(f"- **Regime:** {ps.regime}")
        lines.append(f"- **Strategy:** `{ps.strategy.value}`")
        lines.append(f"- **Adjustment:** {ps.adjustment}")
        for lbl, val in ps.key_levels.items():
            lines.append(f"- **{lbl}:** {val}")
        lines.append(f"- _Rationale: {ps.rationale}_")
        lines.append("")

    # Cash summary
    lines.append("### Cash")
    lines.append(
        f"- **Available:** {result.cash_usdc:.2f} USDC "
        f"({result.cash_pct:.0f}% of portfolio — {cash_status})"
    )
    lines.append(f"- **Target reserve:** >= {result.cash_min_pct:.0f}%")
    if result.raise_cash_plan:
        lines.append("")
        lines.append("**Plan de rééquilibrage (RAISE_CASH) :**")
        for step in result.raise_cash_plan:
            lines.append(f"- {step}")
    lines.append("")

    return "\n".join(lines)
