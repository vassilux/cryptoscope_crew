# src/cryptoscope_crew/forecast/kronos.py
"""Kronos K-line forecasting — MODE OBSERVATION.

Produit des prévisions OHLCV structurées (KronosForecast) via le foundation
model Kronos (https://github.com/shiyu-coder/Kronos, vendorisé dans
kronos_model/). La sortie est injectée dans le rapport comme contexte
probabiliste : elle n'influence AUCUNE décision tant que sa fiabilité
n'a pas été validée empiriquement.

Le modèle (torch) n'est importé que paresseusement : si torch ou les poids
HuggingFace sont indisponibles, le pipeline continue sans Kronos.
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Optional

import pandas as pd
from pydantic import BaseModel

from cryptoscope_crew.market.exchange import fetch_ohlcv_async

# Configuration (surchargeable par env)
KRONOS_MODEL = os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-small")
KRONOS_TOKENIZER = os.getenv("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
KRONOS_MAX_CONTEXT = 512  # limite dure de Kronos-small/base

_FLAT_THRESHOLD_PCT = 0.5  # |expected_return| sous ce seuil → "flat"


class KronosForecast(BaseModel):
    """Prévision structurée pour une paire — jamais de DataFrame brut vers le LLM."""

    pair: str
    timeframe: str
    pred_len: int
    entry_price: float
    expected_return_pct: float   # % entre close actuel et close prédit final
    predicted_high: float        # max des highs prédits sur l'horizon
    predicted_low: float         # min des lows prédits sur l'horizon
    predicted_range_pct: float   # (high-low)/entry * 100
    direction: str               # "up" / "down" / "flat"
    forecast_horizon: str        # ex: "24x4h"
    sample_count: int = 1


# ------------------------------------------------------------------ #
#  Predictor singleton (lazy — un seul chargement de modèle par process)
# ------------------------------------------------------------------ #

_predictor = None


def get_predictor():
    global _predictor
    if _predictor is None:
        from cryptoscope_crew.forecast.kronos_model import (
            Kronos,
            KronosPredictor,
            KronosTokenizer,
        )
        tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
        model = Kronos.from_pretrained(KRONOS_MODEL)
        # device=None → auto-détection (cuda > mps > cpu)
        _predictor = KronosPredictor(model, tokenizer, max_context=KRONOS_MAX_CONTEXT)
    return _predictor


# ------------------------------------------------------------------ #
#  Forecast
# ------------------------------------------------------------------ #

_FREQ_MAP = {"m": "min", "h": "h", "d": "D", "w": "W"}


def _tf_to_offset(timeframe: str):
    """'4h' → offset pandas 4h, '1d' → D, '15m' → 15min."""
    unit = timeframe[-1].lower()
    num = timeframe[:-1] or "1"
    return pd.tseries.frequencies.to_offset(f"{num}{_FREQ_MAP[unit]}")


def forecast_from_df(
    pair: str,
    df: pd.DataFrame,
    timeframe: str,
    pred_len: int = 24,
    sample_count: int = 1,
    predictor=None,
) -> KronosForecast:
    """Forecast à partir d'un DataFrame OHLCV déjà fetché.

    df doit contenir les colonnes timestamp/open/high/low/close/volume
    (format de fetch_ohlcv_async).
    """
    predictor = predictor or get_predictor()

    # Tronquer au contexte max du modèle
    df = df.tail(KRONOS_MAX_CONTEXT).reset_index(drop=True)
    x_df = df[["open", "high", "low", "close", "volume"]]
    x_timestamp = pd.Series(df["timestamp"])

    freq = _tf_to_offset(timeframe)
    last_ts = df["timestamp"].iloc[-1]
    y_timestamp = pd.Series(pd.date_range(start=last_ts + freq, periods=pred_len, freq=freq))

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=sample_count,
        verbose=False,
    )

    entry = float(df["close"].iloc[-1])
    final_close = float(pred_df["close"].iloc[-1])
    expected_return = (final_close - entry) / entry * 100 if entry else 0.0
    pred_high = float(pred_df["high"].max())
    pred_low = float(pred_df["low"].min())
    pred_range = (pred_high - pred_low) / entry * 100 if entry else 0.0

    if expected_return > _FLAT_THRESHOLD_PCT:
        direction = "up"
    elif expected_return < -_FLAT_THRESHOLD_PCT:
        direction = "down"
    else:
        direction = "flat"

    return KronosForecast(
        pair=pair,
        timeframe=timeframe,
        pred_len=pred_len,
        entry_price=round(entry, 6),
        expected_return_pct=round(expected_return, 2),
        predicted_high=round(pred_high, 6),
        predicted_low=round(pred_low, 6),
        predicted_range_pct=round(pred_range, 2),
        direction=direction,
        forecast_horizon=f"{pred_len}x{timeframe}",
        sample_count=sample_count,
    )


def forecast_pairs(
    pairs: List[str],
    timeframe: Optional[str] = None,
    pred_len: Optional[int] = None,
    lookback: Optional[int] = None,
    sample_count: Optional[int] = None,
) -> List[KronosForecast]:
    """Forecast pour toutes les paires. Les paires en échec sont ignorées (WARN).

    Defaults (surchargeables par env): TF 4h, horizon 24 chandeliers (~4 jours),
    lookback 400 (≤ 512), sample_count 1.
    """
    timeframe = timeframe or os.getenv("KRONOS_TIMEFRAME", "4h")
    pred_len = pred_len or int(os.getenv("KRONOS_PRED_LEN", "24"))
    lookback = min(lookback or int(os.getenv("KRONOS_LOOKBACK", "400")), KRONOS_MAX_CONTEXT)
    sample_count = sample_count or int(os.getenv("KRONOS_SAMPLE_COUNT", "1"))

    async def _fetch_all():
        return await asyncio.gather(
            *[fetch_ohlcv_async(p, timeframe, lookback) for p in pairs]
        )

    dfs = asyncio.run(_fetch_all())

    forecasts: List[KronosForecast] = []
    predictor = get_predictor()
    for pair, df in zip(pairs, dfs):
        try:
            forecasts.append(
                forecast_from_df(pair, df, timeframe, pred_len, sample_count, predictor)
            )
        except Exception as e:
            print(f"[WARN] Kronos forecast failed for {pair}: {e}")
    return forecasts


# ------------------------------------------------------------------ #
#  Rendu markdown (mode observation)
# ------------------------------------------------------------------ #

def kronos_table_md(forecasts: List[KronosForecast]) -> str:
    """Table markdown des forecasts. Vide si aucun forecast."""
    if not forecasts:
        return ""

    _icons = {"up": "🟢 ↑", "down": "🔴 ↓", "flat": "⚪ →"}

    def _fmt(v: float) -> str:
        if v >= 1000:
            return f"{v:.0f}"
        elif v >= 1:
            return f"{v:.4f}"
        return f"{v:.6f}"

    horizon = forecasts[0].forecast_horizon
    rows = [
        f"## Kronos Forecast — mode observation (horizon {horizon})",
        "",
        "| Paire | Prix | Retour attendu | Range prédit | Haut | Bas | Direction |",
        "|-------|------|----------------|--------------|------|-----|-----------|",
    ]
    for f in forecasts:
        rows.append(
            f"| **{f.pair}** | {_fmt(f.entry_price)} | {f.expected_return_pct:+.2f}% | "
            f"{f.predicted_range_pct:.2f}% | {_fmt(f.predicted_high)} | {_fmt(f.predicted_low)} | "
            f"{_icons.get(f.direction, f.direction)} |"
        )
    rows.append("")
    rows.append(
        "_Prévision probabiliste du foundation model Kronos "
        f"({KRONOS_MODEL.split('/')[-1]}). **Phase d'observation** : ces valeurs "
        "n'entrent pas dans le score de conviction ni dans les décisions — "
        "elles servent à évaluer la fiabilité du modèle sur nos paires._"
    )
    return "\n".join(rows)
