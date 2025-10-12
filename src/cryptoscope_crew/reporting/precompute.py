# src/cryptoscope_crew/reporting/precompute.py
from __future__ import annotations
import asyncio, json
from typing import Dict, List

from cryptoscope_crew.market.exchange import fetch_ohlcv_async
from cryptoscope_crew.ta.ema_rsi import ema_rsi_signal  # ema/rsi + signal  :contentReference[oaicite:4]{index=4}

def tech_table_from_context(context: dict) -> str:
    rows = [
        "| Pair | Trend | RSI14 | Bias | Confidence | Notes |",
        "|------|-------|-------|------|------------|-------|",
    ]
    for p in context["pairs"]:
        pair = p["pair"]
        ema_fast, ema_slow, rsi = p["ema_fast"], p["ema_slow"], p["rsi14"]

        trend_up = ema_fast > ema_slow
        trend = "Bullish" if trend_up else "Bearish"
        bias = "Bull" if trend_up else "Bear"

        # écart relatif EMA (plus c'est large, plus la tendance est "forte")
        ema_gap = abs(ema_fast - ema_slow) / max(1e-9, (ema_fast + ema_slow) / 2)

        # score RSI (50=neutre, >55 bon, <45 faible)
        if rsi >= 60:
            rsi_score = 1.0
        elif rsi >= 55:
            rsi_score = 0.8
        elif rsi >= 50:
            rsi_score = 0.65
        elif rsi >= 45:
            rsi_score = 0.5
        elif rsi >= 40:
            rsi_score = 0.35
        else:
            rsi_score = 0.2

        # score tendance vs RSI
        base = 0.55 if trend_up else 0.45
        score = base + 0.5 * ema_gap + 0.5 * (rsi_score - 0.5)
        score = max(0.0, min(1.0, score))

        if score >= 0.75:
            conf = "High"
        elif score >= 0.55:
            conf = "Medium"
        else:
            conf = "Low"

        notes = "TA auto (EMA20/EMA50, RSI14). Confiance pénalisée si RSI<45."
        rows.append(f"| **{pair}** | {trend} | {rsi:.2f} | {bias} | {conf} | {notes} |")
    return "\n".join(rows)

async def _build_context_async(pairs: List[str], timeframe: str, lookback: int) -> Dict:
    dfs = await asyncio.gather(*[fetch_ohlcv_async(p, timeframe, lookback) for p in pairs])  # :contentReference[oaicite:5]{index=5}
    ctx_pairs = []
    for pair, df in zip(pairs, dfs):
        sig = ema_rsi_signal(df).iloc[-1]
        ctx_pairs.append({
            "pair": pair,
            "close": float(df["close"].iloc[-1]),
            "ema_fast": float(sig["ema_fast"]),
            "ema_slow": float(sig["ema_slow"]),
            "rsi14": float(sig["rsi14"]),
            "bias": "bull" if sig["ema_fast"] > sig["ema_slow"] else "bear",
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
