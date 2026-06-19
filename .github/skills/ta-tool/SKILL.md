---
name: ta-tool
description: >
  Use this skill when writing, modifying, or debugging technical analysis
  tool functions. Triggers on: 'RSI', 'MACD', 'Bollinger', 'EMA', 'ATR',
  'indicator', 'candlestick', 'ta tool', 'pandas-ta', 'signal calculation'.
---

# Technical Analysis Tools — CryptoScope

## Core Principle
**ALL indicator calculations happen in tool functions using pandas-ta.**
The LLM receives the computed value, never the raw OHLCV array.

## Tool Function Template

```python
# tools/ta_tools.py
import pandas as pd
import pandas_ta as ta
from crewai.tools import tool
from pydantic import BaseModel

class IndicatorInput(BaseModel):
    symbol: str
    timeframe: str
    lookback: int = 200

class IndicatorOutput(BaseModel):
    symbol: str
    timeframe: str
    rsi_14: float
    macd_line: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    ema_20: float
    ema_50: float
    ema_200: float
    atr_14: float
    close: float
    timestamp: str

@tool("compute_indicators_tool")
def compute_indicators_tool(symbol: str, timeframe: str, lookback: int = 200) -> IndicatorOutput:
    """
    Fetch OHLCV data and compute all standard technical indicators for a symbol.
    Returns structured indicator values — never raw data.
    """
    from tools.ccxt_tools import _fetch_ohlcv_df  # internal helper

    df = _fetch_ohlcv_df(symbol, timeframe, lookback)

    # Compute all indicators tool-side
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.ema(length=200, append=True)
    df.ta.atr(length=14, append=True)

    last = df.iloc[-1]

    return IndicatorOutput(
        symbol=symbol,
        timeframe=timeframe,
        rsi_14=round(float(last["RSI_14"]), 2),
        macd_line=round(float(last["MACD_12_26_9"]), 4),
        macd_signal=round(float(last["MACDs_12_26_9"]), 4),
        macd_hist=round(float(last["MACDh_12_26_9"]), 4),
        bb_upper=round(float(last["BBU_20_2.0"]), 2),
        bb_mid=round(float(last["BBM_20_2.0"]), 2),
        bb_lower=round(float(last["BBL_20_2.0"]), 2),
        ema_20=round(float(last["EMA_20"]), 2),
        ema_50=round(float(last["EMA_50"]), 2),
        ema_200=round(float(last["EMA_200"]), 2),
        atr_14=round(float(last["ATRr_14"]), 4),
        close=round(float(last["close"]), 2),
        timestamp=str(last.name),
    )
```

## Adding a New Indicator

```python
# Example: add Stochastic RSI
df.ta.stochrsi(length=14, rsi_length=14, k=3, d=3, append=True)
# Column names: STOCHRSIk_14_14_3_3, STOCHRSId_14_14_3_3
last["STOCHRSIk_14_14_3_3"]
```

## pandas-ta Column Naming Convention

| Indicator | pandas-ta column name               |
|-----------|-------------------------------------|
| RSI(14)   | `RSI_14`                            |
| MACD      | `MACD_12_26_9`, `MACDs_12_26_9`, `MACDh_12_26_9` |
| BB(20,2)  | `BBU_20_2.0`, `BBM_20_2.0`, `BBL_20_2.0` |
| EMA(20)   | `EMA_20`                            |
| ATR(14)   | `ATRr_14`                           |
| Volume    | `OBV` (On-Balance Volume)           |

## Market Structure Helper

```python
@tool("detect_market_structure_tool")
def detect_market_structure_tool(symbol: str, timeframe: str) -> dict:
    """Detect trend direction and key support/resistance levels dynamically."""
    df = _fetch_ohlcv_df(symbol, timeframe, 200)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.ema(length=200, append=True)

    last = df.iloc[-1]
    ema20, ema50, ema200 = last["EMA_20"], last["EMA_50"], last["EMA_200"]
    close = last["close"]

    if close > ema20 > ema50 > ema200:
        trend = "strong_uptrend"
    elif close < ema20 < ema50 < ema200:
        trend = "strong_downtrend"
    else:
        trend = "ranging"

    # Dynamic S/R from recent highs/lows — never hardcoded
    resistance = df["high"].rolling(20).max().iloc[-1]
    support = df["low"].rolling(20).min().iloc[-1]

    return {"trend": trend, "resistance": round(resistance, 2), "support": round(support, 2)}
```

## Anti-patterns

```python
# WRONG — hardcoded levels
support = 58000.0

# WRONG — LLM computes indicators
Task(description="Is RSI above 70 for this data? {ohlcv_json}")

# WRONG — NaN not handled
last["RSI_14"]  # may be NaN for first 14 rows — always check or slice
df = df.iloc[200:]  # keep only rows where all indicators are computed
```
