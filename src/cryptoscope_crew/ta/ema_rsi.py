from __future__ import annotations
import pandas as pd

try:
    # If Rust extension is built, import its fast indicators
    from rust_ta import ema as fast_ema, rsi as fast_rsi  # type: ignore
except Exception:
    fast_ema = fast_rsi = None

# Fallback pure‑Python indicators (vectorized with pandas)

def ema(series: pd.Series, span: int) -> pd.Series:
    if fast_ema is not None:
        return pd.Series(fast_ema(series.values.tolist(), span), index=series.index)
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    if fast_rsi is not None:
        return pd.Series(fast_rsi(series.values.tolist(), period), index=series.index)
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-12)
    return 100 - (100 / (1 + rs))

def ema_rsi_signal(df: pd.DataFrame) -> pd.DataFrame:
    # Compute features and a simple signal
    out = df.copy()
    out["ema_fast"] = ema(out["close"], 20)
    out["ema_slow"] = ema(out["close"], 50)
    out["rsi14"] = rsi(out["close"], 14)
    out["trend"] = (out["ema_fast"] > out["ema_slow"]).astype(int)  # 1 bull / 0 bear
    out["signal"] = 0
    buy = (out["trend"] == 1) & (out["rsi14"] < 60)
    sell = (out["trend"] == 0) & (out["rsi14"] > 40)
    out.loc[buy, "signal"] = 1
    out.loc[sell, "signal"] = -1
    return out
