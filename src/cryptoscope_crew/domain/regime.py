# src/cryptoscope_crew/domain/regime.py
"""MarketRegimeDetector — local per-pair regime using EMA20/EMA50.

Local regime uses EMA20/EMA50 cross + close position:
  - close > EMA50  AND  EMA20 > EMA50  →  BULL
  - close < EMA50  AND  EMA20 < EMA50  →  BEAR
  - otherwise                          →  RANGE

This is the per-pair, per-timeframe trend direction.
For the BTC-led macro regime (EMA50/EMA200), see macro_regime.py.

Pure deterministic logic, no LLM.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel

from cryptoscope_crew.domain.decision_engine import _get_entry


# ------------------------------------------------------------------ #
#  Types
# ------------------------------------------------------------------ #

class MarketRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    RANGE = "RANGE"


class RegimeResult(BaseModel):
    """Detected local regime for a single pair."""

    pair: str
    regime: MarketRegime
    close: float = 0.0
    ema_fast: float = 0.0   # EMA20
    ema_slow: float = 0.0   # EMA50
    rationale: str = ""


# ------------------------------------------------------------------ #
#  Detector
# ------------------------------------------------------------------ #

class MarketRegimeDetector:
    """Classifies local market regime per pair.

    Local rules (EMA20/EMA50):
      - close > EMA50  AND  EMA20 > EMA50  →  BULL
      - close < EMA50  AND  EMA20 < EMA50  →  BEAR
      - otherwise                          →  RANGE
    """

    @staticmethod
    def detect(
        pair: str,
        context_by_tf: Dict[str, dict],
        tf: str = "1d",
    ) -> RegimeResult:
        """Detect local regime for *pair* using data from *tf* (default 1D)."""
        ctx = context_by_tf.get(tf, {})
        entry = _get_entry(ctx, pair)

        if entry is None:
            return RegimeResult(
                pair=pair,
                regime=MarketRegime.RANGE,
                rationale=f"No {tf} data available for {pair}; defaulting to RANGE.",
            )

        close = entry["close"]
        ema_fast = entry["ema_fast"]   # EMA20
        ema_slow = entry["ema_slow"]   # EMA50

        if close > ema_slow and ema_fast > ema_slow:
            regime = MarketRegime.BULL
            rationale = (
                f"Close ({close:.4f}) > EMA50 ({ema_slow:.4f}) "
                f"and EMA20 ({ema_fast:.4f}) > EMA50 → BULL."
            )
        elif close < ema_slow and ema_fast < ema_slow:
            regime = MarketRegime.BEAR
            rationale = (
                f"Close ({close:.4f}) < EMA50 ({ema_slow:.4f}) "
                f"and EMA20 ({ema_fast:.4f}) < EMA50 → BEAR."
            )
        else:
            regime = MarketRegime.RANGE
            rationale = (
                f"Mixed signals: Close={close:.4f}, EMA20={ema_fast:.4f}, "
                f"EMA50={ema_slow:.4f} → RANGE."
            )

        return RegimeResult(
            pair=pair,
            regime=regime,
            close=close,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rationale=rationale,
        )

    # ------------------------------------------------------------------ #
    #  Batch detection (no hierarchy — that's in macro_regime.py)
    # ------------------------------------------------------------------ #

    @staticmethod
    def detect_all(
        pairs: List[str],
        context_by_tf: Dict[str, dict],
        tf: str = "1d",
    ) -> List[RegimeResult]:
        """Detect local regime for every pair (simple batch, no clamping)."""
        return [MarketRegimeDetector.detect(p, context_by_tf, tf) for p in pairs]
