# src/cryptoscope_crew/ta/price_action.py
"""Price Action Concepts — pure pandas/numpy implementation.

Mirrors the logic from the Pine Script indicator:
- Swing point detection (pivot highs/lows)
- Market Structure classification (BOS / CHoCH)
- Fair Value Gaps (FVG)
- Order Blocks (OB)
- Liquidity Sweeps
- Equal Highs/Lows
- Premium/Discount/Equilibrium Zones
- Choppiness Index (CHOP)

All functions operate on a DataFrame with columns:
  timestamp, open, high, low, close, volume
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────
#  Data types
# ─────────────────────────────────────────────────────────────────────

class StructureType(str, Enum):
    BOS = "BOS"       # Break of Structure (continuation)
    CHOCH = "CHoCH"   # Change of Character (reversal)


class Direction(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"


@dataclass
class SwingPoint:
    index: int          # bar index in the DataFrame
    price: float
    is_high: bool       # True = swing high, False = swing low
    label: str = ""     # HH, HL, LH, LL


@dataclass
class StructureBreak:
    bar_index: int
    price: float        # level that was broken
    direction: Direction
    structure_type: StructureType
    swing_level: str = ""  # "swing" or "internal"


@dataclass
class FairValueGap:
    bar_index: int      # middle candle of the 3-bar pattern
    top: float
    bottom: float
    is_bull: bool
    mitigated: bool = False
    mitigated_at: Optional[int] = None


@dataclass
class OrderBlock:
    bar_index: int
    top: float
    bottom: float
    direction: Direction  # BULL = demand zone, BEAR = supply zone
    volume: float = 0.0
    breaker: bool = False  # True = OB has been broken (breaker block)
    breaker_at: Optional[int] = None


@dataclass
class LiquiditySweep:
    bar_index: int
    pivot_price: float
    sweep_price: float   # wick extreme
    direction: Direction  # BULL = swept low then closed above, BEAR = swept high then closed below


@dataclass
class PriceActionContext:
    """Aggregated price action analysis for a single pair/timeframe."""
    swing_points: List[SwingPoint] = field(default_factory=list)
    structure_breaks: List[StructureBreak] = field(default_factory=list)
    fvg_zones: List[FairValueGap] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    liquidity_sweeps: List[LiquiditySweep] = field(default_factory=list)
    structure_trend: int = 0         # >0 bullish BOS count, <0 bearish
    last_bos_type: Optional[str] = None  # "BOS" or "CHoCH" or None
    last_bos_direction: Optional[str] = None
    chop_value: float = 50.0
    chop_regime: str = "neutral"     # "trending" / "choppy" / "neutral"
    price_zone: str = "equilibrium"  # "premium" / "discount" / "equilibrium"


# ─────────────────────────────────────────────────────────────────────
#  Swing Point Detection
# ─────────────────────────────────────────────────────────────────────

def detect_swing_points(df: pd.DataFrame, length: int = 50) -> List[SwingPoint]:
    """Detect pivot highs and lows using a rolling window.

    A pivot high at bar i requires high[i] to be the highest in
    [i-length, i+length]. Same logic for pivot low.
    Mirrors Pine's ta.pivothigh(length, length) / ta.pivotlow(length, length).
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    points: List[SwingPoint] = []

    prev_high = 0.0
    prev_low = float("inf")

    for i in range(length, n - length):
        # Pivot high: high[i] is the max in the window
        window_high = highs[i - length: i + length + 1]
        if highs[i] == window_high.max() and highs[i] != highs[i - 1]:
            label = "HH" if highs[i] > prev_high else "LH"
            points.append(SwingPoint(index=i, price=float(highs[i]), is_high=True, label=label))
            prev_high = float(highs[i])

        # Pivot low: low[i] is the min in the window
        window_low = lows[i - length: i + length + 1]
        if lows[i] == window_low.min() and lows[i] != lows[i - 1]:
            label = "LL" if lows[i] < prev_low else "HL"
            points.append(SwingPoint(index=i, price=float(lows[i]), is_high=False, label=label))
            prev_low = float(lows[i])

    return points


def detect_internal_structure(df: pd.DataFrame, length: int = 5) -> List[SwingPoint]:
    """Detect internal (short-term) swing points with a smaller lookback."""
    return detect_swing_points(df, length=length)


# ─────────────────────────────────────────────────────────────────────
#  Market Structure (BOS / CHoCH)
# ─────────────────────────────────────────────────────────────────────

def classify_structure(
    df: pd.DataFrame,
    swing_points: List[SwingPoint],
    level: str = "swing",
) -> List[StructureBreak]:
    """Classify structure breaks as BOS or CHoCH.

    Logic (mirrors Pine lines 930-1050):
    - Track current trend (1 = bull, -1 = bear).
    - When close crosses above the last swing high:
      - If trend was already bull → BOS (continuation)
      - If trend was bear → CHoCH (reversal)
    - When close crosses below the last swing low:
      - If trend was already bear → BOS (continuation)
      - If trend was bull → CHoCH (reversal)
    """
    closes = df["close"].values
    breaks: List[StructureBreak] = []
    trend = 0  # 0 = undetermined, 1 = bull, -1 = bear

    # Separate highs and lows
    swing_highs = [sp for sp in swing_points if sp.is_high]
    swing_lows = [sp for sp in swing_points if not sp.is_high]

    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None
    high_crossed = False
    low_crossed = False

    for i in range(len(closes)):
        # Update last known pivots (only those confirmed before current bar)
        for sh in swing_highs:
            if sh.index < i and (last_high is None or sh.index > last_high.index):
                if last_high is None or sh.index > last_high.index:
                    last_high = sh
                    high_crossed = False

        for sl in swing_lows:
            if sl.index < i and (last_low is None or sl.index > last_low.index):
                if last_low is None or sl.index > last_low.index:
                    last_low = sl
                    low_crossed = False

        # Bullish break: close crosses above last swing high
        if last_high and not high_crossed and closes[i] > last_high.price:
            if i > 0 and closes[i - 1] <= last_high.price:
                st = StructureType.CHOCH if trend <= 0 else StructureType.BOS
                breaks.append(StructureBreak(
                    bar_index=i,
                    price=last_high.price,
                    direction=Direction.BULL,
                    structure_type=st,
                    swing_level=level,
                ))
                trend = 1
                high_crossed = True

        # Bearish break: close crosses below last swing low
        if last_low and not low_crossed and closes[i] < last_low.price:
            if i > 0 and closes[i - 1] >= last_low.price:
                st = StructureType.CHOCH if trend >= 0 else StructureType.BOS
                breaks.append(StructureBreak(
                    bar_index=i,
                    price=last_low.price,
                    direction=Direction.BEAR,
                    structure_type=st,
                    swing_level=level,
                ))
                trend = -1
                low_crossed = True

    return breaks


# ─────────────────────────────────────────────────────────────────────
#  Fair Value Gaps
# ─────────────────────────────────────────────────────────────────────

def detect_fvg(
    df: pd.DataFrame,
    min_atr_mult: float = 0.25,
    atr_period: int = 200,
) -> List[FairValueGap]:
    """Detect Fair Value Gaps (3-bar imbalance pattern).

    Bullish FVG: low[i] > high[i-2] (gap up between bar i-2 high and bar i low)
    Bearish FVG: high[i] < low[i-2] (gap down)

    Filter: gap must exceed min_atr_mult × ATR to filter noise.
    Mitigation: checked — if subsequent price fills the gap.
    """
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    fvgs: List[FairValueGap] = []

    # Pre-compute ATR for filtering
    atr = _atr_series(df, atr_period)

    for i in range(2, n):
        threshold = atr[i] * min_atr_mult if not np.isnan(atr[i]) else 0.0

        # Bullish FVG: low[i] > high[i-2] AND close[i] > close[i-1] (momentum)
        if lows[i] > highs[i - 2] and closes[i] > closes[i - 1]:
            gap_size = lows[i] - highs[i - 2]
            if gap_size > threshold:
                fvg = FairValueGap(
                    bar_index=i - 1,  # middle candle
                    top=float(lows[i]),
                    bottom=float(highs[i - 2]),
                    is_bull=True,
                )
                # Check mitigation in subsequent bars
                for j in range(i + 1, n):
                    if lows[j] <= fvg.bottom:
                        fvg.mitigated = True
                        fvg.mitigated_at = j
                        break
                fvgs.append(fvg)

        # Bearish FVG: high[i] < low[i-2] AND close[i] < close[i-1]
        if highs[i] < lows[i - 2] and closes[i] < closes[i - 1]:
            gap_size = lows[i - 2] - highs[i]
            if gap_size > threshold:
                fvg = FairValueGap(
                    bar_index=i - 1,
                    top=float(lows[i - 2]),
                    bottom=float(highs[i]),
                    is_bull=False,
                )
                for j in range(i + 1, n):
                    if highs[j] >= fvg.top:
                        fvg.mitigated = True
                        fvg.mitigated_at = j
                        break
                fvgs.append(fvg)

    return fvgs


# ─────────────────────────────────────────────────────────────────────
#  Order Blocks
# ─────────────────────────────────────────────────────────────────────

def detect_order_blocks(
    df: pd.DataFrame,
    swing_length: int = 10,
    max_atr_mult: float = 10.0,
) -> List[OrderBlock]:
    """Detect Order Blocks at swing structure breaks.

    A bullish OB is the last bearish candle before a bullish swing break.
    A bearish OB is the last bullish candle before a bearish swing break.

    Size filter: OB height must be <= max_atr_mult × ATR(10).
    Breaker detection: if price breaks through the OB, it becomes a breaker.
    """
    highs = df["high"].values
    lows = df["low"].values
    opens = df["open"].values
    closes = df["close"].values
    volumes = df["volume"].values
    n = len(df)
    obs: List[OrderBlock] = []

    atr = _atr_series(df, 10)

    # Find swing points for OB construction
    swings = detect_swing_points(df, length=swing_length)
    swing_highs = [sp for sp in swings if sp.is_high]
    swing_lows = [sp for sp in swings if not sp.is_high]

    # Bullish OBs: when price breaks above a swing high,
    # look back for the lowest candle body before the break
    for sh in swing_highs:
        # Find the bar where close crosses above this swing high
        for i in range(sh.index + 1, min(sh.index + 100, n)):
            if closes[i] > sh.price:
                # Look back from the swing to find the bearish candle (OB)
                ob_idx = sh.index
                ob_low = lows[sh.index]
                for j in range(sh.index, max(sh.index - swing_length, 0), -1):
                    if lows[j] < ob_low:
                        ob_low = lows[j]
                        ob_idx = j

                ob_top = max(opens[ob_idx], closes[ob_idx])
                ob_bottom = min(opens[ob_idx], closes[ob_idx])
                if ob_bottom == ob_top:
                    ob_top = highs[ob_idx]
                    ob_bottom = lows[ob_idx]

                ob_size = ob_top - ob_bottom
                max_size = atr[ob_idx] * max_atr_mult if not np.isnan(atr[ob_idx]) else float("inf")

                if ob_size <= max_size and ob_size > 0:
                    ob = OrderBlock(
                        bar_index=ob_idx,
                        top=float(ob_top),
                        bottom=float(ob_bottom),
                        direction=Direction.BULL,
                        volume=float(volumes[ob_idx]) if ob_idx < len(volumes) else 0.0,
                    )
                    # Check if breaker (price breaks below OB bottom)
                    for k in range(i + 1, n):
                        if lows[k] < ob.bottom:
                            ob.breaker = True
                            ob.breaker_at = k
                            break
                    obs.append(ob)
                break

    # Bearish OBs: when price breaks below a swing low
    for sl in swing_lows:
        for i in range(sl.index + 1, min(sl.index + 100, n)):
            if closes[i] < sl.price:
                ob_idx = sl.index
                ob_high = highs[sl.index]
                for j in range(sl.index, max(sl.index - swing_length, 0), -1):
                    if highs[j] > ob_high:
                        ob_high = highs[j]
                        ob_idx = j

                ob_top = max(opens[ob_idx], closes[ob_idx])
                ob_bottom = min(opens[ob_idx], closes[ob_idx])
                if ob_bottom == ob_top:
                    ob_top = highs[ob_idx]
                    ob_bottom = lows[ob_idx]

                ob_size = ob_top - ob_bottom
                max_size = atr[ob_idx] * max_atr_mult if not np.isnan(atr[ob_idx]) else float("inf")

                if ob_size <= max_size and ob_size > 0:
                    ob = OrderBlock(
                        bar_index=ob_idx,
                        top=float(ob_top),
                        bottom=float(ob_bottom),
                        direction=Direction.BEAR,
                        volume=float(volumes[ob_idx]) if ob_idx < len(volumes) else 0.0,
                    )
                    for k in range(i + 1, n):
                        if highs[k] > ob.top:
                            ob.breaker = True
                            ob.breaker_at = k
                            break
                    obs.append(ob)
                break

    return obs


# ─────────────────────────────────────────────────────────────────────
#  Liquidity Sweeps
# ─────────────────────────────────────────────────────────────────────

def detect_liquidity_sweeps(
    df: pd.DataFrame,
    pivot_len: int = 6,
) -> List[LiquiditySweep]:
    """Detect liquidity sweeps: wicks that take out pivot levels then close back inside.

    Bearish sweep: high > pivot_high BUT close < pivot_high (wick above)
    Bullish sweep: low < pivot_low BUT close > pivot_low (wick below)
    """
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    sweeps: List[LiquiditySweep] = []

    # Get pivot levels
    pivots = detect_swing_points(df, length=pivot_len)
    pivot_highs = [p for p in pivots if p.is_high]
    pivot_lows = [p for p in pivots if not p.is_high]

    # Track active (unswept) pivot highs
    for ph in pivot_highs:
        for i in range(ph.index + pivot_len, n):
            if highs[i] > ph.price and closes[i] < ph.price:
                # Bearish sweep: wick took the high, closed below
                sweeps.append(LiquiditySweep(
                    bar_index=i,
                    pivot_price=ph.price,
                    sweep_price=float(highs[i]),
                    direction=Direction.BEAR,
                ))
                break
            elif closes[i] > ph.price:
                # Broken cleanly (not a sweep, real breakout)
                break

    # Track active pivot lows
    for pl in pivot_lows:
        for i in range(pl.index + pivot_len, n):
            if lows[i] < pl.price and closes[i] > pl.price:
                # Bullish sweep: wick took the low, closed above
                sweeps.append(LiquiditySweep(
                    bar_index=i,
                    pivot_price=pl.price,
                    sweep_price=float(lows[i]),
                    direction=Direction.BULL,
                ))
                break
            elif closes[i] < pl.price:
                break

    return sweeps


# ─────────────────────────────────────────────────────────────────────
#  Equal Highs / Lows
# ─────────────────────────────────────────────────────────────────────

def detect_equal_hl(
    df: pd.DataFrame,
    eq_len: int = 3,
    threshold_mult: float = 0.1,
) -> List[dict]:
    """Detect Equal Highs and Equal Lows.

    Two consecutive pivots at approximately the same level (within ATR × threshold).
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    results = []

    atr = _atr_series(df, 200)

    # Pivot detection for EQH/EQL (short length)
    pivots = detect_swing_points(df, length=eq_len)
    pivot_highs = [p for p in pivots if p.is_high]
    pivot_lows = [p for p in pivots if not p.is_high]

    # Threshold scale: smaller eq_len = less strict
    t_scale = 0.1 * (6 - eq_len)
    if eq_len == 5:
        t_scale = 0.05

    # Check consecutive pivot highs
    for i in range(1, len(pivot_highs)):
        prev = pivot_highs[i - 1]
        curr = pivot_highs[i]
        idx = curr.index
        threshold = atr[idx] * t_scale if idx < len(atr) and not np.isnan(atr[idx]) else 0.0
        diff = abs(curr.price - prev.price)
        if diff <= threshold:
            results.append({
                "type": "EQH",
                "bar_index": idx,
                "price": (curr.price + prev.price) / 2,
                "prev_index": prev.index,
            })

    # Check consecutive pivot lows
    for i in range(1, len(pivot_lows)):
        prev = pivot_lows[i - 1]
        curr = pivot_lows[i]
        idx = curr.index
        threshold = atr[idx] * t_scale if idx < len(atr) and not np.isnan(atr[idx]) else 0.0
        diff = abs(curr.price - prev.price)
        if diff <= threshold:
            results.append({
                "type": "EQL",
                "bar_index": idx,
                "price": (curr.price + prev.price) / 2,
                "prev_index": prev.index,
            })

    return results


# ─────────────────────────────────────────────────────────────────────
#  Premium / Discount / Equilibrium
# ─────────────────────────────────────────────────────────────────────

def compute_premium_discount(
    swing_high: float,
    swing_low: float,
    current_close: float,
) -> str:
    """Classify current price within the swing range.

    Premium: price > 61.8% fib (upper zone — overvalued)
    Discount: price < 38.2% fib (lower zone — undervalued)
    Equilibrium: between 38.2% and 61.8%
    """
    if swing_high <= swing_low:
        return "equilibrium"

    rng = swing_high - swing_low
    position = (current_close - swing_low) / rng  # 0.0 = at low, 1.0 = at high

    if position >= 0.618:
        return "premium"
    elif position <= 0.382:
        return "discount"
    else:
        return "equilibrium"


# ─────────────────────────────────────────────────────────────────────
#  Choppiness Index
# ─────────────────────────────────────────────────────────────────────

def choppiness_index(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Compute Choppiness Index.

    CHOP = 100 × log10(sum(ATR(1), length) / (highest(high,length) - lowest(low,length))) / log10(length)

    Values:
    - > 61.8 → choppy/ranging market
    - < 38.2 → trending market
    - Between → neutral
    """
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]

    # True Range (ATR with period 1 = just TR)
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Sum of TR over length
    atr_sum = tr.rolling(window=length).sum()

    # Range over length
    highest = highs.rolling(window=length).max()
    lowest = lows.rolling(window=length).min()
    price_range = highest - lowest

    # Avoid division by zero
    price_range = price_range.replace(0, np.nan)

    chop = 100.0 * np.log10(atr_sum / price_range) / math.log10(length)
    return chop


def chop_regime(chop_value: float, trending_threshold: float = 38.2, choppy_threshold: float = 61.8) -> str:
    """Classify CHOP value into regime."""
    if np.isnan(chop_value):
        return "neutral"
    if chop_value < trending_threshold:
        return "trending"
    elif chop_value > choppy_threshold:
        return "choppy"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────
#  Full Analysis
# ─────────────────────────────────────────────────────────────────────

def analyze_price_action(
    df: pd.DataFrame,
    swing_length: int = 50,
    internal_length: int = 5,
    ob_swing_length: int = 10,
    sweep_pivot_len: int = 6,
    chop_length: int = 14,
) -> PriceActionContext:
    """Run full price action analysis on a DataFrame.

    Returns a PriceActionContext with all detected structures.
    """
    if len(df) < swing_length * 2 + 1:
        return PriceActionContext()

    # Swing points & structure
    swing_points = detect_swing_points(df, length=swing_length)
    internal_points = detect_internal_structure(df, length=internal_length)

    swing_breaks = classify_structure(df, swing_points, level="swing")
    internal_breaks = classify_structure(df, internal_points, level="internal")
    all_breaks = swing_breaks + internal_breaks

    # Structure trend: count net BOS direction from swing breaks
    structure_trend = 0
    last_bos_type = None
    last_bos_dir = None
    for sb in swing_breaks:
        if sb.direction == Direction.BULL:
            if structure_trend <= 0 and sb.structure_type == StructureType.CHOCH:
                structure_trend = 1
            elif structure_trend > 0:
                structure_trend += 1
        else:
            if structure_trend >= 0 and sb.structure_type == StructureType.CHOCH:
                structure_trend = -1
            elif structure_trend < 0:
                structure_trend -= 1
    if swing_breaks:
        last_bos_type = swing_breaks[-1].structure_type.value
        last_bos_dir = swing_breaks[-1].direction.value

    # FVG
    fvg_zones = detect_fvg(df)

    # Order Blocks
    order_blocks = detect_order_blocks(df, swing_length=ob_swing_length)

    # Liquidity Sweeps
    sweeps = detect_liquidity_sweeps(df, pivot_len=sweep_pivot_len)

    # CHOP
    chop_series = choppiness_index(df, length=chop_length)
    last_chop = float(chop_series.iloc[-1]) if len(chop_series) > 0 and not np.isnan(chop_series.iloc[-1]) else 50.0
    regime = chop_regime(last_chop)

    # Premium/Discount from recent swing range
    recent_highs = [sp for sp in swing_points if sp.is_high]
    recent_lows = [sp for sp in swing_points if not sp.is_high]
    if recent_highs and recent_lows:
        sh = max(sp.price for sp in recent_highs[-5:])  # last 5 swing highs
        sl = min(sp.price for sp in recent_lows[-5:])   # last 5 swing lows
        zone = compute_premium_discount(sh, sl, float(df["close"].iloc[-1]))
    else:
        zone = "equilibrium"

    return PriceActionContext(
        swing_points=swing_points,
        structure_breaks=all_breaks,
        fvg_zones=fvg_zones,
        order_blocks=order_blocks,
        liquidity_sweeps=sweeps,
        structure_trend=structure_trend,
        last_bos_type=last_bos_type,
        last_bos_direction=last_bos_dir,
        chop_value=last_chop,
        chop_regime=regime,
        price_zone=zone,
    )


# ─────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _atr_series(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    """Compute ATR as numpy array (for internal use)."""
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)

    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder's smoothing (EMA with alpha = 1/period)
    atr = np.empty(n)
    atr[:period] = np.nan
    atr[period - 1] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha

    return atr
