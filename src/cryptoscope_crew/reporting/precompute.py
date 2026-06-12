# src/cryptoscope_crew/reporting/precompute.py
from __future__ import annotations
import asyncio, json
from typing import Dict, List

import numpy as np
import pandas as pd

from cryptoscope_crew.market.exchange import (
    fetch_ohlcv_async,
    fetch_funding_rate,
    fetch_open_interest,
    fetch_open_interest_history,
)
from cryptoscope_crew.ta.ema_rsi import ema_rsi_signal  # ema/rsi + signal  :contentReference[oaicite:4]{index=4}
from cryptoscope_crew.ta.price_action import (
    analyze_price_action,
    choppiness_index,
    PriceActionContext,
)
from cryptoscope_crew.ta.confluence_score import compute_confluence_score, ScoringConfig
from cryptoscope_crew.domain.regime_flow import analyze_regime_flow, FlowRegimeResult

def tech_table_from_context(context: dict) -> str:
    rows = [
        "| Pair | Close | EMA20 | EMA50 | RSI14 | ATR14 | Bias | Conf | Notes |",
        "|------|-------|-------|-------|-------|-------|------|------|-------|",
    ]
    for p in context["pairs"]:
        pair = p["pair"]
        close = p.get("close")
        ema_fast = p.get("ema_fast")
        ema_slow = p.get("ema_slow")
        rsi = p.get("rsi14")
        atr = p.get("atr14")

        trend_up = ema_fast > ema_slow
        bias = "Bull" if trend_up else "Bear"

        # qualité de tendance + confiance
        ema_gap = abs(ema_fast - ema_slow) / max(1e-9, (ema_fast + ema_slow) / 2)
        if   rsi >= 60: rsi_score = 1.0
        elif rsi >= 55: rsi_score = 0.8
        elif rsi >= 50: rsi_score = 0.65
        elif rsi >= 45: rsi_score = 0.5
        elif rsi >= 40: rsi_score = 0.35
        else:           rsi_score = 0.2
        base = 0.55 if trend_up else 0.45
        score = max(0.0, min(1.0, base + 0.5*ema_gap + 0.5*(rsi_score-0.5)))
        conf = "High" if score>=0.75 else "Medium" if score>=0.55 else "Low"

        if trend_up and rsi < 45:
            note = "Tendance haussière mais momentum faible (RSI<45) : prudence, risque d’invalidation."
        elif (not trend_up) and rsi > 55:
            note = "Tendance baissière mais momentum ferme (RSI>55) : risque de squeeze/retournement."
        else:
            note = "TA auto (Close, EMA20/EMA50, RSI14, ATR14)."

        rows.append(
            f"| **{pair}** | {close:.4f} | {ema_fast:.4f} | {ema_slow:.4f} | "
            f"{rsi:.2f} | {atr:.4f} | {bias} | {conf} | {note} |"
        )
    return "\n".join(rows)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _rsi14(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0)
    down = -diff.clip(upper=0)
    roll_up = up.ewm(alpha=1/n, adjust=False).mean()
    roll_down = down.ewm(alpha=1/n, adjust=False).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)

def _atr14(df: pd.DataFrame, n: int = 14) -> pd.Series:
    # df: columns ["open","high","low","close"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    # Wilder’s smoothing (EMA alpha = 1/n)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = _ema(out["close"], 20)
    out["ema50"] = _ema(out["close"], 50)
    out["ema200"] = _ema(out["close"], 200)
    out["rsi14"] = _rsi14(out["close"], 14)
    out["atr14"] = _atr14(out, 14)
    return out

def triggers_from_context(context: dict) -> str:
    """Génère des triggers simples par paire (TF = context['timeframe'])."""
    lines = []
    tf = context.get("timeframe", "?")
    lines.append(f"_Timeframe: {tf}_")
    for p in context["pairs"]:
        pair = p["pair"]; c = p["close"]; e20 = p["ema_fast"]; e50 = p["ema_slow"]; r = p["rsi14"]
        # Règles simples & transparentes:
        # Long trigger: close > EMA20 && RSI>45 ; Confirm: close > EMA50 || Higher High sur TF inférieur (optionnel)
        # Short trigger: close < EMA20 && RSI<55 (si trend bear, on préfère RSI<50/45) ; Confirm: close < EMA50
        if e20 > e50:
            long_trig  = f"Clôture > EMA20 ({e20:.4f}) ET RSI>45"
            long_conf  = f"Renfort si clôture > EMA50 ({e50:.4f})"
            invalid    = f"Clôture < EMA50 ({e50:.4f}) OU RSI<40"
            bias = "Bull"
        else:
            long_trig  = f"Reclaim EMA20 ({e20:.4f}) + RSI>45 (setup contre-tendance)"
            long_conf  = f"Puis clôture > EMA50 ({e50:.4f}) pour valider"
            invalid    = f"Clôture < EMA20 ({e20:.4f}) confirmée OU RSI<40"
            bias = "Bear"

        if e20 > e50:
            short_trig = f"Rejet EMA20 ({e20:.4f}) AVEC RSI<55 (contre-tendance)"
            short_conf = f"Valide si clôture < EMA50 ({e50:.4f})"
        else:
            short_trig = f"Clôture < EMA20 ({e20:.4f}) ET RSI<50"
            short_conf = f"Renfort si clôture < EMA50 ({e50:.4f})"

        lines.append(
            f"- **{pair}** ({bias})  \n"
            f"  • Long: {long_trig} → {long_conf}  \n"
            f"  • Short: {short_trig} → {short_conf}  \n"
            f"  • Invalidation: {invalid}"
        )
    return "\n".join(lines)

async def _build_context_async(pairs: List[str], timeframe: str, lookback: int) -> Dict:
    dfs = await asyncio.gather(*[fetch_ohlcv_async(p, timeframe, lookback) for p in pairs])
    ctx_pairs = []
    for pair, df in zip(pairs, dfs):
        # <-- calcule les indicateurs numériques
        df = compute_indicators(df)
        last = df.iloc[-1]
        close = float(last["close"])
        ema_fast = float(last["ema20"])
        ema_slow = float(last["ema50"])
        ema200 = float(last["ema200"])
        rsi = float(last["rsi14"])
        atr = float(last["atr14"])

        # Price Action analysis
        pa_ctx = analyze_price_action(df, swing_length=50, internal_length=5)

        # Confluence scoring
        n = len(df) - 1
        confluence = compute_confluence_score(
            pa_context=pa_ctx,
            current_bar=n,
            current_close=close,
            current_low=float(last["low"]) if "low" in last.index else close,
            current_high=float(last["high"]) if "high" in last.index else close,
            atr=atr,
            htf_structure_trend=None,  # filled later in multi-TF
        )

        ctx_pairs.append({
            "pair": pair,
            "close": close,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema200": ema200,
            "rsi14": rsi,
            "atr14": atr,
            "bias": "bull" if ema_fast > ema_slow else "bear",
            # Price Action enrichment
            "structure_trend": pa_ctx.structure_trend,
            "last_bos_type": pa_ctx.last_bos_type,
            "last_bos_direction": pa_ctx.last_bos_direction,
            "chop_value": pa_ctx.chop_value,
            "chop_regime": pa_ctx.chop_regime,
            "price_zone": pa_ctx.price_zone,
            "active_fvg_count": len([f for f in pa_ctx.fvg_zones if not f.mitigated]),
            "active_ob_count": len([ob for ob in pa_ctx.order_blocks if not ob.breaker]),
            "recent_sweeps": len(pa_ctx.liquidity_sweeps[-5:]) if pa_ctx.liquidity_sweeps else 0,
            # Confluence scores
            "confluence_bull": confluence.bull_score,
            "confluence_bear": confluence.bear_score,
            "confluence_setup": "BULL" if confluence.bullish_setup else "BEAR" if confluence.bearish_setup else "NONE",
        })
    return {"timeframe": timeframe, "pairs": ctx_pairs}


def build_context(pairs: List[str], timeframe: str, lookback: int) -> Dict:
    return asyncio.run(_build_context_async(pairs, timeframe, lookback))

def precompute(pairs: List[str], timeframe: str, lookback: int) -> Dict[str, str]:
    """
    Retourne un dict prêt à injecter dans Crew inputs:
      - context_json
      - tech_table_md
    """
    ctx = build_context(pairs, timeframe, lookback)
    return {
        "context_json": json.dumps(ctx),
        "tech_table_md": tech_table_from_context(ctx)
    }
def precompute_multi(pairs: list[str], timeframes: list[str], lookback: int) -> dict:
    """Retourne:
       - context_by_tf: { "1d": {...}, "4h": {...}, ... }
       - tables_by_tf: { "1d": "markdown", "4h": "markdown", ... }
       - summary_table_md: "markdown" (biais par TF + score d'alignement)
    """
    context_by_tf, tables_by_tf = {}, {}
    for tf in timeframes:
        ctx = build_context(pairs, tf, lookback)
        context_by_tf[tf] = ctx
        tables_by_tf[tf] = tech_table_from_context(ctx)

    # tableau de synthèse (biais par TF + score)
    rows = ["| Pair | 1D | 4H | 1H | Alignement |",
            "|------|----|----|----|-----------|"]
    def col(p, tf):
        # "Bull" / "Bear" depuis le contexte
        r = next(x for x in context_by_tf[tf]["pairs"] if x["pair"] == p)
        return "Bull" if r["ema_fast"] > r["ema_slow"] else "Bear"
    for p in pairs:
        b1d = col(p, "1d") if "1d" in context_by_tf else "-"
        b4h = col(p, "4h") if "4h" in context_by_tf else "-"
        b1h = col(p, "1h") if "1h" in context_by_tf else "-"
        votes = [b for b in (b1d, b4h, b1h) if b in ("Bull","Bear")]
        bull = votes.count("Bull"); bear = votes.count("Bear")
        align = f"{max(bull,bear)}/{len(votes)}"
        rows.append(f"| **{p}** | {b1d} | {b4h} | {b1h} | {align} |")
    summary_md = "\n".join(rows)

    return {
        "context_by_tf": context_by_tf,
        "tables_by_tf": tables_by_tf,
        "summary_table_md": summary_md
    }


def _fmt_pct(x: float) -> str:
    s = f"{x:.2f}%"
    return s.replace(".00%", "%")

def _pct_to_level(price: float, level: float) -> float:
    if price == 0:
        return 0.0
    return (level - price) / price * 100.0

def _fmt_pct_signed(price: float, level: float) -> str:
    if not price:
        return "0%"
    pct = (level - price) / price * 100.0
    s = f"{pct:.2f}%"
    return s.replace(".00%", "%")

def ready_signals_from_context(context: dict, label: str | None = None) -> str:
    """
    Sortie compacte par paire :
      - Etat vs EMA20/EMA50 : "déjà > ..." ou "X% à franchir"
      - RSI : "≥45 ok"/"≥50 ok" sinon deltas "→45: x.xx pts"
      - Tag 'À portée' si distance à EMA20 < 0.5×ATR(14)
    """
    tf = label or context.get("timeframe", "?")
    lines = [f"_Timeframe: {tf}_"]
    for p in context["pairs"]:
        pair  = p["pair"]
        price = p["close"]
        ema20 = p["ema_fast"]
        ema50 = p["ema_slow"]
        rsi   = p["rsi14"]
        atr   = p.get("atr14", None)

        def ema_state(level: float) -> str:
            if price > level:
                return f"déjà > {level:.4f}"
            return f"{_fmt_pct_signed(price, level)} à franchir"

        s20 = ema_state(ema20)
        s50 = ema_state(ema50)

        tag = ""
        if atr and price:
            dist_pct = abs((ema20 - price) / price) * 100
            half_atr_pct = (0.5 * atr / price) * 100
            if price < ema20 and dist_pct <= half_atr_pct:
                tag = " — **À portée**"

        r45 = "≥45 ok" if rsi >= 45 else f"→45: {45 - rsi:.2f} pts"
        r50 = "≥50 ok" if rsi >= 50 else f"→50: {50 - rsi:.2f} pts"

        lines.append(
            f"- **{pair}**  \n"
            f"  • Prix={price:.4f} | EMA20: {s20} | EMA50: {s50}{tag}  \n"
            f"  • RSI={rsi:.2f} ({r45}; {r50})"
        )
    return "\n".join(lines)

def ready_signals_multi(context_by_tf: dict, order: list[str] = None) -> str:
    order = order or ["1d", "4h", "1h"]
    blocks = []
    for tf in order:
        ctx = context_by_tf.get(tf)
        if ctx:
            blocks.append(ready_signals_from_context(ctx, tf))
    return "\n\n".join(blocks)


# ─────────────────────────────────────────────────────────────────────
#  Regime + Flow enrichment
# ─────────────────────────────────────────────────────────────────────

def precompute_flow(pairs: List[str], context_by_tf: Dict[str, dict]) -> Dict[str, FlowRegimeResult]:
    """Compute Regime+Flow analysis for each pair.

    Uses 4H context for CHOP + EMAs, fetches funding rate and OI from exchange.

    Returns dict: {pair: FlowRegimeResult}
    """
    results = {}
    # Prefer 4H for regime detection; fall back to 1D
    regime_tf = "4h" if "4h" in context_by_tf else "1d"
    ctx = context_by_tf.get(regime_tf, {})

    for p_data in ctx.get("pairs", []):
        pair = p_data["pair"]
        close = p_data["close"]
        ema20 = p_data["ema_fast"]
        ema50 = p_data["ema_slow"]
        ema200 = p_data.get("ema200", ema50)  # fallback if missing
        chop_val = p_data.get("chop_value", 50.0)

        # Fetch funding rate
        fr_data = fetch_funding_rate(pair)
        funding_rate = fr_data["funding_rate"] if fr_data and fr_data.get("funding_rate") is not None else None

        # Fetch OI and compute 24h change
        oi_change_pct = _compute_oi_change(pair)

        result = analyze_regime_flow(
            pair=pair,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            close=close,
            chop_value=chop_val,
            oi_change_pct=oi_change_pct,
            funding_rate=funding_rate,
        )
        results[pair] = result

    return results


def _compute_oi_change(pair: str) -> float:
    """Compute OI % change over ~24h. Returns 0.0 if data unavailable."""
    try:
        oi_df = fetch_open_interest_history(pair, timeframe="1h", limit=48)
        if oi_df.empty or len(oi_df) < 2:
            return 0.0
        oi_now = float(oi_df["open_interest"].iloc[-1])
        # ~24h ago (24 bars on 1h)
        lookback_idx = max(0, len(oi_df) - 25)
        oi_then = float(oi_df["open_interest"].iloc[lookback_idx])
        if oi_then == 0:
            return 0.0
        return ((oi_now - oi_then) / oi_then) * 100.0
    except Exception:
        return 0.0


def flow_summary_table(flow_results: Dict[str, FlowRegimeResult]) -> str:
    """Generate a markdown table summarizing Regime+Flow for all pairs."""
    rows = [
        "| Pair | Regime | Direction | Conv. | EMA | CHOP | OI Δ24h | Funding | Size% | Exit |",
        "|------|--------|-----------|-------|-----|------|---------|---------|-------|------|",
    ]
    for pair, r in flow_results.items():
        ema_icon = "✓" if r.ema_aligned else "✗"
        chop_icon = "✓" if r.chop_trending else "✗"
        oi_icon = "✓" if r.oi_rising else "✗"
        fund_icon = "✓" if r.funding_favorable else "✗"
        exit_str = r.exit_signal.value if r.exit_signal.value != "NONE" else "-"
        rows.append(
            f"| **{pair}** | {r.regime.value} | {r.direction} | {r.conviction_score}/4 | "
            f"{ema_icon} | {chop_icon} ({r.chop_value:.0f}) | {oi_icon} ({r.oi_change_pct:+.1f}%) | "
            f"{fund_icon} ({r.funding_rate*100:.3f}%) | {r.suggested_size_pct:.1f}% | {exit_str} |"
        )
    return "\n".join(rows)


# ─────────────────────────────────────────────────────────────────────
#  Niveaux Clés (déterministe)
# ─────────────────────────────────────────────────────────────────────

def key_levels_table(context_by_tf: Dict[str, Dict], pivot_tf: str = "4h") -> str:
    """Generate a deterministic 'Niveaux Clés' table from 4H data.

    For each pair:
      - Support: recent low or EMA50 1D (whichever is lower)
      - Resistance: EMA50 4H
      - Trigger Long: clôture 4H > EMA50 + RSI > 55
      - Trigger Short: clôture < support
    """
    ctx = context_by_tf.get(pivot_tf, {})
    pairs_data = ctx.get("pairs", [])
    if not pairs_data:
        return ""

    # Also grab 1D data for support levels
    ctx_1d = context_by_tf.get("1d", {})
    pairs_1d = {p["pair"]: p for p in ctx_1d.get("pairs", [])}

    rows = [
        "## Niveaux Clés",
        "",
        "| Paire | Prix | Support | Résistance | Trigger Long | Trigger Short |",
        "|-------|------|---------|------------|--------------|---------------|",
    ]
    for p in pairs_data:
        pair = p["pair"]
        close = p["close"]
        ema50_4h = p["ema_slow"]
        ema20_4h = p["ema_fast"]

        # Support: min(EMA50 1D, recent low proxy = close - ATR*2)
        p_1d = pairs_1d.get(pair, {})
        ema50_1d = p_1d.get("ema_slow", ema50_4h)
        atr = p.get("atr14", 0)
        support = min(ema50_1d, close - atr * 2) if atr else ema50_1d

        # Resistance: EMA50 4H (key reclaim level)
        resistance = ema50_4h

        # Format numbers based on magnitude
        def _fmt(v):
            if v >= 1000:
                return f"{v:.0f}"
            elif v >= 1:
                return f"{v:.4f}"
            else:
                return f"{v:.6f}"

        trigger_long = f">{_fmt(ema50_4h)} + RSI>55"
        trigger_short = f"<{_fmt(support)}"

        rows.append(
            f"| **{pair}** | {_fmt(close)} | {_fmt(support)} | "
            f"{_fmt(resistance)} | {trigger_long} | {trigger_short} |"
        )

    return "\n".join(rows)


# ─────────────────────────────────────────────────────────────────────
#  Coherence Check (social vs technique)
# ─────────────────────────────────────────────────────────────────────

def coherence_note(
    context_by_tf: Dict[str, Dict],
    social_sentiment: str = "",
    pivot_tf: str = "4h",
) -> str:
    """Generate a coherence note when social sentiment contradicts technical structure.

    Returns a markdown note if there's a divergence, empty string otherwise.
    """
    if not social_sentiment:
        return ""

    # Determine social bias
    social_label = social_sentiment.strip().upper()
    social_bull = social_label in ("BULL", "BULLISH")
    social_bear = social_label in ("BEAR", "BEARISH")

    if not (social_bull or social_bear):
        return ""

    # Count technical biases from pivot TF
    ctx = context_by_tf.get(pivot_tf, {})
    pairs_data = ctx.get("pairs", [])
    if not pairs_data:
        return ""

    bear_count = 0
    bull_count = 0
    for p in pairs_data:
        close = p["close"]
        ema50 = p["ema_slow"]
        if close < ema50:
            bear_count += 1
        else:
            bull_count += 1

    total = len(pairs_data)

    # Detect contradiction
    if social_bull and bear_count >= total * 0.6:
        return (
            "## ⚠️ Divergence Social / Technique\n\n"
            f"Le sentiment social est **BULL** mais {bear_count}/{total} paires sont sous "
            f"leur EMA50 {pivot_tf.upper()}. Le social est un accélérateur potentiel, pas un "
            "déclencheur. Attendre les confirmations techniques (reclaim EMA50 + RSI>55) "
            "avant d'agir sur le narratif."
        )
    elif social_bear and bull_count >= total * 0.6:
        return (
            "## ⚠️ Divergence Social / Technique\n\n"
            f"Le sentiment social est **BEAR** mais {bull_count}/{total} paires sont au-dessus "
            f"de leur EMA50 {pivot_tf.upper()}. Le pessimisme social ne reflète pas la structure "
            "technique. Les positions existantes restent valides tant que les supports tiennent."
        )

    return ""
