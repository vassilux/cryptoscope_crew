"""Tests unitaires — Decision Engine V1 + portfolio + MD parser."""
import os
import json
import pytest

from cryptoscope_crew.domain.portfolio import load_portfolio, Portfolio, Position
from cryptoscope_crew.domain.decision_engine import (
    Action,
    decide,
    decide_all,
    decisions_to_markdown,
    _parse_one_table,
    parse_md_tables,
)


# ================================================================== #
#  Fixtures
# ================================================================== #

SAMPLE_TABLE = """\
| **Pair** | Close | EMA20 | EMA50 | RSI14 | ATR14 | Bias | Conf | Notes |
|----------|-------|-------|-------|-------|-------|------|------|-------|
| **BTC/USDC** | 95000.0000 | 94000.0000 | 96000.0000 | 42.00 | 2000.0000 | Bear | High | daily bear |
| **ETH/USDC** | 3200.0000 | 3300.0000 | 3100.0000 | 58.00 | 100.0000 | Bull | Med | 1D bull |
| **XRP/USDC** | 0.5000 | 0.4900 | 0.5200 | 38.00 | 0.0200 | Bear | Low | daily bear |
"""

TECH_TABLES_SECONDARY = """\
### Table 4h
-----
| **Pair** | Close | EMA20 | EMA50 | RSI14 | ATR14 | Bias | Conf | Notes |
|----------|-------|-------|-------|-------|-------|------|------|-------|
| **BTC/USDC** | 95000.0000 | 95500.0000 | 94000.0000 | 62.00 | 800.0000 | Bull | High | 4h bull |
| **ETH/USDC** | 3200.0000 | 3250.0000 | 3150.0000 | 55.00 | 50.0000 | Bull | Med | 4h bull |
| **XRP/USDC** | 0.5000 | 0.4900 | 0.5100 | 40.00 | 0.0100 | Bear | Low | 4h bear |
-----

### Table 1h
-----
| **Pair** | Close | EMA20 | EMA50 | RSI14 | ATR14 | Bias | Conf | Notes |
|----------|-------|-------|-------|-------|-------|------|------|-------|
| **BTC/USDC** | 95000.0000 | 95200.0000 | 94800.0000 | 72.00 | 300.0000 | Bull | High | 1h hot |
| **ETH/USDC** | 3200.0000 | 3210.0000 | 3190.0000 | 55.00 | 20.0000 | Bull | Med | 1h ok |
| **XRP/USDC** | 0.5000 | 0.5000 | 0.5050 | 45.00 | 0.0050 | Bear | Low | 1h bear |
-----
"""

# Equivalent dict-based context (for comparison)
CTX_DICT = {
    "1d": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 94000, "ema_slow": 96000, "rsi14": 42, "atr14": 2000},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3300, "ema_slow": 3100, "rsi14": 58, "atr14": 100},
        {"pair": "XRP/USDC", "close": 0.5, "ema_fast": 0.49, "ema_slow": 0.52, "rsi14": 38, "atr14": 0.02},
    ]},
    "4h": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 95500, "ema_slow": 94000, "rsi14": 62, "atr14": 800},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3250, "ema_slow": 3150, "rsi14": 55, "atr14": 50},
        {"pair": "XRP/USDC", "close": 0.5, "ema_fast": 0.49, "ema_slow": 0.51, "rsi14": 40, "atr14": 0.01},
    ]},
    "1h": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 95200, "ema_slow": 94800, "rsi14": 72, "atr14": 300},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3210, "ema_slow": 3190, "rsi14": 55, "atr14": 20},
        {"pair": "XRP/USDC", "close": 0.5, "ema_fast": 0.50, "ema_slow": 0.505, "rsi14": 45, "atr14": 0.005},
    ]},
}


@pytest.fixture()
def portfolio():
    os.environ["PORTFOLIO_JSON"] = json.dumps({
        "cash_usdc": 500,
        "positions": [
            {"pair": "BTC/USDC", "quantity": 0.12, "avg_price": 62000},
            {"pair": "ETH/USDC", "quantity": 2.5, "avg_price": 3100},
        ],
    })
    p = load_portfolio()
    p.enrich_all({"BTC/USDC": 95000, "ETH/USDC": 3200})
    yield p
    os.environ.pop("PORTFOLIO_JSON", None)


# ================================================================== #
#  Portfolio tests
# ================================================================== #

class TestPortfolio:
    def test_load_and_enrich(self, portfolio):
        assert len(portfolio.positions) == 2
        assert portfolio.positions[0].pnl_pct > 0  # BTC +53 %

    def test_empty_fallback(self):
        os.environ.pop("PORTFOLIO_JSON", None)
        os.environ.pop("PORTFOLIO_FILE", None)
        p = load_portfolio()
        assert len(p.positions) == 0


# ================================================================== #
#  MD table parser tests
# ================================================================== #

class TestMDParser:
    def test_parse_one_table_extracts_all_rows(self):
        rows = _parse_one_table(SAMPLE_TABLE)
        assert len(rows) == 3

    def test_parse_one_table_values(self):
        rows = _parse_one_table(SAMPLE_TABLE)
        btc = rows[0]
        assert btc["pair"] == "BTC/USDC"
        assert btc["close"] == 95000.0
        assert btc["ema_fast"] == 94000.0
        assert btc["ema_slow"] == 96000.0
        assert btc["rsi14"] == 42.0
        assert btc["bias"] == "Bear"

    def test_parse_one_table_bias_column(self):
        rows = _parse_one_table(SAMPLE_TABLE)
        assert rows[0]["bias"] == "Bear"
        assert rows[1]["bias"] == "Bull"
        assert rows[2]["bias"] == "Bear"

    def test_parse_one_table_empty_string(self):
        assert _parse_one_table("") == []
        assert _parse_one_table("no table here") == []

    def test_parse_md_tables_three_timeframes(self):
        ctx = parse_md_tables(SAMPLE_TABLE, TECH_TABLES_SECONDARY)
        assert set(ctx.keys()) == {"1d", "4h", "1h"}
        assert len(ctx["1d"]["pairs"]) == 3
        assert len(ctx["4h"]["pairs"]) == 3
        assert len(ctx["1h"]["pairs"]) == 3

    def test_parse_md_tables_values_match_dict(self):
        """Le résultat du parser MD doit donner les mêmes valeurs que le dict."""
        ctx = parse_md_tables(SAMPLE_TABLE, TECH_TABLES_SECONDARY)
        btc_4h = next(p for p in ctx["4h"]["pairs"] if p["pair"] == "BTC/USDC")
        assert btc_4h["ema_fast"] == 95500.0
        assert btc_4h["ema_slow"] == 94000.0
        assert btc_4h["rsi14"] == 62.0


# ================================================================== #
#  Decision rules tests (via dict)
# ================================================================== #

class TestDecisionRules:
    """Valide les 4 règles V1 : R1, R2, R3, R5 (WAIT fallback)."""

    def test_r1_reduce_swing(self):
        """1D Bear + 4H Bull + RSI 1H > 70 → REDUCE_SWING."""
        d = decide("BTC/USDC", CTX_DICT)
        assert d.suggested_action == Action.REDUCE_SWING
        assert d.rule_id == "R1"
        assert d.reentry_zone and "95500" in d.reentry_zone
        assert d.invalidation and "94000" in d.invalidation
        assert d.distance_pct is not None

    def test_r1_with_lowercase_bias(self):
        """Même scénario mais bias en minuscules (comme precompute_multi)."""
        ctx_lower = {
            "1d": {"pairs": [{"pair": "BTC/USDC", "close": 95000, "ema_fast": 94000, "ema_slow": 96000, "rsi14": 42, "atr14": 2000, "bias": "bear"}]},
            "4h": {"pairs": [{"pair": "BTC/USDC", "close": 95000, "ema_fast": 95500, "ema_slow": 94000, "rsi14": 62, "atr14": 800, "bias": "bull"}]},
            "1h": {"pairs": [{"pair": "BTC/USDC", "close": 95000, "ema_fast": 95200, "ema_slow": 94800, "rsi14": 72, "atr14": 300, "bias": "bull"}]},
        }
        d = decide("BTC/USDC", ctx_lower)
        assert d.suggested_action == Action.REDUCE_SWING
        assert d.rule_id == "R1"

    def test_r2_defensive(self):
        """1D Bear + 4H Bear → DEFENSIVE."""
        d = decide("XRP/USDC", CTX_DICT)
        assert d.suggested_action == Action.DEFENSIVE
        assert d.rule_id == "R2"

    def test_r3_hold_or_add(self):
        """1D Bull + 4H Bull → HOLD_OR_ADD."""
        d = decide("ETH/USDC", CTX_DICT)
        assert d.suggested_action == Action.HOLD_OR_ADD
        assert d.rule_id == "R3"

    def test_r5_wait_fallback(self):
        """Aucune règle → WAIT."""
        ctx_mixed = {
            "1d": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 52, "atr14": 5}]},
            "4h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 149, "ema_slow": 151, "rsi14": 48, "atr14": 3}]},
            "1h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 150.5, "ema_slow": 149.5, "rsi14": 50, "atr14": 1}]},
        }
        d = decide("SOL/USDC", ctx_mixed)
        assert d.suggested_action == Action.WAIT
        assert d.rule_id == "R5"


# ================================================================== #
#  Decision rules via MD tables (round-trip: MD → parse → decide)
# ================================================================== #

class TestDecisionFromMD:
    """Même scénario BTC/ETH/XRP mais partant des tables Markdown."""

    def test_r1_from_md(self):
        ctx = parse_md_tables(SAMPLE_TABLE, TECH_TABLES_SECONDARY)
        d = decide("BTC/USDC", ctx)
        assert d.suggested_action == Action.REDUCE_SWING
        assert d.rule_id == "R1"

    def test_r2_from_md(self):
        ctx = parse_md_tables(SAMPLE_TABLE, TECH_TABLES_SECONDARY)
        d = decide("XRP/USDC", ctx)
        assert d.suggested_action == Action.DEFENSIVE
        assert d.rule_id == "R2"

    def test_r3_from_md(self):
        ctx = parse_md_tables(SAMPLE_TABLE, TECH_TABLES_SECONDARY)
        d = decide("ETH/USDC", ctx)
        assert d.suggested_action == Action.HOLD_OR_ADD
        assert d.rule_id == "R3"

    def test_decide_all_via_md_tables(self):
        """decide_all() avec uniquement tech_table_md + tech_tables_md."""
        results = decide_all(
            ["BTC/USDC", "ETH/USDC", "XRP/USDC"],
            tech_table_md=SAMPLE_TABLE,
            tech_tables_md=TECH_TABLES_SECONDARY,
        )
        assert results[0].suggested_action == Action.REDUCE_SWING  # BTC
        assert results[1].suggested_action == Action.HOLD_OR_ADD   # ETH
        assert results[2].suggested_action == Action.DEFENSIVE     # XRP


# ================================================================== #
#  Markdown output
# ================================================================== #

class TestMarkdownOutput:
    def test_decisions_to_markdown_header(self):
        decisions = decide_all(["BTC/USDC", "ETH/USDC", "XRP/USDC"], CTX_DICT)
        md = decisions_to_markdown(decisions)
        assert md.startswith("## Decision Summary (V1)")

    def test_decisions_to_markdown_contains_actions(self):
        decisions = decide_all(["BTC/USDC", "ETH/USDC", "XRP/USDC"], CTX_DICT)
        md = decisions_to_markdown(decisions)
        assert "REDUCE_SWING" in md
        assert "HOLD_OR_ADD" in md
        assert "DEFENSIVE" in md

    def test_decisions_to_markdown_contains_reentry_and_invalidation(self):
        decisions = decide_all(["BTC/USDC"], CTX_DICT)
        md = decisions_to_markdown(decisions)
        assert "Re-entry zone" in md
        assert "Invalidation" in md
        assert "Distance close/EMA20 4H" in md

    def test_example_output(self):
        """Produit l'exemple demandé : BTC/ETH/XRP → actions attendues."""
        decisions = decide_all(
            ["BTC/USDC", "ETH/USDC", "XRP/USDC"],
            tech_table_md=SAMPLE_TABLE,
            tech_tables_md=TECH_TABLES_SECONDARY,
        )
        md = decisions_to_markdown(decisions)
        print("\n" + md)
        # Vérifie la sortie attendue
        assert len(decisions) == 3
        btc, eth, xrp = decisions
        assert btc.suggested_action == Action.REDUCE_SWING
        assert btc.structure == {"1d": "Bear", "4h": "Bull", "1h": "Bull"}
        assert eth.suggested_action == Action.HOLD_OR_ADD
        assert eth.structure == {"1d": "Bull", "4h": "Bull", "1h": "Bull"}
        assert xrp.suggested_action == Action.DEFENSIVE
        assert xrp.structure == {"1d": "Bear", "4h": "Bear", "1h": "Bear"}

    def test_real_report_data(self):
        """Données réelles du rapport 2026-03-04 — bias lowercase comme precompute."""
        ctx_real = {
            "1d": {"pairs": [
                {"pair": "BTC/USDC", "close": 71464.09, "ema_fast": 68722.4705, "ema_slow": 74374.022, "rsi14": 53.53, "atr14": 3509.49, "bias": "bear"},
                {"pair": "ETH/USDC", "close": 2063.60, "ema_fast": 2027.7631, "ema_slow": 2293.2197, "rsi14": 48.75, "atr14": 138.95, "bias": "bear"},
                {"pair": "XRP/USDC", "close": 1.406, "ema_fast": 1.4182, "ema_slow": 1.5717, "rsi14": 45.60, "atr14": 0.0953, "bias": "bear"},
            ]},
            "4h": {"pairs": [
                {"pair": "BTC/USDC", "close": 71505.63, "ema_fast": 68338.0679, "ema_slow": 67483.1809, "rsi14": 67.88, "atr14": 1558.32, "bias": "bull"},
                {"pair": "ETH/USDC", "close": 2064.99, "ema_fast": 1996.2525, "ema_slow": 1979.7568, "rsi14": 61.61, "atr14": 56.87, "bias": "bull"},
                {"pair": "XRP/USDC", "close": 1.4065, "ema_fast": 1.3748, "ema_slow": 1.3804, "rsi14": 58.24, "atr14": 0.0342, "bias": "bear"},
            ]},
            "1h": {"pairs": [
                {"pair": "BTC/USDC", "close": 71499.02, "ema_fast": 69788.8659, "ema_slow": 68676.7639, "rsi14": 72.48, "atr14": 760.34, "bias": "bull"},
                {"pair": "ETH/USDC", "close": 2064.85, "ema_fast": 2021.9364, "ema_slow": 2000.6648, "rsi14": 67.15, "atr14": 26.18, "bias": "bull"},
                {"pair": "XRP/USDC", "close": 1.4063, "ema_fast": 1.3829, "ema_slow": 1.3742, "rsi14": 64.45, "atr14": 0.0159, "bias": "bull"},
            ]},
        }
        decisions = decide_all(["BTC/USDC", "ETH/USDC", "XRP/USDC"], ctx_real)
        md = decisions_to_markdown(decisions)
        print("\n--- Real report 2026-03-04 ---\n" + md)

        btc, eth, xrp = decisions
        # BTC: 1D bear + 4H bull + RSI 1H 72.48 > 70 → R1 REDUCE_SWING
        assert btc.suggested_action == Action.REDUCE_SWING
        assert btc.rule_id == "R1"
        assert "68338" in btc.reentry_zone      # EMA20 4H
        assert "67483" in btc.invalidation      # EMA50 4H

        # ETH: 1D bear + 4H bull + RSI 1H 67.15 < 70 → pas R1 ; 1D bear ≠ R3 → R5 WAIT
        assert eth.suggested_action == Action.WAIT
        assert eth.rule_id == "R5"

        # XRP: 1D bear + 4H bear → R2 DEFENSIVE
        assert xrp.suggested_action == Action.DEFENSIVE
        assert xrp.rule_id == "R2"


# ================================================================== #
#  distance_pct + watch_levels tests
# ================================================================== #

class TestDistancePctAndWatch:
    """Valide le calcul distance_pct et les watch_levels (WAIT)."""

    def test_distance_pct_above_3_adjusts_to_20(self):
        """close_4h très au-dessus d'EMA20 4H (>3%) → adjustment_pct = 20."""
        ctx = {
            "1d": {"pairs": [{"pair": "BTC/USDC", "close": 70000, "ema_fast": 69000, "ema_slow": 72000, "rsi14": 40, "atr14": 2000, "bias": "bear"}]},
            "4h": {"pairs": [{"pair": "BTC/USDC", "close": 72000, "ema_fast": 69000, "ema_slow": 67000, "rsi14": 65, "atr14": 800, "bias": "bull"}]},
            "1h": {"pairs": [{"pair": "BTC/USDC", "close": 72000, "ema_fast": 71500, "ema_slow": 71000, "rsi14": 75, "atr14": 300, "bias": "bull"}]},
        }
        # distance = (72000 - 69000) / 69000 * 100 = 4.35% > 3%
        d = decide("BTC/USDC", ctx)
        assert d.suggested_action == Action.REDUCE_SWING
        assert d.distance_pct == pytest.approx(4.35, abs=0.01)
        assert d.adjustment_pct == 20

    def test_distance_pct_below_3_adjusts_to_10(self):
        """close_4h proche d'EMA20 4H (<3%) → adjustment_pct = 10."""
        ctx = {
            "1d": {"pairs": [{"pair": "BTC/USDC", "close": 70000, "ema_fast": 69000, "ema_slow": 72000, "rsi14": 40, "atr14": 2000, "bias": "bear"}]},
            "4h": {"pairs": [{"pair": "BTC/USDC", "close": 70500, "ema_fast": 69000, "ema_slow": 67000, "rsi14": 65, "atr14": 800, "bias": "bull"}]},
            "1h": {"pairs": [{"pair": "BTC/USDC", "close": 70500, "ema_fast": 70200, "ema_slow": 69800, "rsi14": 73, "atr14": 300, "bias": "bull"}]},
        }
        # distance = (70500 - 69000) / 69000 * 100 = 2.17% < 3%
        d = decide("BTC/USDC", ctx)
        assert d.suggested_action == Action.REDUCE_SWING
        assert d.distance_pct == pytest.approx(2.17, abs=0.01)
        assert d.adjustment_pct == 10

    def test_wait_has_watch_levels(self):
        """WAIT doit inclure watch_levels avec reentry_zone et risk_line."""
        ctx = {
            "1d": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 52, "atr14": 5, "bias": "bull"}]},
            "4h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 148, "ema_slow": 145, "rsi14": 48, "atr14": 3, "bias": "bear"}]},
            "1h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 150.5, "ema_slow": 149.5, "rsi14": 50, "atr14": 1, "bias": "bull"}]},
        }
        d = decide("SOL/USDC", ctx)
        assert d.suggested_action == Action.WAIT
        assert d.watch_levels is not None
        assert "148" in d.watch_levels["reentry_zone"]    # EMA20 4H
        assert "145" in d.watch_levels["risk_line"]       # EMA50 4H

    def test_wait_watch_levels_in_markdown(self):
        """Le markdown WAIT contient les Watch levels."""
        ctx = {
            "1d": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 151, "ema_slow": 149, "rsi14": 52, "atr14": 5, "bias": "bull"}]},
            "4h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 148, "ema_slow": 145, "rsi14": 48, "atr14": 3, "bias": "bear"}]},
            "1h": {"pairs": [{"pair": "SOL/USDC", "close": 150, "ema_fast": 150.5, "ema_slow": 149.5, "rsi14": 50, "atr14": 1, "bias": "bull"}]},
        }
        decisions = decide_all(["SOL/USDC"], ctx)
        md = decisions_to_markdown(decisions)
        assert "Watch levels" in md
        assert "Re-entry zone: EMA20 4H" in md
        assert "Risk line: EMA50 4H" in md

    def test_defensive_reactivation_in_markdown(self):
        """Le markdown DEFENSIVE affiche 'Reactivation condition' et non 'Invalidation'."""
        decisions = decide_all(["XRP/USDC"], CTX_DICT)
        md = decisions_to_markdown(decisions)
        assert "Reactivation condition" in md
        assert "Invalidation" not in md
