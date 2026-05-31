# src/cryptoscope_crew/ta/confluence_score.py
"""Confluence Scoring Engine — quantifies setup quality (0-100).

Mirrors the Pine Script scoring logic with 7 weighted components:
  HTF alignment:     +20
  Internal struct:   +15
  Swing struct:      +15
  Liquidity sweep:   +15
  Price zone:        +10
  FVG:               +10
  OB proximity:      +15
  CHOP regime:       ±10

Total possible: 100 (theoretical max with CHOP bonus).
Without CHOP bonus: max 100, without CHOP penalty: clamped at 0-100.

A signal triggers when:
  score >= min_score (default 75) AND
  score_lead >= gap_required (default 15) AND
  CHOP allows (not choppy, or filter disabled)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from cryptoscope_crew.ta.price_action import (
    Direction,
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    PriceActionContext,
    StructureBreak,
    StructureType,
)


@dataclass
class ConfluenceResult:
    """Result of confluence scoring for a pair/timeframe."""
    bull_score: int = 0
    bear_score: int = 0
    bull_lead: int = 0       # bull_score - bear_score
    bear_lead: int = 0       # bear_score - bull_score
    bullish_setup: bool = False
    bearish_setup: bool = False
    high_confidence_bull: bool = False
    high_confidence_bear: bool = False
    components: dict = None  # detail of what contributed

    def __post_init__(self):
        if self.components is None:
            self.components = {}


@dataclass
class ScoringConfig:
    """Tunable parameters for the scoring engine."""
    min_score: int = 75
    score_gap_required: int = 15
    high_confidence_score: int = 85
    lookback_bars: int = 10
    use_chop_filter: bool = True
    block_choppy_signals: bool = True

    # Weight overrides (default = Pine values)
    w_htf: int = 20
    w_internal: int = 15
    w_swing: int = 15
    w_sweep: int = 15
    w_zone: int = 10
    w_fvg: int = 10
    w_ob: int = 15
    w_chop: int = 10  # bonus/penalty


def compute_confluence_score(
    pa_context: PriceActionContext,
    current_bar: int,
    current_close: float,
    current_low: float,
    current_high: float,
    atr: float,
    htf_structure_trend: Optional[int] = None,
    config: Optional[ScoringConfig] = None,
) -> ConfluenceResult:
    """Compute bull/bear confluence scores for the current bar.

    Args:
        pa_context: PriceActionContext from analyze_price_action()
        current_bar: index of the current bar in the DataFrame
        current_close: current close price
        current_low: current low price
        current_high: current high price
        atr: current ATR value (for OB proximity check)
        htf_structure_trend: structure trend from higher timeframe (>0 bull, <0 bear)
        config: scoring parameters

    Returns:
        ConfluenceResult with scores and setup flags.
    """
    if config is None:
        config = ScoringConfig()

    bull_score = 0
    bear_score = 0
    components = {}

    lookback = config.lookback_bars

    # ── 1. HTF Alignment (+w_htf) ──────────────────────────────────
    bull_htf = htf_structure_trend is not None and htf_structure_trend > 0
    bear_htf = htf_structure_trend is not None and htf_structure_trend < 0
    if bull_htf:
        bull_score += config.w_htf
    if bear_htf:
        bear_score += config.w_htf
    components["htf"] = {"bull": bull_htf, "bear": bear_htf}

    # ── 2. Internal Structure Break (recent, +w_internal) ──────────
    bull_internal = False
    bear_internal = False
    for sb in pa_context.structure_breaks:
        if sb.swing_level == "internal" and (current_bar - sb.bar_index) <= lookback:
            if sb.direction == Direction.BULL:
                bull_internal = True
            else:
                bear_internal = True
    if bull_internal:
        bull_score += config.w_internal
    if bear_internal:
        bear_score += config.w_internal
    components["internal"] = {"bull": bull_internal, "bear": bear_internal}

    # ── 3. Swing Structure Break (recent, +w_swing) ────────────────
    bull_swing = False
    bear_swing = False
    for sb in pa_context.structure_breaks:
        if sb.swing_level == "swing" and (current_bar - sb.bar_index) <= lookback:
            if sb.direction == Direction.BULL:
                bull_swing = True
            else:
                bear_swing = True
    if bull_swing:
        bull_score += config.w_swing
    if bear_swing:
        bear_score += config.w_swing
    components["swing"] = {"bull": bull_swing, "bear": bear_swing}

    # ── 4. Liquidity Sweep (recent, +w_sweep) ──────────────────────
    bull_sweep = False
    bear_sweep = False
    for sw in pa_context.liquidity_sweeps:
        if (current_bar - sw.bar_index) <= lookback:
            if sw.direction == Direction.BULL:
                bull_sweep = True
            else:
                bear_sweep = True
    if bull_sweep:
        bull_score += config.w_sweep
    if bear_sweep:
        bear_score += config.w_sweep
    components["sweep"] = {"bull": bull_sweep, "bear": bear_sweep}

    # ── 5. Price Zone (+w_zone) ────────────────────────────────────
    bull_zone = pa_context.price_zone == "discount"
    bear_zone = pa_context.price_zone == "premium"
    if bull_zone:
        bull_score += config.w_zone
    if bear_zone:
        bear_score += config.w_zone
    components["zone"] = {"bull": bull_zone, "bear": bear_zone, "value": pa_context.price_zone}

    # ── 6. FVG (recent unmitigated, +w_fvg) ───────────────────────
    bull_fvg = False
    bear_fvg = False
    for fvg in pa_context.fvg_zones:
        if not fvg.mitigated and (current_bar - fvg.bar_index) <= lookback:
            if fvg.is_bull:
                bull_fvg = True
            else:
                bear_fvg = True
    if bull_fvg:
        bull_score += config.w_fvg
    if bear_fvg:
        bear_score += config.w_fvg
    components["fvg"] = {"bull": bull_fvg, "bear": bear_fvg}

    # ── 7. OB Proximity (+w_ob) ────────────────────────────────────
    ob_proximity = atr * 0.5
    bull_ob = False
    bear_ob = False
    for ob in pa_context.order_blocks:
        if ob.breaker:
            continue
        if ob.direction == Direction.BULL:
            # Price near bullish OB (demand zone)
            if current_low <= ob.top + ob_proximity and current_low >= ob.bottom - ob_proximity:
                bull_ob = True
        else:
            # Price near bearish OB (supply zone)
            if current_high >= ob.bottom - ob_proximity and current_high <= ob.top + ob_proximity:
                bear_ob = True
    if bull_ob:
        bull_score += config.w_ob
    if bear_ob:
        bear_score += config.w_ob
    components["ob"] = {"bull": bull_ob, "bear": bear_ob}

    # ── 8. CHOP Regime (±w_chop) ───────────────────────────────────
    if config.use_chop_filter:
        if pa_context.chop_regime == "trending":
            bull_score += config.w_chop
            bear_score += config.w_chop
        elif pa_context.chop_regime == "choppy":
            bull_score -= config.w_chop
            bear_score -= config.w_chop
    components["chop"] = {"regime": pa_context.chop_regime, "value": pa_context.chop_value}

    # ── Clamp 0-100 ───────────────────────────────────────────────
    bull_score = max(0, min(100, bull_score))
    bear_score = max(0, min(100, bear_score))

    bull_lead = bull_score - bear_score
    bear_lead = bear_score - bull_score

    # ── Setup triggers ─────────────────────────────────────────────
    chop_allows = (
        not config.use_chop_filter
        or not config.block_choppy_signals
        or pa_context.chop_regime != "choppy"
    )

    bullish_setup = (
        bull_score >= config.min_score
        and bull_lead >= config.score_gap_required
        and chop_allows
    )
    bearish_setup = (
        bear_score >= config.min_score
        and bear_lead >= config.score_gap_required
        and chop_allows
    )

    return ConfluenceResult(
        bull_score=bull_score,
        bear_score=bear_score,
        bull_lead=bull_lead,
        bear_lead=bear_lead,
        bullish_setup=bullish_setup,
        bearish_setup=bearish_setup,
        high_confidence_bull=bullish_setup and bull_score >= config.high_confidence_score,
        high_confidence_bear=bearish_setup and bear_score >= config.high_confidence_score,
        components=components,
    )
