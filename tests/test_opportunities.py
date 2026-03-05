"""Tests unitaires — Top Opportunities V1."""
import os
import json
import pytest

from cryptoscope_crew.domain.portfolio import Portfolio, Position, load_portfolio
from cryptoscope_crew.domain.decision_engine import (
    Action,
    DecisionResult,
    decide_all,
)
from cryptoscope_crew.domain.opportunities import (
    Opportunity,
    OpportunityEngine,
    _distance_to_ema20_4h_pct,
    _score,
    opportunities_to_markdown,
)


# ================================================================== #
#  Fixtures — contexte multi-TF réutilisable
# ================================================================== #

def _make_ctx(
    *,
    close_4h: float = 70000,
    ema20_4h: float = 69000,
    ema50_4h: float = 67000,
    rsi_4h: float = 60,
    atr_4h: float = 800,
    bias_4h: str = "bull",
    rsi_1h: float = 72,
    bias_1h: str = "bull",
) -> dict:
    """Construit un context_by_tf minimaliste pour BTC/USDC (3 TF)."""
    return {
        "1d": {"pairs": [
            {"pair": "BTC/USDC", "close": 70000,
             "ema_fast": 69000, "ema_slow": 72000,
             "rsi14": 40, "atr14": 2000, "bias": "bear"},
        ]},
        "4h": {"pairs": [
            {"pair": "BTC/USDC", "close": close_4h,
             "ema_fast": ema20_4h, "ema_slow": ema50_4h,
             "rsi14": rsi_4h, "atr14": atr_4h, "bias": bias_4h},
        ]},
        "1h": {"pairs": [
            {"pair": "BTC/USDC", "close": 70000,
             "ema_fast": 69800, "ema_slow": 69500,
             "rsi14": rsi_1h, "atr14": 300, "bias": bias_1h},
        ]},
    }


@pytest.fixture()
def portfolio():
    os.environ["PORTFOLIO_JSON"] = json.dumps({
        "cash_usdc": 5000,
        "positions": [
            {"pair": "BTC/USDC", "quantity": 0.1, "avg_price": 62000},
        ],
    })
    p = load_portfolio()
    p.enrich_all({"BTC/USDC": 70000})
    yield p
    os.environ.pop("PORTFOLIO_JSON", None)


# ================================================================== #
#  Test 1 — score monotonic : RSI 1H haut ⇒ score plus haut
# ================================================================== #

class TestScoring:
    def test_score_monotonic_rsi_1h(self):
        """Un RSI 1H > 70 doit produire un score strictement supérieur
        à un RSI 1H ≤ 70, toutes choses égales par ailleurs."""
        common = dict(
            bias_4h_bull=True,
            align_2of3=True,
            distance_ema20_4h_pct=1.5,
            atr_pct=1.0,
            cash_pct=50.0,
            exposure_pct=50.0,
        )
        score_high = _score(rsi_1h=75, **common)
        score_low  = _score(rsi_1h=65, **common)
        assert score_high > score_low, (
            f"RSI 75 score ({score_high}) doit être > RSI 65 score ({score_low})"
        )
        # La différence doit être exactement 25 pts (le bonus RSI>70)
        assert score_high - score_low == 25.0

    def test_score_bounded_0_100(self):
        """Le score doit rester dans [0, 100] même avec des valeurs extrêmes."""
        # Score très haut
        s_max = _score(
            rsi_1h=90, bias_4h_bull=True, align_2of3=True,
            distance_ema20_4h_pct=0, atr_pct=0,
            cash_pct=100, exposure_pct=0,
        )
        assert 0 <= s_max <= 100

        # Score très bas (grosse volatilité, pas d'edge)
        s_min = _score(
            rsi_1h=30, bias_4h_bull=False, align_2of3=False,
            distance_ema20_4h_pct=10, atr_pct=5,
            cash_pct=0, exposure_pct=100,
        )
        assert 0 <= s_min <= 100


# ================================================================== #
#  Test 2 — distance_to_ema20_4h_pct calcul correct
# ================================================================== #

class TestDistanceCalc:
    def test_distance_positive_when_above(self):
        """close > EMA20 → distance positive."""
        ctx_4h = {"pairs": [
            {"pair": "BTC/USDC", "close": 70000,
             "ema_fast": 68000, "ema_slow": 66000,
             "rsi14": 55, "atr14": 500, "bias": "bull"},
        ]}
        dist = _distance_to_ema20_4h_pct(ctx_4h, "BTC/USDC")
        expected = (70000 - 68000) / 68000 * 100  # ≈ 2.941%
        assert dist == pytest.approx(expected, rel=1e-6)
        assert dist > 0

    def test_distance_negative_when_below(self):
        """close < EMA20 → distance négative."""
        ctx_4h = {"pairs": [
            {"pair": "BTC/USDC", "close": 67000,
             "ema_fast": 68000, "ema_slow": 66000,
             "rsi14": 45, "atr14": 500, "bias": "bear"},
        ]}
        dist = _distance_to_ema20_4h_pct(ctx_4h, "BTC/USDC")
        expected = (67000 - 68000) / 68000 * 100  # ≈ -1.471%
        assert dist == pytest.approx(expected, rel=1e-6)
        assert dist < 0

    def test_distance_zero_when_pair_missing(self):
        """Pair manquante → distance = 0."""
        ctx_4h = {"pairs": []}
        assert _distance_to_ema20_4h_pct(ctx_4h, "BTC/USDC") == 0.0


# ================================================================== #
#  Top3 integration
# ================================================================== #

class TestBuildTop3:
    def test_sell_strength_from_reduce_swing(self, portfolio):
        """REDUCE_SWING → SELL_STRENGTH opportunity."""
        ctx = _make_ctx(rsi_1h=75)
        decisions = decide_all(["BTC/USDC"], ctx, portfolio)
        assert decisions[0].suggested_action == Action.REDUCE_SWING

        opps = OpportunityEngine.build_top3(ctx, portfolio, decisions)
        assert len(opps) >= 1
        assert opps[0].kind == "SELL_STRENGTH"
        assert opps[0].score > 0

    def test_buy_pullback_near_ema20(self, portfolio):
        """Close ≤1% above EMA20 4H + bias Bull + RSI 4H [50-55] → BUY_PULLBACK."""
        ctx = _make_ctx(
            close_4h=69500,   # 0.72% above ema20_4h (69000)
            ema20_4h=69000,
            rsi_4h=52,
            bias_4h="bull",
            rsi_1h=55,        # pas de surchauffe → pas R1
            bias_1h="bull",
        )
        decisions = decide_all(["BTC/USDC"], ctx, portfolio)
        # 1D Bear + 4H bull + RSI 1H 55 (<70) → pas R1, et pas R2 (4H bull) → WAIT
        assert decisions[0].suggested_action == Action.WAIT

        opps = OpportunityEngine.build_top3(ctx, portfolio, decisions)
        assert len(opps) >= 1
        assert opps[0].kind == "BUY_PULLBACK"

    def test_max_3_returned(self, portfolio):
        """Au maximum 3 opportunités même avec plus de paires."""
        ctx = {
            "1d": {"pairs": [
                {"pair": f"T{i}/USDC", "close": 100, "ema_fast": 99, "ema_slow": 101, "rsi14": 40, "atr14": 5, "bias": "bear"}
                for i in range(5)
            ]},
            "4h": {"pairs": [
                {"pair": f"T{i}/USDC", "close": 100, "ema_fast": 99, "ema_slow": 98, "rsi14": 60, "atr14": 3, "bias": "bull"}
                for i in range(5)
            ]},
            "1h": {"pairs": [
                {"pair": f"T{i}/USDC", "close": 100, "ema_fast": 100.5, "ema_slow": 99.5, "rsi14": 75, "atr14": 1, "bias": "bull"}
                for i in range(5)
            ]},
        }
        decisions = decide_all([f"T{i}/USDC" for i in range(5)], ctx, portfolio)
        opps = OpportunityEngine.build_top3(ctx, portfolio, decisions)
        assert len(opps) <= 3

    def test_markdown_output(self, portfolio):
        """Le markdown contient le header et les champs attendus."""
        ctx = _make_ctx(rsi_1h=75)
        decisions = decide_all(["BTC/USDC"], ctx, portfolio)
        opps = OpportunityEngine.build_top3(ctx, portfolio, decisions)
        md = opportunities_to_markdown(opps)
        assert md.startswith("## Top Opportunities (V1)")
        assert "SELL_STRENGTH" in md
        assert "Score:" in md
        assert "Action:" in md

    def test_empty_when_no_opportunity(self):
        """Pas d'opportunité si tout est HOLD_OR_ADD (ne matche aucun kind)."""
        ctx = {
            "1d": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 55, "atr14": 3, "bias": "bull"}]},
            "4h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 55, "atr14": 3, "bias": "bull"}]},
            "1h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 55, "atr14": 3, "bias": "bull"}]},
        }
        decisions = decide_all(["SOL/USDC"], ctx)
        opps = OpportunityEngine.build_top3(ctx, None, decisions)
        # HOLD_OR_ADD n'est pas mappé → aucune opportunité
        assert len(opps) == 0
        md = opportunities_to_markdown(opps)
        assert "Aucune opportunité" in md
