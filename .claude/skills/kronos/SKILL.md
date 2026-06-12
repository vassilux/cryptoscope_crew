---
name: kronos
description: >
  Use this skill when integrating, calling, or debugging the Kronos
  K-line forecasting model as a CrewAI tool.
  Triggers on: 'Kronos', 'K-line forecast', 'candlestick prediction',
  'OHLCV forecast', 'KronosPredictor', 'foundation model forecast'.
---

# Kronos Forecasting Integration — CryptoScope

## What Kronos Is
Foundation model (decoder Transformer) for financial candlestick sequences.
Trained on 45+ exchanges. Generates future OHLCV candles autoregressively.
Accepted at AAAI 2026. Repo: https://github.com/shiyu-coder/Kronos

## Model Selection

| Model         | Params  | Context | Use case                        |
|---------------|---------|---------|----------------------------------|
| Kronos-mini   | 4.1M    | 2048    | Real-time, low-latency          |
| Kronos-small  | 24.7M   | 512     | Default — good balance          |
| Kronos-base   | 102.3M  | 512     | Higher quality, more GPU/RAM    |

**Default: `NeoQuasar/Kronos-small`**

## Setup

```bash
pip install -r requirements.txt  # includes torch, transformers
# Kronos models download from HuggingFace on first use
```

```python
# config/kronos.py
from model import Kronos, KronosTokenizer, KronosPredictor

def load_kronos(model_name: str = "NeoQuasar/Kronos-small") -> KronosPredictor:
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained(model_name)
    return KronosPredictor(model, tokenizer, max_context=512)

# Lazy singleton — load once per process
_predictor: KronosPredictor | None = None

def get_predictor() -> KronosPredictor:
    global _predictor
    if _predictor is None:
        _predictor = load_kronos()
    return _predictor
```

## CrewAI Tool

```python
# tools/kronos_tool.py
from crewai.tools import tool
from pydantic import BaseModel
from config.kronos import get_predictor
from tools.ccxt_tools import _fetch_ohlcv_df
import pandas as pd

class KronosOutput(BaseModel):
    symbol: str
    timeframe: str
    pred_len: int
    expected_return_pct: float      # % change close[0] → close[-1]
    predicted_high: float           # max predicted high in horizon
    predicted_low: float            # min predicted low in horizon
    predicted_range_pct: float      # (high-low)/entry * 100
    direction: str                  # 'up', 'down', 'flat'
    forecast_horizon: str           # e.g. "24h", "4h"

@tool("kronos_forecast_tool")
def kronos_forecast_tool(symbol: str, timeframe: str = "1h",
                          lookback: int = 400, pred_len: int = 24) -> KronosOutput:
    """
    Forecast the next {pred_len} candles for {symbol} using the Kronos foundation model.
    Returns expected return, predicted range, and direction.
    Treat as probabilistic context — combine with TA and sentiment.
    """
    predictor = get_predictor()
    df = _fetch_ohlcv_df(symbol, timeframe, lookback)

    x_df = df[["open", "high", "low", "close", "volume"]].copy()
    x_timestamp = df.index.to_series()
    
    # Generate future timestamps
    freq = pd.tseries.frequencies.to_offset(timeframe.replace("m", "T").replace("h", "H"))
    last_ts = df.index[-1]
    y_timestamp = pd.Series(
        pd.date_range(start=last_ts + freq, periods=pred_len, freq=freq)
    )

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=1,
    )

    entry = float(df["close"].iloc[-1])
    final_close = float(pred_df["close"].iloc[-1])
    expected_return = (final_close - entry) / entry * 100
    pred_high = float(pred_df["high"].max())
    pred_low = float(pred_df["low"].min())
    pred_range = (pred_high - pred_low) / entry * 100

    direction = "up" if expected_return > 0.5 else "down" if expected_return < -0.5 else "flat"
    horizon_label = f"{pred_len}{timeframe}"

    return KronosOutput(
        symbol=symbol,
        timeframe=timeframe,
        pred_len=pred_len,
        expected_return_pct=round(expected_return, 2),
        predicted_high=round(pred_high, 2),
        predicted_low=round(pred_low, 2),
        predicted_range_pct=round(pred_range, 2),
        direction=direction,
        forecast_horizon=horizon_label,
    )
```

## Batch Forecasting (Multi-Asset)

```python
@tool("kronos_batch_forecast_tool")
def kronos_batch_forecast_tool(symbols: list[str], timeframe: str = "1h",
                                 pred_len: int = 24) -> list[KronosOutput]:
    """
    Forecast all 5 monitored assets simultaneously using GPU batching.
    More efficient than calling kronos_forecast_tool 5 times.
    """
    predictor = get_predictor()
    lookback = 400

    df_list, x_ts_list, y_ts_list = [], [], []
    for symbol in symbols:
        df = _fetch_ohlcv_df(symbol, timeframe, lookback)
        # ... (same timestamp prep as single-asset version)
        df_list.append(df[["open", "high", "low", "close", "volume"]])
        x_ts_list.append(df.index.to_series())
        # build y_timestamp ...

    pred_list = predictor.predict_batch(
        df_list=df_list,
        x_timestamp_list=x_ts_list,
        y_timestamp_list=y_ts_list,
        pred_len=pred_len,
        T=1.0, top_p=0.9, sample_count=1, verbose=False,
    )
    # ... build KronosOutput for each
```

## Important Constraints

- Context limit: 512 candles for Kronos-small/base → max lookback = 512
- At 1h timeframe: 512 candles ≈ 21 days of history
- Kronos does NOT know about: funding rates, order book, on-chain flows, news
- Use `sample_count > 1` for a probability distribution instead of a single path
- Kronos output is one signal among three — TA + sentiment + Kronos → final decision

## Anti-patterns

```python
# WRONG — Kronos used as sole decision-maker
if kronos_output.direction == "up":
    place_order(...)

# WRONG — raw pred_df passed to the LLM agent
Task(description=f"Analyze this forecast DataFrame: {pred_df.to_json()}")
# → always pass the KronosOutput Pydantic model, never raw DataFrames

# WRONG — model reloaded on every tool call (very slow)
model = Kronos.from_pretrained(...)  # inside the tool function
# → use the get_predictor() singleton pattern
```
