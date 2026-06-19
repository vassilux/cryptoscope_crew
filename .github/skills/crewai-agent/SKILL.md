---
name: crewai-agent
description: >
  Use this skill when creating, modifying, or debugging CrewAI agents,
  tasks, or crews in this project. Triggers on: 'add an agent', 'new task',
  'create a crew', 'modify agent', 'agent not working', 'task output'.
---

# CrewAI Agent & Task Patterns — CryptoScope

## Agent Structure

```python
from crewai import Agent
from tools.ta_tools import compute_indicators_tool
from tools.ccxt_tools import fetch_ohlcv_tool

ta_analyst = Agent(
    role="Technical Analysis Specialist",
    goal="Identify high-confidence entry/exit signals from OHLCV data",
    backstory="Expert in reading candlestick patterns, indicators, and market structure.",
    tools=[compute_indicators_tool, fetch_ohlcv_tool],
    verbose=True,
    max_iter=3,          # prevent infinite loops
    allow_delegation=False,
)
```

## Task Structure — Mandatory Pydantic Output

Every task MUST declare `output_pydantic`. No exceptions.

```python
from crewai import Task
from models.signals import TASignalOutput

ta_task = Task(
    description="""
    Analyze {symbol} on {timeframe} timeframe.
    Use fetch_ohlcv_tool to get the last {lookback} candles.
    Use compute_indicators_tool to calculate RSI, MACD, Bollinger Bands.
    Return a structured signal with entry, stop-loss, take-profit.
    """,
    expected_output="A TASignalOutput with direction, confidence, and levels.",
    output_pydantic=TASignalOutput,   # REQUIRED — fail loud if missing
    agent=ta_analyst,
    context=[],  # list other tasks whose output this task depends on
)
```

## Crew Assembly

```python
from crewai import Crew, Process

crypto_crew = Crew(
    agents=[ta_analyst, sentiment_analyst, signal_aggregator],
    tasks=[ta_task, sentiment_task, aggregation_task],
    process=Process.sequential,  # use hierarchical only if truly needed
    verbose=True,
    memory=False,   # keep stateless — state managed in Pydantic outputs
)

result = crypto_crew.kickoff(inputs={"symbol": "BTC/USDT", "timeframe": "1h", "lookback": 200})
```

## Agent Roles in This Project

| Agent              | Role                        | Key tools                        |
|--------------------|-----------------------------|----------------------------------|
| `ta_analyst`       | Technical analysis          | compute_indicators_tool, fetch_ohlcv_tool |
| `sentiment_analyst`| Macro/political sentiment   | twitter_search_tool, serper_tool |
| `onchain_analyst`  | On-chain metrics            | glassnode_tool                   |
| `signal_aggregator`| Combine signals → decision  | None (reasoning only)            |
| `order_manager`    | Execute / size position     | place_order_tool, get_balance_tool |

## Task Output Chaining

```python
# signal_aggregator task receives outputs from previous tasks via context
aggregation_task = Task(
    description="Combine TA signal, sentiment score, and on-chain data into final decision.",
    output_pydantic=FinalSignalOutput,
    agent=signal_aggregator,
    context=[ta_task, sentiment_task, onchain_task],  # injected as context
)
```

## Anti-patterns to Avoid

```python
# WRONG — LLM asked to compute indicators
Task(description="Calculate the RSI of this OHLCV data: {raw_data}")

# WRONG — no Pydantic schema
Task(description="...", expected_output="A JSON with the signal")  # brittle

# WRONG — delegation enabled with no guardrails
Agent(..., allow_delegation=True, max_iter=10)  # runaway agent risk
```

## Testing Agents

```python
# tests/test_ta_agent.py
from unittest.mock import patch
import pytest

@patch("tools.ccxt_tools.fetch_ohlcv_tool")
def test_ta_task_output_schema(mock_fetch):
    mock_fetch.return_value = load_fixture("btc_1h_200.json")
    result = ta_task.execute({"symbol": "BTC/USDT", "timeframe": "1h", "lookback": 200})
    assert isinstance(result, TASignalOutput)
    assert result.confidence >= 0.0
```
