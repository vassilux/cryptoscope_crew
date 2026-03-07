# src/cryptoscope_crew/domain/macro_regime.py
"""BtcMacroRegimeDetector — BTC-led macro regime using EMA50/EMA200 on 1D.

Macro regime uses EMA50/EMA200 cross + close position on 1D:
  - close < EMA200  AND  EMA50 < EMA200  →  BEAR
  - close > EMA200  AND  EMA50 > EMA200  →  BULL
  - otherwise                            →  TRANSITION

BTC-led hierarchy:
  - BTC is the primary regime reference.
  - ETH: own regime is authoritative, but downgraded from BULL → TRANSITION
    when BTC is BEAR (macro caution).
  - XRP (and any non-BTC/ETH pair): forced BEAR when BTC is BEAR,
    capped to TRANSITION when BTC is TRANSITION.  Only gets BULL when
    BTC is BULL.

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

class MacroRegime(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    TRANSITION = "TRANSITION"


# Pair-role tiers for BTC-led hierarchy
_PRIMARY = "primary"              # BTC — no clamping
_SECONDARY = "secondary"          # ETH — mild clamping
_OPPORTUNISTIC = "opportunistic"  # XRP + others — strict clamping


def _pair_role(pair: str) -> str:
    """Return the hierarchy role for a pair."""
    ticker = pair.split("/")[0].upper()
    if ticker == "BTC":
        return _PRIMARY
    if ticker == "ETH":
        return _SECONDARY
    return _OPPORTUNISTIC


class MacroRegimeResult(BaseModel):
    """BTC-led macro regime for a single pair."""

    pair: str
    macro: MacroRegime
    raw_macro: MacroRegime = MacroRegime.TRANSITION  # before BTC-led clamping
    close: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    btc_macro: Optional[MacroRegime] = None          # BTC reference for traceability
    role: str = ""                                    # primary / secondary / opportunistic
    rationale: str = ""


# ------------------------------------------------------------------ #
#  Detector
# ------------------------------------------------------------------ #

class BtcMacroRegimeDetector:
    """Classifies macro regime per pair using EMA50/EMA200 on 1D.

    Macro rules (EMA50/EMA200 on 1D):
      - close < EMA200  AND  EMA50 < EMA200  →  BEAR
      - close > EMA200  AND  EMA50 > EMA200  →  BULL
      - otherwise                            →  TRANSITION
    """

    @staticmethod
    def detect(
        pair: str,
        context_by_tf: Dict[str, dict],
        tf: str = "1d",
    ) -> MacroRegimeResult:
        """Detect raw macro regime for *pair* using data from *tf*.

        This is the **unclamped** macro — BTC-led hierarchy is applied
        separately via ``detect_all()``.
        """
        ctx = context_by_tf.get(tf, {})
        entry = _get_entry(ctx, pair)

        if entry is None:
            return MacroRegimeResult(
                pair=pair,
                macro=MacroRegime.TRANSITION,
                raw_macro=MacroRegime.TRANSITION,
                role=_pair_role(pair),
                rationale=f"No {tf} data available for {pair}; defaulting to TRANSITION.",
            )

        close = entry["close"]
        ema50 = entry["ema_slow"]
        ema200 = entry.get("ema200", ema50)  # graceful fallback

        if close < ema200 and ema50 < ema200:
            macro = MacroRegime.BEAR
            rationale = (
                f"Close ({close:.4f}) < EMA200 ({ema200:.4f}) "
                f"and EMA50 ({ema50:.4f}) < EMA200 → confirmed BEAR macro."
            )
        elif close > ema200 and ema50 > ema200:
            macro = MacroRegime.BULL
            rationale = (
                f"Close ({close:.4f}) > EMA200 ({ema200:.4f}) "
                f"and EMA50 ({ema50:.4f}) > EMA200 → confirmed BULL macro."
            )
        else:
            macro = MacroRegime.TRANSITION
            rationale = (
                f"Mixed signals: Close={close:.4f}, EMA50={ema50:.4f}, "
                f"EMA200={ema200:.4f}. Macro is in TRANSITION."
            )

        return MacroRegimeResult(
            pair=pair,
            macro=macro,
            raw_macro=macro,
            close=close,
            ema50=ema50,
            ema200=ema200,
            role=_pair_role(pair),
            rationale=rationale,
        )

    # ------------------------------------------------------------------ #
    #  BTC-led clamping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clamp(
        result: MacroRegimeResult,
        btc_macro: MacroRegime,
    ) -> MacroRegimeResult:
        """Apply BTC-led hierarchy clamping to a single MacroRegimeResult.

        Mutates and returns *result*.
        """
        result.btc_macro = btc_macro
        role = result.role or _pair_role(result.pair)
        result.role = role

        if role == _PRIMARY:
            # BTC is never clamped
            return result

        raw = result.raw_macro

        if role == _SECONDARY:
            # ETH: downgrade BULL → TRANSITION when BTC BEAR
            if btc_macro == MacroRegime.BEAR and raw == MacroRegime.BULL:
                result.macro = MacroRegime.TRANSITION
                result.rationale += (
                    " [BTC-led: ETH downgraded BULL→TRANSITION because BTC is BEAR]"
                )
            return result

        # Opportunistic (XRP, etc.)
        if btc_macro == MacroRegime.BEAR:
            if raw != MacroRegime.BEAR:
                result.macro = MacroRegime.BEAR
                result.rationale += (
                    f" [BTC-led: {result.pair} forced BEAR because BTC is BEAR]"
                )
        elif btc_macro == MacroRegime.TRANSITION:
            if raw == MacroRegime.BULL:
                result.macro = MacroRegime.TRANSITION
                result.rationale += (
                    f" [BTC-led: {result.pair} capped BULL→TRANSITION "
                    f"because BTC is TRANSITION]"
                )
        # btc BULL → no clamping for opportunistic
        return result

    # ------------------------------------------------------------------ #
    #  Batch detection with BTC-led hierarchy
    # ------------------------------------------------------------------ #

    @staticmethod
    def detect_all(
        pairs: List[str],
        context_by_tf: Dict[str, dict],
        tf: str = "1d",
    ) -> List[MacroRegimeResult]:
        """Detect macro regime for every pair **with BTC-led hierarchy**.

        1. Detect raw macro for all pairs.
        2. Find BTC macro (fallback TRANSITION if BTC not in pairs).
        3. Clamp non-BTC pairs according to hierarchy rules.
        """
        raw_results = [
            BtcMacroRegimeDetector.detect(p, context_by_tf, tf) for p in pairs
        ]

        # Find BTC macro
        btc_macro = MacroRegime.TRANSITION
        for r in raw_results:
            if _pair_role(r.pair) == _PRIMARY:
                btc_macro = r.macro
                break

        # Apply clamping
        for r in raw_results:
            BtcMacroRegimeDetector._clamp(r, btc_macro)

        return raw_results
