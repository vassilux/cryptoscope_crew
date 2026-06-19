"""Tests des corrections issues de la review externe du rapport 12/06/2026 :

1. Condition de réactivation déjà remplie (reactivation_met) + label Recovery
2. Plan RAISE_CASH quand le cash est sous la cible
3. (déduplication = prompt reporting_task, non testable unitairement)
4. Score de proximité de réactivation (DEFENSIVE != 0.0 plat)
5. Validation des sources narrative_scan (URLs valides, dédupliquées)
"""
import json
import os

import pytest

from cryptoscope_crew.domain.decision_engine import (
    Action,
    DecisionResult,
    decide,
    decisions_to_markdown,
)
from cryptoscope_crew.domain.opportunities import (
    OpportunityEngine,
    _reactivation_proximity_score,
)
from cryptoscope_crew.domain.portfolio import load_portfolio
from cryptoscope_crew.domain.portfolio_strategy import (
    PortfolioStrategyEngine,
    portfolio_strategy_to_markdown,
)
from cryptoscope_crew.domain.schemas import Narrative, NarrativeScanOutput
from cryptoscope_crew.reporting.precompute import tech_table_from_context


# ================================================================== #
#  Fixtures
# ================================================================== #

def _ctx_bear_with_reactivation_met():
    """Reproduit le cas du rapport 12/06 : croisement 4H bear mais
    close > EMA50 4H et RSI 4H > 55 (condition de réactivation remplie)."""
    return {
        "1d": {"pairs": [
            {"pair": "BTC/USDC", "close": 63688, "ema_fast": 67139, "ema_slow": 71363,
             "rsi14": 33.4, "atr14": 2396, "bias": "Bear"},
        ]},
        "4h": {"pairs": [
            {"pair": "BTC/USDC", "close": 63688.5, "ema_fast": 62798.36, "ema_slow": 63676.71,
             "rsi14": 56.47, "atr14": 991.7, "bias": "Bear"},
        ]},
        "1h": {"pairs": [
            {"pair": "BTC/USDC", "close": 63688.5, "ema_fast": 63293, "ema_slow": 62897,
             "rsi14": 59.6, "atr14": 422, "bias": "Bull"},
        ]},
    }


def _ctx_bear_not_met():
    """DEFENSIVE classique : close sous EMA50 4H, RSI < 55."""
    return {
        "1d": {"pairs": [
            {"pair": "ETH/USDC", "close": 1674, "ema_fast": 1816, "ema_slow": 1998,
             "rsi14": 31.5, "atr14": 87, "bias": "Bear"},
        ]},
        "4h": {"pairs": [
            {"pair": "ETH/USDC", "close": 1674.91, "ema_fast": 1658.40, "ema_slow": 1695.43,
             "rsi14": 53.15, "atr14": 34, "bias": "Bear"},
        ]},
        "1h": {"pairs": [
            {"pair": "ETH/USDC", "close": 1674.91, "ema_fast": 1666.89, "ema_slow": 1658.93,
             "rsi14": 55.9, "atr14": 14, "bias": "Bull"},
        ]},
    }


@pytest.fixture()
def low_cash_portfolio():
    os.environ["PORTFOLIO_JSON"] = json.dumps({
        "cash_usdc": 50,
        "positions": [
            {"pair": "BTC/USDC", "quantity": 0.02, "avg_price": 95000,
             "core_pct": 70, "swing_pct": 30, "min_core_qty": 0.01},
            {"pair": "ETH/USDC", "quantity": 0.5, "avg_price": 3100,
             "core_pct": 70, "swing_pct": 30, "min_core_qty": 0.3},
        ],
        "risk_limits": {
            "cash_min_pct": 20,
            "max_exposure_pct": {"BTC/USDC": 40, "ETH/USDC": 30},
            "max_single_order_cash_pct": 12,
        },
        "decision_defaults": {
            "reduce_swing_pct_of_swing": 50,
            "add_small_cash_pct": 5,
            "buy_ladder_cash_pct": [6, 9, 12],
        },
    })
    p = load_portfolio()
    p.enrich_all({"BTC/USDC": 90000, "ETH/USDC": 3000})
    yield p
    os.environ.pop("PORTFOLIO_JSON", None)


# BTC nettement plus faible (-5.3% vs EMA50 4H) qu'ETH (-1.0%)
CTX_RAISE_CASH = {
    "1d": {"pairs": [
        {"pair": "BTC/USDC", "close": 90000, "ema_fast": 93000, "ema_slow": 96000,
         "rsi14": 35, "atr14": 2000, "bias": "Bear"},
        {"pair": "ETH/USDC", "close": 3000, "ema_fast": 3100, "ema_slow": 3200,
         "rsi14": 38, "atr14": 100, "bias": "Bear"},
    ]},
    "4h": {"pairs": [
        {"pair": "BTC/USDC", "close": 90000, "ema_fast": 92000, "ema_slow": 95000,
         "rsi14": 40, "atr14": 800, "bias": "Bear"},
        {"pair": "ETH/USDC", "close": 3000, "ema_fast": 3010, "ema_slow": 3030,
         "rsi14": 48, "atr14": 50, "bias": "Bear"},
    ]},
    "1h": {"pairs": [
        {"pair": "BTC/USDC", "close": 90000, "ema_fast": 90100, "ema_slow": 90200,
         "rsi14": 45, "atr14": 300, "bias": "Bear"},
        {"pair": "ETH/USDC", "close": 3000, "ema_fast": 3005, "ema_slow": 3010,
         "rsi14": 47, "atr14": 20, "bias": "Bear"},
    ]},
}


def _defensive_decision(pair: str) -> DecisionResult:
    return DecisionResult(
        pair=pair,
        suggested_action=Action.DEFENSIVE,
        invalidation="Reclaim EMA50 4H + RSI 4H > 55",
        rationale="test",
        rule_id="R2",
        structure={"1d": "Bear", "4h": "Bear", "1h": "Bear"},
    )


# ================================================================== #
#  1. Réactivation déjà remplie
# ================================================================== #

class TestReactivationMet:
    def test_defensive_with_condition_met_is_flagged(self):
        d = decide("BTC/USDC", _ctx_bear_with_reactivation_met())
        assert d.suggested_action == Action.DEFENSIVE
        assert d.reactivation_met is True
        assert "déjà remplie" in d.rationale

    def test_defensive_condition_not_met(self):
        d = decide("ETH/USDC", _ctx_bear_not_met())
        assert d.suggested_action == Action.DEFENSIVE
        assert d.reactivation_met is False
        assert "déjà remplie" not in d.rationale

    def test_markdown_warns_when_met(self):
        d = decide("BTC/USDC", _ctx_bear_with_reactivation_met())
        md = decisions_to_markdown([d])
        assert "Condition déjà remplie" in md
        assert "prochaine clôture" in md

    def test_markdown_silent_when_not_met(self):
        d = decide("ETH/USDC", _ctx_bear_not_met())
        md = decisions_to_markdown([d])
        assert "Condition déjà remplie" not in md


class TestRecoveryLabel:
    def test_recovery_note_in_tech_table(self):
        """Croisement bear + prix > EMA20/EMA50 → note 'récupération'."""
        ctx = {"timeframe": "4h", "pairs": [
            {"pair": "BTC/USDC", "close": 63688.5, "ema_fast": 62798.36,
             "ema_slow": 63676.71, "rsi14": 56.47, "atr14": 991.7},
        ]}
        table = tech_table_from_context(ctx)
        assert "récupération en cours" in table

    def test_weakening_note_in_tech_table(self):
        """Croisement bull + prix < EMA20/EMA50 → note 'fragilisée'."""
        ctx = {"timeframe": "4h", "pairs": [
            {"pair": "ETH/USDC", "close": 3000, "ema_fast": 3100,
             "ema_slow": 3050, "rsi14": 48, "atr14": 50},
        ]}
        table = tech_table_from_context(ctx)
        assert "fragilisée" in table

    def test_normal_bear_keeps_default_note(self):
        ctx = {"timeframe": "4h", "pairs": [
            {"pair": "XRP/USDC", "close": 1.10, "ema_fast": 1.13,
             "ema_slow": 1.15, "rsi14": 45, "atr14": 0.02},
        ]}
        table = tech_table_from_context(ctx)
        assert "récupération" not in table
        assert "fragilisée" not in table


# ================================================================== #
#  2. Plan RAISE_CASH
# ================================================================== #

class TestRaiseCashPlan:
    def test_plan_generated_when_cash_below_target(self, low_cash_portfolio):
        result = PortfolioStrategyEngine.build(
            low_cash_portfolio, [], [],
            [_defensive_decision("BTC/USDC"), _defensive_decision("ETH/USDC")],
            CTX_RAISE_CASH,
        )
        assert result.cash_pct < result.cash_min_pct
        assert result.raise_cash_plan, "Plan RAISE_CASH attendu quand cash < cible"
        assert any("Vendre" in step for step in result.raise_cash_plan)

    def test_weakest_pair_sold_first(self, low_cash_portfolio):
        plan = PortfolioStrategyEngine._build_raise_cash_plan(
            low_cash_portfolio, CTX_RAISE_CASH, low_cash_portfolio.risk_limits
        )
        # BTC est à -5.3% sous EMA50 4H, ETH à -1.0% → BTC en premier
        assert "BTC" in plan[0]

    def test_core_never_touched(self, low_cash_portfolio):
        import re
        plan = PortfolioStrategyEngine._build_raise_cash_plan(
            low_cash_portfolio, CTX_RAISE_CASH, low_cash_portfolio.risk_limits
        )
        # BTC sellable swing = 0.02 - max(0.014, 0.01) = 0.006
        m = re.search(r"Vendre ~([\d.]+) BTC", plan[0])
        assert m, f"Ligne BTC introuvable: {plan[0]}"
        assert float(m.group(1)) <= 0.006 + 1e-9

    def test_no_plan_when_cash_ok(self, low_cash_portfolio):
        low_cash_portfolio.cash_usdc = 10_000  # cash largement au-dessus de 20%
        result = PortfolioStrategyEngine.build(
            low_cash_portfolio, [], [],
            [_defensive_decision("BTC/USDC"), _defensive_decision("ETH/USDC")],
            CTX_RAISE_CASH,
        )
        assert result.raise_cash_plan == []

    def test_plan_rendered_in_markdown(self, low_cash_portfolio):
        result = PortfolioStrategyEngine.build(
            low_cash_portfolio, [], [],
            [_defensive_decision("BTC/USDC"), _defensive_decision("ETH/USDC")],
            CTX_RAISE_CASH,
        )
        md = portfolio_strategy_to_markdown(result)
        assert "RAISE_CASH" in md
        assert "Vendre" in md

    def test_sell_level_guidance_present(self, low_cash_portfolio):
        plan = PortfolioStrategyEngine._build_raise_cash_plan(
            low_cash_portfolio, CTX_RAISE_CASH, low_cash_portfolio.risk_limits
        )
        # Prix sous EMA50 → consigne d'exécuter sur rebond, pas en panique
        assert any("rebond" in step for step in plan)


# ================================================================== #
#  4. Score de proximité de réactivation
# ================================================================== #

class TestReactivationProximityScore:
    def test_met_condition_scores_highest(self):
        e_met = {"close": 63688.5, "ema_slow": 63676.71, "rsi14": 56.47}
        e_close = {"close": 1674.91, "ema_slow": 1695.43, "rsi14": 53.15}
        e_far = {"close": 1.10, "ema_slow": 1.20, "rsi14": 38}
        s_met = _reactivation_proximity_score(e_met, reactivation_met=True)
        s_close = _reactivation_proximity_score(e_close)
        s_far = _reactivation_proximity_score(e_far)
        assert s_met > s_close > s_far

    def test_bounded_0_90(self):
        e = {"close": 100, "ema_slow": 99, "rsi14": 70}
        assert 0 <= _reactivation_proximity_score(e, True) <= 90
        assert _reactivation_proximity_score(None) == 0.0
        assert _reactivation_proximity_score({}) == 0.0

    def test_defensive_opportunities_not_all_zero(self):
        """Cas du rapport 12/06 : les 3 paires DEFENSIVE ne doivent plus
        toutes scorer 0.0."""
        ctx = _ctx_bear_with_reactivation_met()
        # Ajoute ETH au même contexte
        eth = _ctx_bear_not_met()
        for tf in ("1d", "4h", "1h"):
            ctx[tf]["pairs"].extend(eth[tf]["pairs"])

        decisions = [
            decide("BTC/USDC", ctx),
            decide("ETH/USDC", ctx),
        ]
        opps = OpportunityEngine.build_top3(ctx, None, decisions)
        assert opps, "Des opportunités DEFENSIVE sont attendues"
        scores = [o.score for o in opps]
        assert any(s > 0 for s in scores)
        # BTC (condition remplie) doit être priorisé devant ETH
        assert opps[0].pair == "BTC/USDC"

    def test_met_flag_in_action_text(self):
        ctx = _ctx_bear_with_reactivation_met()
        decisions = [decide("BTC/USDC", ctx)]
        opps = OpportunityEngine.build_top3(ctx, None, decisions)
        assert "déjà remplie" in opps[0].action_text


# ================================================================== #
#  5. Validation des sources
# ================================================================== #

class TestSourceValidation:
    def test_invalid_urls_dropped(self):
        n = Narrative(
            title="t", summary="s", tickers=["BTC"], heat=3,
            sources=["https://www.coindesk.com/article", "pas-une-url",
                     "ftp://ancien.protocole.com/x", "   "],
        )
        assert n.sources == ["https://www.coindesk.com/article"]

    def test_duplicate_source_kept_on_first_narrative_only(self):
        url = "https://blockworks.co/news/crypto-markets-fed-hold-june-2026"
        out = NarrativeScanOutput(narratives=[
            {"title": "n1", "summary": "s", "tickers": ["ETH"], "heat": 4, "sources": [url]},
            {"title": "n2", "summary": "s", "tickers": ["ETH"], "heat": 3, "sources": [url]},
            {"title": "n3", "summary": "s", "tickers": ["BTC"], "heat": 3,
             "sources": ["https://www.coindesk.com/markets/2026/06/12/other"]},
        ])
        # n2 partageait la même URL que n1 → écarté ; n1 et n3 conservés
        titles = [n.title for n in out.narratives]
        assert titles == ["n1", "n3"]

    def test_narrative_without_valid_source_dropped(self):
        out = NarrativeScanOutput(narratives=[
            {"title": "ok", "summary": "s", "tickers": [], "heat": 2,
             "sources": ["https://messari.io/report/x"]},
            {"title": "sans-source", "summary": "s", "tickers": [], "heat": 5,
             "sources": ["lien-invente"]},
        ])
        assert [n.title for n in out.narratives] == ["ok"]

    def test_distinct_sources_all_kept(self):
        out = NarrativeScanOutput(narratives=[
            {"title": "a", "summary": "s", "tickers": [], "heat": 3,
             "sources": ["https://www.theblock.co/1"]},
            {"title": "b", "summary": "s", "tickers": [], "heat": 3,
             "sources": ["https://www.theblock.co/2"]},
        ])
        assert len(out.narratives) == 2
