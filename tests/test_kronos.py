"""Tests du wrapper Kronos (forecast/kronos.py) — predictor mocké, jamais de
download HuggingFace ni d'appel exchange."""
from __future__ import annotations

import pandas as pd
import pytest

from cryptoscope_crew.forecast.kronos import (
    KRONOS_MAX_CONTEXT,
    KronosForecast,
    _tf_to_offset,
    forecast_from_df,
    kronos_table_md,
)


# ------------------------------------------------------------------ #
#  Fixtures
# ------------------------------------------------------------------ #

def make_ohlcv_df(n: int = 600, start_price: float = 100.0, freq: str = "4h") -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    close = pd.Series([start_price + i * 0.1 for i in range(n)])
    return pd.DataFrame({
        "timestamp": ts,
        "open": close - 0.05,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 1000.0,
    })


class FakePredictor:
    """Predictor déterministe : dernier close × multiplicateur sur l'horizon."""

    def __init__(self, final_multiplier: float = 1.02):
        self.final_multiplier = final_multiplier
        self.last_call = None

    def predict(self, df, x_timestamp, y_timestamp, pred_len, **kwargs):
        self.last_call = {
            "n_rows": len(df),
            "pred_len": pred_len,
            "y_first": y_timestamp.iloc[0],
            **kwargs,
        }
        entry = float(df["close"].iloc[-1])
        final = entry * self.final_multiplier
        closes = [entry + (final - entry) * (i + 1) / pred_len for i in range(pred_len)]
        return pd.DataFrame({
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": 1000.0,
        })


# ------------------------------------------------------------------ #
#  _tf_to_offset
# ------------------------------------------------------------------ #

class TestTfToOffset:
    def test_4h(self):
        assert _tf_to_offset("4h") == pd.tseries.frequencies.to_offset("4h")

    def test_1d(self):
        assert _tf_to_offset("1d") == pd.tseries.frequencies.to_offset("1D")

    def test_15m(self):
        assert _tf_to_offset("15m") == pd.tseries.frequencies.to_offset("15min")


# ------------------------------------------------------------------ #
#  forecast_from_df
# ------------------------------------------------------------------ #

class TestForecastFromDf:
    def test_up_direction(self):
        fake = FakePredictor(final_multiplier=1.02)  # +2%
        df = make_ohlcv_df()
        f = forecast_from_df("BTC/USDC", df, "4h", pred_len=24, predictor=fake)
        assert isinstance(f, KronosForecast)
        assert f.direction == "up"
        assert f.expected_return_pct == pytest.approx(2.0, abs=0.1)

    def test_down_direction(self):
        fake = FakePredictor(final_multiplier=0.97)  # -3%
        f = forecast_from_df("ETH/USDC", make_ohlcv_df(), "4h", pred_len=24, predictor=fake)
        assert f.direction == "down"
        assert f.expected_return_pct == pytest.approx(-3.0, abs=0.1)

    def test_flat_direction(self):
        fake = FakePredictor(final_multiplier=1.001)  # +0.1% < seuil 0.5%
        f = forecast_from_df("SOL/USDC", make_ohlcv_df(), "4h", pred_len=24, predictor=fake)
        assert f.direction == "flat"

    def test_context_truncated_to_max(self):
        fake = FakePredictor()
        df = make_ohlcv_df(n=800)  # > 512
        forecast_from_df("BTC/USDC", df, "4h", pred_len=24, predictor=fake)
        assert fake.last_call["n_rows"] <= KRONOS_MAX_CONTEXT

    def test_y_timestamp_starts_after_last_candle(self):
        fake = FakePredictor()
        df = make_ohlcv_df(n=100, freq="4h")
        forecast_from_df("BTC/USDC", df, "4h", pred_len=24, predictor=fake)
        expected_first = df["timestamp"].iloc[-1] + pd.Timedelta(hours=4)
        assert fake.last_call["y_first"] == expected_first

    def test_range_and_levels(self):
        fake = FakePredictor(final_multiplier=1.02)
        df = make_ohlcv_df()
        f = forecast_from_df("BTC/USDC", df, "4h", pred_len=24, predictor=fake)
        assert f.predicted_high > f.predicted_low
        assert f.predicted_range_pct > 0
        assert f.forecast_horizon == "24x4h"

    def test_no_llm_verbose(self):
        """verbose doit être False pour ne pas spammer la sortie crew."""
        fake = FakePredictor()
        forecast_from_df("BTC/USDC", make_ohlcv_df(), "4h", pred_len=24, predictor=fake)
        assert fake.last_call["verbose"] is False


# ------------------------------------------------------------------ #
#  kronos_table_md
# ------------------------------------------------------------------ #

class TestKronosTableMd:
    def _forecasts(self):
        fake_up = FakePredictor(1.02)
        fake_down = FakePredictor(0.97)
        return [
            forecast_from_df("BTC/USDC", make_ohlcv_df(), "4h", pred_len=24, predictor=fake_up),
            forecast_from_df("ETH/USDC", make_ohlcv_df(), "4h", pred_len=24, predictor=fake_down),
        ]

    def test_empty_returns_empty_string(self):
        assert kronos_table_md([]) == ""

    def test_contains_pairs_and_header(self):
        md = kronos_table_md(self._forecasts())
        assert "## Kronos Forecast" in md
        assert "BTC/USDC" in md
        assert "ETH/USDC" in md

    def test_observation_disclaimer(self):
        md = kronos_table_md(self._forecasts())
        assert "observation" in md.lower()
        assert "décision" in md.lower()

    def test_serialization_roundtrip(self):
        for f in self._forecasts():
            data = f.model_dump(mode="json")
            assert KronosForecast(**data) == f
