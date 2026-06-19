from __future__ import annotations
import asyncio
import threading
import ccxt
import pandas as pd
from typing import Dict, List, Optional, Tuple
from ..config import ex_cfg

# Simple exchange OHLCV fetcher via CCXT

# Instances réutilisées (load_markets est coûteux : une fois par instance suffit)
_EXCHANGE_CACHE: Dict[Tuple[str, str], ccxt.Exchange] = {}
_markets_lock = threading.Lock()


def _cached_exchange(name: str, kind: str) -> ccxt.Exchange:
    key = (name, kind)
    ex = _EXCHANGE_CACHE.get(key)
    if ex is None:
        opts = {
            "apiKey": ex_cfg.key,
            "secret": ex_cfg.secret,
            "enableRateLimit": True,
        }
        if kind == "swap":
            opts["options"] = {"defaultType": "swap"}  # perpetual swap for funding/OI
        ex = getattr(ccxt, name)(opts)
        _EXCHANGE_CACHE[key] = ex
    return ex


def _ensure_markets(ex: ccxt.Exchange) -> None:
    """Charge les markets une seule fois, de façon thread-safe."""
    if not getattr(ex, "markets", None):
        with _markets_lock:
            if not getattr(ex, "markets", None):
                ex.load_markets()


def get_exchange(name: str | None = None):
    return _cached_exchange(name or ex_cfg.name, "spot")


def _get_futures_exchange(name: str | None = None):
    """Get exchange instance configured for futures/derivatives (for funding + OI)."""
    return _cached_exchange(name or ex_cfg.name, "swap")


def _fetch_ohlcv_sync(ex: ccxt.Exchange, pair: str, timeframe: str, limit: int) -> list:
    _ensure_markets(ex)
    return ex.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)


async def fetch_ohlcv_async(
    pair: str, timeframe: str = "1h", limit: int = 1000, exchange_name: str | None = None
) -> pd.DataFrame:
    ex = get_exchange(exchange_name)
    # CCXT sync est bloquant : on délègue à un thread pour que asyncio.gather
    # parallélise réellement les fetchs (paires × timeframes).
    data = await asyncio.to_thread(_fetch_ohlcv_sync, ex, pair, timeframe, limit)
    df = pd.DataFrame(
        data, columns=["timestamp","open","high","low","close","volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


# ─────────────────────────────────────────────────────────────────────
#  Funding Rate
# ─────────────────────────────────────────────────────────────────────

def fetch_funding_rate(
    pair: str,
    exchange_name: str | None = None,
) -> Optional[dict]:
    """Fetch current funding rate for a perpetual contract.

    Returns dict with keys: funding_rate, next_funding_time, timestamp
    or None if unavailable.
    """
    try:
        ex = _get_futures_exchange(exchange_name)
        # Convert spot pair to perp symbol if needed (e.g., BTC/USDC → BTC/USDC:USDC)
        perp_symbol = _to_perp_symbol(pair, ex)
        fr = ex.fetch_funding_rate(perp_symbol)
        return {
            "pair": pair,
            "funding_rate": fr.get("fundingRate"),
            "next_funding_time": fr.get("fundingDatetime"),
            "timestamp": fr.get("datetime"),
            "mark_price": fr.get("markPrice"),
            "index_price": fr.get("indexPrice"),
        }
    except Exception:
        return None


def fetch_funding_rate_history(
    pair: str,
    limit: int = 100,
    exchange_name: str | None = None,
) -> pd.DataFrame:
    """Fetch historical funding rates.

    Returns DataFrame with columns: timestamp, funding_rate
    """
    try:
        ex = _get_futures_exchange(exchange_name)
        perp_symbol = _to_perp_symbol(pair, ex)
        history = ex.fetch_funding_rate_history(perp_symbol, limit=limit)
        if not history:
            return pd.DataFrame(columns=["timestamp", "funding_rate"])
        rows = [{"timestamp": h["datetime"], "funding_rate": h["fundingRate"]} for h in history]
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    except Exception:
        return pd.DataFrame(columns=["timestamp", "funding_rate"])


# ─────────────────────────────────────────────────────────────────────
#  Open Interest
# ─────────────────────────────────────────────────────────────────────

def fetch_open_interest(
    pair: str,
    exchange_name: str | None = None,
) -> Optional[dict]:
    """Fetch current open interest for a perpetual contract.

    Returns dict with: open_interest (in contracts), open_interest_value (USD notional)
    or None if unavailable.
    """
    try:
        ex = _get_futures_exchange(exchange_name)
        perp_symbol = _to_perp_symbol(pair, ex)
        oi = ex.fetch_open_interest(perp_symbol)
        return {
            "pair": pair,
            "open_interest": oi.get("openInterestAmount"),
            "open_interest_value": oi.get("openInterestValue"),
            "timestamp": oi.get("datetime"),
        }
    except Exception:
        return None


def fetch_open_interest_history(
    pair: str,
    timeframe: str = "1h",
    limit: int = 48,
    exchange_name: str | None = None,
) -> pd.DataFrame:
    """Fetch historical open interest (where supported by exchange).

    Returns DataFrame with columns: timestamp, open_interest
    """
    try:
        ex = _get_futures_exchange(exchange_name)
        perp_symbol = _to_perp_symbol(pair, ex)
        # Not all exchanges support this; binance does via fetchOpenInterestHistory
        if hasattr(ex, "fetch_open_interest_history"):
            history = ex.fetch_open_interest_history(perp_symbol, timeframe=timeframe, limit=limit)
        else:
            return pd.DataFrame(columns=["timestamp", "open_interest"])
        if not history:
            return pd.DataFrame(columns=["timestamp", "open_interest"])
        rows = [{"timestamp": h.get("datetime") or h.get("timestamp"), "open_interest": h.get("openInterestAmount") or h.get("openInterest")} for h in history]
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    except Exception:
        return pd.DataFrame(columns=["timestamp", "open_interest"])


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

# Résolutions paire spot → symbole perp déjà calculées, par exchange
_PERP_SYMBOL_CACHE: Dict[Tuple[str, str], str] = {}


def _to_perp_symbol(pair: str, ex) -> str:
    """Convert a spot pair like BTC/USDC to the exchange's perpetual symbol.

    Common patterns:
    - Binance: BTC/USDT:USDT
    - Bybit: BTC/USDT:USDT
    - OKX: BTC/USDT:USDT
    """
    # If already has ':' (e.g., BTC/USDT:USDT), return as-is
    if ":" in pair:
        return pair

    cache_key = (getattr(ex, "id", ""), pair)
    cached = _PERP_SYMBOL_CACHE.get(cache_key)
    if cached:
        return cached

    # Try common stablecoin suffixes
    base_quote = pair.split("/")
    if len(base_quote) == 2:
        quote = base_quote[1]
        perp = f"{pair}:{quote}"
        # Verify it exists on the exchange
        try:
            _ensure_markets(ex)
            if perp in ex.markets:
                _PERP_SYMBOL_CACHE[cache_key] = perp
                return perp
            # Try USDT variant if USDC pair
            if quote == "USDC":
                alt = f"{base_quote[0]}/USDT:USDT"
                if alt in ex.markets:
                    _PERP_SYMBOL_CACHE[cache_key] = alt
                    return alt
        except Exception:
            pass
        _PERP_SYMBOL_CACHE[cache_key] = perp
        return perp

    return pair


# ─────────────────────────────────────────────────────────────────────
#  Spot Balances (authenticated)
# ─────────────────────────────────────────────────────────────────────

def fetch_spot_balances(
    assets: Optional[List[str]] = None,
    exchange_name: str | None = None,
) -> Dict[str, float]:
    """Fetch spot wallet balances from exchange.

    Args:
        assets: Optional filter list, e.g. ["BTC", "ETH", "XRP", "USDC"].
                If None, returns all non-zero balances.

    Returns:
        Dict mapping asset → free balance, e.g. {"BTC": 0.00434, "USDC": 3470.0}
    """
    ex = get_exchange(exchange_name)
    balance = ex.fetch_balance()
    free: Dict[str, float] = {}
    for asset, amount in balance.get("free", {}).items():
        if amount and float(amount) > 0:
            if assets is None or asset.upper() in [a.upper() for a in assets]:
                free[asset.upper()] = float(amount)
    return free


def fetch_avg_entry_price(
    pair: str,
    exchange_name: str | None = None,
    since_days: int = 365,
) -> Tuple[float, float]:
    """Calculate average entry price from trade history (FIFO net position).

    Walks through all trades for *pair* in the last *since_days* and computes
    the volume-weighted average price of the current net position.

    Returns:
        (avg_price, net_quantity) — avg_price=0.0 if no position.
    """
    import time

    ex = get_exchange(exchange_name)
    since_ms = int((time.time() - since_days * 86400) * 1000)

    # Fetch all trades (paginated)
    all_trades: List[dict] = []
    params: dict = {}
    while True:
        trades = ex.fetch_my_trades(pair, since=since_ms, limit=1000, params=params)
        if not trades:
            break
        all_trades.extend(trades)
        # Binance pagination: use last trade id
        last_id = trades[-1].get("id")
        if last_id and len(trades) == 1000:
            params = {"fromId": int(last_id) + 1}
            since_ms = None  # type: ignore[assignment]
        else:
            break

    if not all_trades:
        return (0.0, 0.0)

    # FIFO computation: accumulate buys, deduct sells
    net_qty = 0.0
    cost_basis = 0.0

    for t in all_trades:
        side = t.get("side", "").lower()
        qty = float(t.get("amount", 0))
        price = float(t.get("price", 0))

        if side == "buy":
            cost_basis += qty * price
            net_qty += qty
        elif side == "sell":
            if net_qty > 0:
                # Remove proportional cost
                avg = cost_basis / net_qty if net_qty else 0
                removed = min(qty, net_qty)
                cost_basis -= removed * avg
                net_qty -= removed

    if net_qty <= 0:
        return (0.0, 0.0)

    avg_price = cost_basis / net_qty
    return (round(avg_price, 8), round(net_qty, 8))
