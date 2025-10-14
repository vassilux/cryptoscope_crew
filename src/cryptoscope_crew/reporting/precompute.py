# src/cryptoscope_crew/reporting/precompute.py
from __future__ import annotations
import asyncio, json
from typing import Dict, List

import numpy as np
import pandas as pd

from cryptoscope_crew.market.exchange import fetch_ohlcv_async
from cryptoscope_crew.ta.ema_rsi import ema_rsi_signal  # ema/rsi + signal  :contentReference[oaicite:4]{index=4}

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
        rsi = float(last["rsi14"])
        atr = float(last["atr14"])

        ctx_pairs.append({
            "pair": pair,
            "close": close,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi14": rsi,
            "atr14": atr,
            "bias": "bull" if ema_fast > ema_slow else "bear",
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

