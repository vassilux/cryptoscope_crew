from __future__ import annotations
import ccxt
import pandas as pd
from typing import List
from ..config import ex_cfg

# Simple exchange OHLCV fetcher via CCXT

def get_exchange(name: str | None = None):
    name = name or ex_cfg.name
    ex = getattr(ccxt, name)({
        "apiKey": ex_cfg.key,
        "secret": ex_cfg.secret,
        "enableRateLimit": True,
    })
    return ex

async def fetch_ohlcv_async(
    pair: str, timeframe: str = "1h", limit: int = 1000, exchange_name: str | None = None
) -> pd.DataFrame:
    # NOTE: ccxt async variant exists; here we keep sync for simplicity
    ex = get_exchange(exchange_name)
    data = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(
        data, columns=["timestamp","open","high","low","close","volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df
