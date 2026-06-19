---
name: ccxt-tool
description: >
  Use this skill when writing or modifying exchange connectivity: fetching
  OHLCV, placing orders, checking balances, or managing positions.
  Triggers on: 'CCXT', 'Kraken', 'Binance', 'fetch price', 'place order',
  'get balance', 'open position', 'perpetual', 'spot order', 'exchange'.
---

# CCXT Exchange Connectivity — CryptoScope

## Exchange Setup

```python
# config/exchanges.py
import ccxt
from dotenv import load_dotenv
import os

load_dotenv()

def get_kraken_futures() -> ccxt.krakenfutures:
    return ccxt.krakenfutures({
        "apiKey": os.getenv("KRAKEN_API_KEY"),
        "secret": os.getenv("KRAKEN_SECRET"),
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    })

def get_binance_spot() -> ccxt.binance:
    return ccxt.binance({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
```

## OHLCV Fetching (Internal Helper — Not a Tool)

```python
# tools/ccxt_tools.py
import pandas as pd
import ccxt
from config.exchanges import get_binance_spot

def _fetch_ohlcv_df(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    """Internal helper — returns a DataFrame with OHLCV. Never hardcode prices."""
    exchange = get_binance_spot()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df
```

## CrewAI Tools

```python
from crewai.tools import tool
from pydantic import BaseModel

class PriceOutput(BaseModel):
    symbol: str
    bid: float
    ask: float
    last: float
    exchange: str

@tool("get_live_price_tool")
def get_live_price_tool(symbol: str) -> PriceOutput:
    """Get the current live price for a symbol from Binance."""
    exchange = get_binance_spot()
    ticker = exchange.fetch_ticker(symbol)
    return PriceOutput(
        symbol=symbol,
        bid=ticker["bid"],
        ask=ticker["ask"],
        last=ticker["last"],
        exchange="binance",
    )

class OrderInput(BaseModel):
    symbol: str
    side: str       # 'buy' or 'sell'
    amount: float
    order_type: str = "limit"
    price: float | None = None

class OrderOutput(BaseModel):
    order_id: str
    symbol: str
    side: str
    amount: float
    price: float
    status: str

@tool("place_spot_order_tool")
def place_spot_order_tool(symbol: str, side: str, amount: float,
                           order_type: str = "limit", price: float | None = None) -> OrderOutput:
    """Place a spot order on Binance. Use limit orders by default."""
    exchange = get_binance_spot()
    order = exchange.create_order(symbol, order_type, side, amount, price)
    return OrderOutput(
        order_id=order["id"],
        symbol=order["symbol"],
        side=order["side"],
        amount=float(order["amount"]),
        price=float(order["price"] or order["average"] or 0),
        status=order["status"],
    )
```

## Kraken Perpetuals (Derivatives)

```python
@tool("get_kraken_position_tool")
def get_kraken_position_tool(symbol: str) -> dict:
    """Get current open position on Kraken Futures."""
    exchange = get_kraken_futures()
    positions = exchange.fetch_positions([symbol])
    if not positions:
        return {"symbol": symbol, "size": 0, "side": None, "unrealized_pnl": 0}
    pos = positions[0]
    return {
        "symbol": pos["symbol"],
        "size": pos["contracts"],
        "side": pos["side"],
        "unrealized_pnl": pos["unrealizedPnl"],
        "entry_price": pos["entryPrice"],
        "liquidation_price": pos["liquidationPrice"],
    }

@tool("close_kraken_position_tool")
def close_kraken_position_tool(symbol: str) -> dict:
    """Close all open perpetual positions on Kraken for a symbol."""
    exchange = get_kraken_futures()
    result = exchange.close_position(symbol)
    return {"closed": True, "symbol": symbol, "result": str(result)}
```

## Error Handling

```python
import ccxt

try:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
except ccxt.NetworkError as e:
    raise RuntimeError(f"Network error fetching {symbol}: {e}")
except ccxt.ExchangeError as e:
    raise RuntimeError(f"Exchange error for {symbol}: {e}")
```

## Testing — Always Mock Exchange Calls

```python
# tests/test_ccxt_tools.py
from unittest.mock import patch, MagicMock
from tools.ccxt_tools import get_live_price_tool

@patch("tools.ccxt_tools.get_binance_spot")
def test_get_live_price(mock_exchange_factory):
    mock_exchange = MagicMock()
    mock_exchange.fetch_ticker.return_value = {
        "bid": 65000.0, "ask": 65010.0, "last": 65005.0
    }
    mock_exchange_factory.return_value = mock_exchange

    result = get_live_price_tool("BTC/USDT")
    assert result.last == 65005.0
    assert result.exchange == "binance"
```
