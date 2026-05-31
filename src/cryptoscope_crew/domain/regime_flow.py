# src/cryptoscope_crew/domain/regime_flow.py
"""Regime + Flow Engine — enhanced regime detection with CHOP, OI, and Funding.

This is the core edge: the "AND gate" that determines WHEN to trade.

Entry conditions (all must be true):
  Bullish:
    - EMA20 > EMA50 > EMA200  (triple alignment)
    - CHOP(14, 4H) < 38.2     (trending)
    - OI 24h change > +3%     (conviction)
    - [bonus] Funding < 0.01% (not crowded)

  Bearish:
    - EMA20 < EMA50 < EMA200
    - CHOP(14, 4H) < 38.2
    - OI 24h change > +3%
    - [bonus] Funding > -0.01%

Exit conditions (ANY one triggers):
    - CHOP > 50          → exit partial
    - OI drops > 5% 24h  → exit full
    - EMA20 crosses EMA50 against → tighten trailing

Pure deterministic logic, no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class FlowRegime(str, Enum):
    """Overall flow regime classification."""
    STRONG_BULL = "STRONG_BULL"     # All 4 conditions met + funding bonus
    BULL = "BULL"                   # Core 3 conditions met (EMA + CHOP + OI)
    WEAK_BULL = "WEAK_BULL"        # EMA aligned but CHOP or OI missing
    NEUTRAL = "NEUTRAL"            # Mixed / no clear setup
    WEAK_BEAR = "WEAK_BEAR"        # EMA bearish but CHOP or OI missing
    BEAR = "BEAR"                  # Core 3 bearish conditions met
    STRONG_BEAR = "STRONG_BEAR"    # All 4 bearish + funding bonus


class ExitSignal(str, Enum):
    """Exit condition type."""
    NONE = "NONE"
    CHOP_EXIT = "CHOP_EXIT"        # CHOP > 50 → partial exit
    OI_DUMP = "OI_DUMP"            # OI dropped > 5% → full exit
    EMA_CROSS = "EMA_CROSS"        # EMA20 crossed against → tighten stop
    FULL_REVERSAL = "FULL_REVERSAL"  # All conditions flipped


@dataclass
class FlowRegimeResult:
    """Result of the Regime + Flow analysis."""
    pair: str
    regime: FlowRegime
    direction: str = "neutral"   # "bull" / "bear" / "neutral"

    # Component states
    ema_aligned: bool = False     # EMA20>50>200 (or reverse for bear)
    ema_direction: str = "neutral"  # "bull" / "bear" / "neutral"
    chop_trending: bool = False   # CHOP < 38.2
    chop_value: float = 50.0
    oi_rising: bool = False       # OI 24h > +3%
    oi_change_pct: float = 0.0
    funding_favorable: bool = False  # Not crowded
    funding_rate: float = 0.0

    # Confidence & sizing
    conviction_score: int = 0     # 0-4 (how many conditions are met)
    suggested_size_pct: float = 0.0  # Suggested position size (% of capital)

    # Exit signals
    exit_signal: ExitSignal = ExitSignal.NONE
    exit_reason: str = ""

    rationale: str = ""


@dataclass
class FlowConfig:
    """Tunable parameters for the Regime + Flow system."""
    # CHOP
    chop_trending_threshold: float = 38.2
    chop_exit_threshold: float = 50.0
    chop_choppy_threshold: float = 61.8

    # OI
    oi_rising_threshold_pct: float = 3.0    # OI must rise > 3% in 24h
    oi_dump_threshold_pct: float = -5.0     # OI drops > 5% → exit

    # Funding
    funding_crowded_threshold: float = 0.01  # > 0.01% = crowded long
    funding_extreme_threshold: float = 0.03  # > 0.03% = very crowded

    # Position sizing (% of capital)
    size_strong: float = 5.0   # All 4 conditions
    size_normal: float = 3.0   # Core 3 conditions
    size_weak: float = 1.0     # Partial alignment
    size_none: float = 0.0     # No trade


def analyze_regime_flow(
    pair: str,
    ema20: float,
    ema50: float,
    ema200: float,
    close: float,
    chop_value: float,
    oi_change_pct: float,
    funding_rate: Optional[float] = None,
    config: Optional[FlowConfig] = None,
) -> FlowRegimeResult:
    """Analyze the Regime + Flow conditions for a pair.

    Args:
        pair: Trading pair (e.g., "BTC/USDC")
        ema20: Current EMA20 value
        ema50: Current EMA50 value
        ema200: Current EMA200 value
        close: Current close price
        chop_value: Current CHOP index value
        oi_change_pct: OI change over 24h in percent (+3.5 = up 3.5%)
        funding_rate: Current 8h funding rate (0.0001 = 0.01%)
        config: Tunable parameters

    Returns:
        FlowRegimeResult with regime classification and sizing.
    """
    if config is None:
        config = FlowConfig()

    # ── 1. EMA Triple Alignment ────────────────────────────────────
    bull_ema = ema20 > ema50 > ema200
    bear_ema = ema20 < ema50 < ema200
    ema_direction = "bull" if bull_ema else "bear" if bear_ema else "neutral"

    # ── 2. CHOP Trending ───────────────────────────────────────────
    chop_trending = chop_value < config.chop_trending_threshold
    chop_exit = chop_value > config.chop_exit_threshold

    # ── 3. OI Rising ──────────────────────────────────────────────
    oi_rising = oi_change_pct > config.oi_rising_threshold_pct
    oi_dumping = oi_change_pct < config.oi_dump_threshold_pct

    # ── 4. Funding Not Crowded ─────────────────────────────────────
    funding_rate_val = funding_rate if funding_rate is not None else 0.0
    if bull_ema:
        # For longs: funding should be low/negative (not crowded long)
        funding_favorable = funding_rate_val < config.funding_crowded_threshold
    elif bear_ema:
        # For shorts/reduce: funding should be high (crowded long = good to fade)
        funding_favorable = funding_rate_val > -config.funding_crowded_threshold
    else:
        funding_favorable = False

    # ── Conviction count ───────────────────────────────────────────
    bull_conditions = [bull_ema, chop_trending, oi_rising, funding_favorable]
    bear_conditions = [bear_ema, chop_trending, oi_rising, funding_favorable]

    bull_conviction = sum(bull_conditions)
    bear_conviction = sum(bear_conditions)

    # ── Regime Classification ──────────────────────────────────────
    if bull_conviction == 4:
        regime = FlowRegime.STRONG_BULL
        direction = "bull"
        size = config.size_strong
    elif bull_conviction == 3 and bull_ema and chop_trending and oi_rising:
        regime = FlowRegime.BULL
        direction = "bull"
        size = config.size_normal
    elif bull_ema and (chop_trending or oi_rising):
        regime = FlowRegime.WEAK_BULL
        direction = "bull"
        size = config.size_weak
    elif bear_conviction == 4:
        regime = FlowRegime.STRONG_BEAR
        direction = "bear"
        size = config.size_strong
    elif bear_conviction == 3 and bear_ema and chop_trending and oi_rising:
        regime = FlowRegime.BEAR
        direction = "bear"
        size = config.size_normal
    elif bear_ema and (chop_trending or oi_rising):
        regime = FlowRegime.WEAK_BEAR
        direction = "bear"
        size = config.size_weak
    else:
        regime = FlowRegime.NEUTRAL
        direction = "neutral"
        size = config.size_none

    # ── Exit Signals ───────────────────────────────────────────────
    exit_signal = ExitSignal.NONE
    exit_reason = ""

    if oi_dumping:
        exit_signal = ExitSignal.OI_DUMP
        exit_reason = f"OI dropped {oi_change_pct:.1f}% in 24h — full exit."
    elif chop_exit and direction != "neutral":
        exit_signal = ExitSignal.CHOP_EXIT
        exit_reason = f"CHOP={chop_value:.1f} > {config.chop_exit_threshold} — partial exit, market losing direction."

    # EMA cross detection (simplified: just check if EMA20 crossed EMA50)
    # This would need previous values for real cross detection, so we flag proximity
    ema_proximity = abs(ema20 - ema50) / max(ema50, 1e-9)
    if direction == "bull" and ema_proximity < 0.002:
        exit_signal = ExitSignal.EMA_CROSS
        exit_reason = "EMA20 converging on EMA50 — tighten trailing stop."
    elif direction == "bear" and ema_proximity < 0.002:
        exit_signal = ExitSignal.EMA_CROSS
        exit_reason = "EMA20 converging on EMA50 — tighten trailing stop."

    # ── Build rationale ────────────────────────────────────────────
    conditions_str = []
    if bull_ema:
        conditions_str.append("EMA20>50>200 ✓")
    elif bear_ema:
        conditions_str.append("EMA20<50<200 ✓")
    else:
        conditions_str.append("EMA mixed ✗")

    conditions_str.append(f"CHOP={chop_value:.1f} {'✓ trending' if chop_trending else '✗ not trending'}")
    conditions_str.append(f"OI Δ24h={oi_change_pct:+.1f}% {'✓' if oi_rising else '✗'}")
    if funding_rate is not None:
        conditions_str.append(f"Funding={funding_rate_val*100:.4f}% {'✓ ok' if funding_favorable else '✗ crowded'}")

    conviction = max(bull_conviction, bear_conviction)
    rationale = f"{regime.value} | {conviction}/4 conditions | " + " | ".join(conditions_str)

    return FlowRegimeResult(
        pair=pair,
        regime=regime,
        direction=direction,
        ema_aligned=bull_ema or bear_ema,
        ema_direction=ema_direction,
        chop_trending=chop_trending,
        chop_value=chop_value,
        oi_rising=oi_rising,
        oi_change_pct=oi_change_pct,
        funding_favorable=funding_favorable,
        funding_rate=funding_rate_val,
        conviction_score=conviction,
        suggested_size_pct=size,
        exit_signal=exit_signal,
        exit_reason=exit_reason,
        rationale=rationale,
    )
