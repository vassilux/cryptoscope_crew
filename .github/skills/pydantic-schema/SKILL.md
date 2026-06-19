---
name: pydantic-schema
description: >
  Use this skill when creating or modifying Pydantic models for agent
  outputs, task validation, or API response parsing.
  Triggers on: 'Pydantic', 'output schema', 'BaseModel', 'task output',
  'validation', 'output_pydantic', 'signal model', 'response model'.
---

# Pydantic Output Schemas — CryptoScope

## Principle
Every CrewAI task output must map to a typed Pydantic model.
**Silent failures = corrupted downstream decisions. Fail loud, always.**

## Core Signal Models

```python
# models/signals.py
from pydantic import BaseModel, Field, validator
from typing import Literal
from datetime import datetime

class TASignalOutput(BaseModel):
    symbol: str
    timeframe: str
    signal: Literal["long", "short", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    risk_reward_ratio: float = Field(ge=0)
    indicators: dict[str, float]   # rsi, macd, ema_trend, etc.
    reasoning: str

    @validator("stop_loss")
    def stop_loss_below_entry_for_long(cls, v, values):
        if values.get("signal") == "long" and v >= values.get("entry_price", 0):
            raise ValueError("stop_loss must be below entry_price for long signal")
        return v

class SentimentOutput(BaseModel):
    symbol: str
    sentiment: Literal["bullish", "bearish", "neutral"]
    score: float = Field(ge=-1.0, le=1.0)   # -1 bearish, +1 bullish
    key_events: list[str]
    sources_count: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class OnChainOutput(BaseModel):
    symbol: str
    sopr: float | None           # Spent Output Profit Ratio
    nupl: float | None           # Net Unrealized Profit/Loss
    exchange_netflow: float | None  # negative = outflows (accumulation)
    fear_greed_index: int | None    # 0-100
    signal: Literal["accumulate", "distribute", "neutral"]

class FinalSignalOutput(BaseModel):
    symbol: str
    action: Literal["open_long", "open_short", "close", "hold", "dca"]
    confidence: float = Field(ge=0.0, le=1.0)
    position_size_pct: float = Field(ge=0.0, le=1.0)  # % of available capital
    entry_price: float
    stop_loss: float
    take_profit: float
    ta_weight: float = 0.5
    sentiment_weight: float = 0.3
    onchain_weight: float = 0.2
    rationale: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

## DCA / Accumulation Models

```python
# models/accumulation.py
class DCAOrderOutput(BaseModel):
    symbol: str
    zone_low: float
    zone_high: float
    order_price: float
    size_usdt: float
    order_type: Literal["limit", "market"]
    exchange: Literal["binance", "kraken"]
    rationale: str
```

## Validation in Tasks

```python
# tasks/ta_task.py
from crewai import Task
from models.signals import TASignalOutput

ta_task = Task(
    description="...",
    output_pydantic=TASignalOutput,  # parsing error → raises, never None
    agent=ta_analyst,
)

# Accessing output safely
result = crew.kickoff(inputs={...})
signal: TASignalOutput = result.pydantic  # typed access
print(signal.confidence, signal.entry_price)
```

## Fail-Loud Pattern

```python
# If you ever parse manually (avoid this — prefer output_pydantic on task)
import json
from pydantic import ValidationError

def parse_agent_output(raw: str) -> TASignalOutput:
    try:
        data = json.loads(raw)
        return TASignalOutput(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        # Never return None or {} — raise and let the crew handle it
        raise ValueError(f"Agent output parse failure: {e}\nRaw: {raw[:200]}")
```

## Schema Evolution Rules

- Add new fields with `default=None` or `default_factory` to stay backward-compatible
- Use `Literal` for enums — never bare strings for categorical fields
- Always validate cross-field logic with `@validator` (e.g., SL < entry for longs)
- Keep `reasoning` / `rationale` fields as `str` — useful for debugging hallucinations
