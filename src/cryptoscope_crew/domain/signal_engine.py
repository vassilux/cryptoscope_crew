# src/cryptoscope_crew/domain/signal_engine.py
"""SignalEngine — interprets multi-timeframe structure into actionable signals.

Combines 1D regime with 4H and 1H bias to produce a structural reading
(e.g. "bounce inside bear trend", "aligned bullish breakout").

SPOT ONLY — no shorts, no leverage. Signal descriptions are always
framed in terms of spot portfolio actions (reduce swing, hold core,
buy dip, rebuild ladder).
Pure deterministic logic, no LLM.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from cryptoscope_crew.domain.decision_engine import _bias, _rsi, _get_entry
from cryptoscope_crew.domain.macro_regime import MacroRegime
from cryptoscope_crew.domain.regime import MarketRegime, RegimeResult


# ------------------------------------------------------------------ #
#  Types
# ------------------------------------------------------------------ #

class SignalType(str, Enum):
    """High-level structural signal derived from multi-TF alignment."""

    SELL_BOUNCE = "SELL_BOUNCE"       # bear trend + lower-TF bounce → fade
    ALIGNED_BEAR = "ALIGNED_BEAR"    # all TFs bearish
    BUY_DIP = "BUY_DIP"             # bull trend + lower-TF dip → buy
    ALIGNED_BULL = "ALIGNED_BULL"    # all TFs bullish
    BULL_WEAKENING = "BULL_WEAKENING"  # 1D bull but lower TFs softening
    BEAR_RECOVERY = "BEAR_RECOVERY"    # 1D bear but lower TFs recovering
    NEUTRAL = "NEUTRAL"              # mixed / no clear signal


class MultiTFSignal(BaseModel):
    """Multi-timeframe signal for a single pair."""

    pair: str
    signal: SignalType
    bias_1d: str = ""
    bias_4h: str = ""
    bias_1h: str = ""
    rsi_1h: float = 50.0
    rsi_4h: float = 50.0
    description: str = ""
    environment: str = ""   # short label for the trading environment


# ------------------------------------------------------------------ #
#  Engine
# ------------------------------------------------------------------ #

class SignalEngine:
    """Interprets multi-timeframe structure into a structural signal.

    Input: context_by_tf (from precompute_multi or parse_md_tables)
           + RegimeResult for the pair.

    Output: MultiTFSignal describing what the combined TF picture means.
    """

    @staticmethod
    def analyze(
        pair: str,
        context_by_tf: Dict[str, dict],
        regime: RegimeResult,
        *,
        btc_macro: Optional[MacroRegime] = None,
    ) -> MultiTFSignal:
        """Produce a multi-TF signal for *pair*.

        If *btc_macro* is provided and the pair is not BTC, the
        environment label is enriched with BTC macro context.
        """
        b1d = regime.regime.value.capitalize()  # "Bull" / "Bear" / "Range"
        b4h = _bias(context_by_tf.get("4h", {}), pair)
        b1h = _bias(context_by_tf.get("1h", {}), pair)
        rsi_1h = _rsi(context_by_tf.get("1h", {}), pair)
        rsi_4h = _rsi(context_by_tf.get("4h", {}), pair)

        base = dict(
            pair=pair,
            bias_1d=b1d,
            bias_4h=b4h,
            bias_1h=b1h,
            rsi_1h=rsi_1h,
            rsi_4h=rsi_4h,
        )

        # ── BEAR regime patterns ──────────────────────────────────
        if regime.regime == MarketRegime.BEAR:
            if b4h == "Bull" and b1h == "Bull":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.SELL_BOUNCE,
                    description=(
                        f"1D Bear / 4H Bull / 1H Bull — counter-trend rally in bear. "
                        f"RSI 1H={rsi_1h:.0f}, RSI 4H={rsi_4h:.0f}. "
                        f"Spot: reduce swing inventory on strength, protect core."
                    ),
                    environment="reduce swing on bounce",
                )
            if b4h == "Bull" and b1h == "Bear":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.SELL_BOUNCE,
                    description=(
                        f"1D Bear / 4H Bull / 1H Bear — fading bounce. "
                        f"4H still up but 1H already turning. "
                        f"Spot: lighten swing if not yet done, hold core."
                    ),
                    environment="reduce swing (fading bounce)",
                )
            if b4h == "Bear" and b1h == "Bull":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.BEAR_RECOVERY,
                    description=(
                        f"1D Bear / 4H Bear / 1H Bull — early recovery attempt. "
                        f"Only 1H shows strength; too early to add spot."
                    ),
                    environment="bear recovery — wait",
                )
            # b4h Bear + b1h Bear
            return MultiTFSignal(
                **base,
                signal=SignalType.ALIGNED_BEAR,
                description=(
                    f"1D Bear / 4H Bear / 1H Bear — full bearish alignment. "
                    f"Spot: no new buys, defensive stance, protect cash."
                ),
                environment="full bear — defensive",
            )

        # ── BULL regime patterns ──────────────────────────────────
        if regime.regime == MarketRegime.BULL:
            if b4h == "Bull" and b1h == "Bull":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.ALIGNED_BULL,
                    description=(
                        f"1D Bull / 4H Bull / 1H Bull — full bullish alignment. "
                        f"Spot: hold core + swing, add small on pullback."
                    ),
                    environment="full bull — hold & add",
                )
            if b4h == "Bull" and b1h == "Bear":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.BUY_DIP,
                    description=(
                        f"1D Bull / 4H Bull / 1H Bear — short-term pullback in uptrend. "
                        f"Spot: potential buy-dip / rebuild ladder if RSI 1H cools."
                    ),
                    environment="buy dip — spot ladder",
                )
            if b4h == "Bear" and b1h == "Bear":
                return MultiTFSignal(
                    **base,
                    signal=SignalType.BULL_WEAKENING,
                    description=(
                        f"1D Bull / 4H Bear / 1H Bear — trend weakening. "
                        f"Daily still bullish but lower TFs deteriorating. "
                        f"Spot: hold core, no new adds until 4H reclaims EMA20."
                    ),
                    environment="weakening bull — hold",
                )
            # b4h Bear + b1h Bull
            return MultiTFSignal(
                **base,
                signal=SignalType.NEUTRAL,
                description=(
                    f"1D Bull / 4H Bear / 1H Bull — mixed signals. "
                    f"Conflicting lower TFs; spot: hold, wait for confirmation."
                ),
                environment="mixed — wait",
            )

        # ── RANGE regime patterns ─────────────────────────────────
        if b4h == "Bull" and b1h == "Bull":
            return MultiTFSignal(
                **base,
                signal=SignalType.BUY_DIP,
                description=(
                    f"1D Range / 4H Bull / 1H Bull — bullish within range. "
                    f"Spot: small add possible, keep tight size."
                ),
                environment="range bull — small add",
            )
        if b4h == "Bear" and b1h == "Bear":
            return MultiTFSignal(
                **base,
                signal=SignalType.SELL_BOUNCE,
                description=(
                    f"1D Range / 4H Bear / 1H Bear — bearish within range. "
                    f"Spot: reduce swing if overweight, hold core."
                ),
                environment="range bear — reduce swing",
            )

        return MultiTFSignal(
            **base,
            signal=SignalType.NEUTRAL,
            description=(
                f"1D Range with mixed lower-TF biases ({b4h}/{b1h}). "
                f"Spot: hold positions, no new adds."
            ),
            environment="range — wait",
        )

    @staticmethod
    def _enrich_environment(signal: MultiTFSignal, btc_macro: Optional[MacroRegime]) -> MultiTFSignal:
        """Append BTC macro context to environment label when relevant."""
        if btc_macro is None:
            return signal
        ticker = signal.pair.split("/")[0].upper()
        if ticker == "BTC":
            return signal
        if btc_macro != MacroRegime.BULL:
            tag = f" (BTC macro {btc_macro.value})"
            if tag not in signal.environment:
                signal.environment += tag
        return signal

    @staticmethod
    def analyze_all(
        pairs: List[str],
        context_by_tf: Dict[str, dict],
        regimes: List[RegimeResult],
        *,
        btc_macro: Optional[MacroRegime] = None,
    ) -> List[MultiTFSignal]:
        """Analyze all pairs. *regimes* order must match *pairs*.

        *btc_macro* is the BTC macro regime (from BtcMacroRegimeDetector).
        When provided, environment labels are enriched with macro context.
        """
        regime_map = {r.pair: r for r in regimes}

        results = []
        for pair in pairs:
            regime = regime_map.get(pair)
            if regime is None:
                # fallback: RANGE
                regime = RegimeResult(pair=pair, regime=MarketRegime.RANGE)
            sig = SignalEngine.analyze(pair, context_by_tf, regime, btc_macro=btc_macro)
            sig = SignalEngine._enrich_environment(sig, btc_macro)
            results.append(sig)
        return results
