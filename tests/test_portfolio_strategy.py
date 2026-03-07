"""Tests unitaires - MarketRegimeDetector (local), BtcMacroRegimeDetector,
SignalEngine, PortfolioStrategyEngine V2 (Spot-Only)."""
import json
import os

import pytest

from cryptoscope_crew.domain.portfolio import (
    DecisionDefaults,
    Portfolio,
    Position,
    RiskLimits,
    load_portfolio,
)
from cryptoscope_crew.domain.decision_engine import Action, DecisionResult, decide_all
from cryptoscope_crew.domain.regime import MarketRegime, MarketRegimeDetector, RegimeResult
from cryptoscope_crew.domain.macro_regime import (
    BtcMacroRegimeDetector,
    MacroRegime,
    MacroRegimeResult,
)
from cryptoscope_crew.domain.signal_engine import SignalEngine, SignalType, MultiTFSignal
from cryptoscope_crew.domain.portfolio_strategy import (
    PortfolioStrategyEngine,
    PortfolioStrategyResult,
    PositionStrategy,
    StrategyAction,
    portfolio_strategy_to_markdown,
)


# ================================================================== #
#  Shared fixtures
# ================================================================== #

# BTC: 1D Bear (EMA20<EMA50), 4H Bull, 1H Bull (bounce in bear)
# ETH: 1D Bull (EMA20>EMA50), 4H Bull, 1H Bull (aligned bull)
# XRP: 1D Bear (EMA20<EMA50), 4H Bear, 1H Bear (aligned bear)
CTX = {
    "1d": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 94000, "ema_slow": 96000, "ema200": 97000, "rsi14": 42, "atr14": 2000, "bias": "Bear"},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3300, "ema_slow": 3100, "ema200": 3000, "rsi14": 58, "atr14": 100, "bias": "Bull"},
        {"pair": "XRP/USDC", "close": 0.50, "ema_fast": 0.49, "ema_slow": 0.52, "ema200": 0.54, "rsi14": 38, "atr14": 0.02, "bias": "Bear"},
    ]},
    "4h": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 95500, "ema_slow": 94000, "rsi14": 62, "atr14": 800, "bias": "Bull"},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3250, "ema_slow": 3150, "rsi14": 55, "atr14": 50, "bias": "Bull"},
        {"pair": "XRP/USDC", "close": 0.50, "ema_fast": 0.49, "ema_slow": 0.51, "rsi14": 40, "atr14": 0.01, "bias": "Bear"},
    ]},
    "1h": {"pairs": [
        {"pair": "BTC/USDC", "close": 95000, "ema_fast": 95200, "ema_slow": 94800, "rsi14": 72, "atr14": 300, "bias": "Bull"},
        {"pair": "ETH/USDC", "close": 3200, "ema_fast": 3210, "ema_slow": 3190, "rsi14": 55, "atr14": 20, "bias": "Bull"},
        {"pair": "XRP/USDC", "close": 0.50, "ema_fast": 0.50, "ema_slow": 0.505, "rsi14": 45, "atr14": 0.005, "bias": "Bear"},
    ]},
}

PAIRS = ["BTC/USDC", "ETH/USDC", "XRP/USDC"]


@pytest.fixture()
def portfolio():
    os.environ["PORTFOLIO_JSON"] = json.dumps({
        "cash_usdc": 2800,
        "positions": [
            {"pair": "BTC/USDC", "quantity": 0.022, "avg_price": 72575,
             "core_pct": 70, "swing_pct": 30, "min_core_qty": 0.015},
            {"pair": "ETH/USDC", "quantity": 0.53, "avg_price": 2129,
             "core_pct": 70, "swing_pct": 30, "min_core_qty": 0.35},
            {"pair": "XRP/USDC", "quantity": 331.10, "avg_price": 1.42,
             "core_pct": 70, "swing_pct": 30, "min_core_qty": 200},
        ],
        "risk_limits": {
            "cash_min_pct": 20,
            "max_exposure_pct": {"BTC/USDC": 40, "ETH/USDC": 30, "XRP/USDC": 15},
            "max_single_order_cash_pct": 12,
        },
        "decision_defaults": {
            "reduce_swing_pct_of_swing": 50,
            "add_small_cash_pct": 5,
            "buy_ladder_cash_pct": [6, 9, 12],
        },
    })
    p = load_portfolio()
    p.enrich_all({"BTC/USDC": 95000, "ETH/USDC": 3200, "XRP/USDC": 0.50})
    yield p
    os.environ.pop("PORTFOLIO_JSON", None)


# ================================================================== #
#  MarketRegimeDetector - LOCAL regime (EMA20/EMA50)
# ================================================================== #

class TestMarketRegimeDetector:
    def test_bear_regime(self):
        """BTC: EMA20 < EMA50 and close < EMA50 -> BEAR (local)."""
        r = MarketRegimeDetector.detect("BTC/USDC", CTX)
        assert r.regime == MarketRegime.BEAR
        assert r.pair == "BTC/USDC"
        assert r.ema_fast == 94000
        assert r.ema_slow == 96000

    def test_bull_regime(self):
        """ETH: EMA20 > EMA50 and close > EMA50 -> BULL (local)."""
        r = MarketRegimeDetector.detect("ETH/USDC", CTX)
        assert r.regime == MarketRegime.BULL
        assert r.ema_fast == 3300
        assert r.ema_slow == 3100

    def test_bear_regime_xrp(self):
        """XRP: EMA20 < EMA50 and close < EMA50 -> BEAR."""
        r = MarketRegimeDetector.detect("XRP/USDC", CTX)
        assert r.regime == MarketRegime.BEAR

    def test_range_regime_mixed(self):
        """When signals are mixed -> RANGE."""
        ctx = {
            "1d": {"pairs": [
                {"pair": "TEST/USDC", "close": 100, "ema_fast": 105, "ema_slow": 102,
                 "ema200": 101, "rsi14": 50, "atr14": 5, "bias": "Bull"},
            ]},
        }
        # close=100 < EMA50=102 but EMA20=105 > EMA50=102 -> mixed -> RANGE
        r = MarketRegimeDetector.detect("TEST/USDC", ctx)
        assert r.regime == MarketRegime.RANGE

    def test_detect_all_simple_batch(self):
        """detect_all is a simple batch - no clamping (hierarchy is in macro_regime)."""
        results = MarketRegimeDetector.detect_all(PAIRS, CTX)
        assert len(results) == 3
        assert results[0].regime == MarketRegime.BEAR   # BTC
        assert results[1].regime == MarketRegime.BULL    # ETH (unclamped)
        assert results[2].regime == MarketRegime.BEAR    # XRP

    def test_missing_pair_defaults_range(self):
        r = MarketRegimeDetector.detect("UNKNOWN/USDC", CTX)
        assert r.regime == MarketRegime.RANGE


# ================================================================== #
#  BtcMacroRegimeDetector - MACRO regime (EMA50/EMA200 + BTC-led)
# ================================================================== #

class TestBtcMacroRegimeDetector:
    def test_bear_macro(self):
        """BTC: close < EMA200 and EMA50 < EMA200 -> BEAR macro."""
        r = BtcMacroRegimeDetector.detect("BTC/USDC", CTX)
        assert r.macro == MacroRegime.BEAR
        assert r.pair == "BTC/USDC"
        assert r.ema200 == 97000
        assert r.ema50 == 96000

    def test_bull_macro(self):
        """ETH: close > EMA200 and EMA50 > EMA200 -> BULL macro (raw, unclamped)."""
        r = BtcMacroRegimeDetector.detect("ETH/USDC", CTX)
        assert r.macro == MacroRegime.BULL
        assert r.ema200 == 3000

    def test_transition_macro(self):
        """When macro signals are mixed -> TRANSITION."""
        ctx = {
            "1d": {"pairs": [
                {"pair": "TEST/USDC", "close": 100, "ema_fast": 105, "ema_slow": 102,
                 "ema200": 101, "rsi14": 50, "atr14": 5, "bias": "Bull"},
            ]},
        }
        # close=100 < ema200=101, but ema50=102 > ema200=101 -> mixed -> TRANSITION
        r = BtcMacroRegimeDetector.detect("TEST/USDC", ctx)
        assert r.macro == MacroRegime.TRANSITION

    def test_detect_all_with_btc_led(self):
        """detect_all applies BTC-led hierarchy:
        BTC=BEAR (primary), ETH=TRANSITION (raw BULL clamped), XRP=BEAR."""
        results = BtcMacroRegimeDetector.detect_all(PAIRS, CTX)
        assert len(results) == 3
        assert results[0].macro == MacroRegime.BEAR       # BTC (primary)
        assert results[1].macro == MacroRegime.TRANSITION  # ETH (raw BULL -> clamped)
        assert results[1].raw_macro == MacroRegime.BULL    # ETH raw
        assert results[1].btc_macro == MacroRegime.BEAR
        assert results[2].macro == MacroRegime.BEAR        # XRP (stays BEAR)

    def test_missing_pair_defaults_transition(self):
        r = BtcMacroRegimeDetector.detect("UNKNOWN/USDC", CTX)
        assert r.macro == MacroRegime.TRANSITION

    def test_btc_bull_no_clamping(self):
        """When BTC is BULL, no pair is clamped."""
        ctx_bull = {
            "1d": {"pairs": [
                {"pair": "BTC/USDC", "close": 100000, "ema_fast": 99000, "ema_slow": 98000, "ema200": 95000, "rsi14": 60, "atr14": 2000},
                {"pair": "ETH/USDC", "close": 3500, "ema_fast": 3400, "ema_slow": 3300, "ema200": 3000, "rsi14": 58, "atr14": 100},
                {"pair": "XRP/USDC", "close": 0.70, "ema_fast": 0.68, "ema_slow": 0.65, "ema200": 0.60, "rsi14": 55, "atr14": 0.02},
            ]},
        }
        results = BtcMacroRegimeDetector.detect_all(PAIRS, ctx_bull)
        assert results[0].macro == MacroRegime.BULL   # BTC
        assert results[1].macro == MacroRegime.BULL   # ETH - no clamping
        assert results[2].macro == MacroRegime.BULL   # XRP - no clamping

    def test_btc_transition_caps_opportunistic(self):
        """When BTC is TRANSITION, XRP BULL is capped to TRANSITION."""
        ctx_trans = {
            "1d": {"pairs": [
                # BTC: close>ema200 but ema50<ema200 -> mixed -> TRANSITION
                {"pair": "BTC/USDC", "close": 96000, "ema_fast": 95000, "ema_slow": 94000, "ema200": 95500, "rsi14": 50, "atr14": 2000},
                {"pair": "XRP/USDC", "close": 0.70, "ema_fast": 0.68, "ema_slow": 0.65, "ema200": 0.60, "rsi14": 55, "atr14": 0.02},
            ]},
        }
        results = BtcMacroRegimeDetector.detect_all(
            ["BTC/USDC", "XRP/USDC"], ctx_trans,
        )
        assert results[0].macro == MacroRegime.TRANSITION  # BTC
        assert results[1].raw_macro == MacroRegime.BULL     # XRP raw
        assert results[1].macro == MacroRegime.TRANSITION   # XRP capped

    def test_btc_bear_forces_opportunistic_bear(self):
        """When BTC=BEAR, an opportunistic pair with raw BULL is forced BEAR."""
        ctx_forced = {
            "1d": {"pairs": [
                {"pair": "BTC/USDC", "close": 90000, "ema_fast": 92000, "ema_slow": 93000, "ema200": 95000, "rsi14": 35, "atr14": 2000},
                {"pair": "XRP/USDC", "close": 0.70, "ema_fast": 0.68, "ema_slow": 0.65, "ema200": 0.60, "rsi14": 55, "atr14": 0.02},
            ]},
        }
        results = BtcMacroRegimeDetector.detect_all(
            ["BTC/USDC", "XRP/USDC"], ctx_forced,
        )
        assert results[0].macro == MacroRegime.BEAR       # BTC
        assert results[1].raw_macro == MacroRegime.BULL    # XRP raw
        assert results[1].macro == MacroRegime.BEAR        # XRP forced BEAR


# ================================================================== #
#  SignalEngine
# ================================================================== #

class TestSignalEngine:
    def test_bear_bounce(self):
        """BTC: 1D Bear + 4H Bull + 1H Bull -> SELL_BOUNCE."""
        regime = RegimeResult(pair="BTC/USDC", regime=MarketRegime.BEAR)
        sig = SignalEngine.analyze("BTC/USDC", CTX, regime)
        assert sig.signal == SignalType.SELL_BOUNCE
        assert "bounce" in sig.environment.lower() or "reduce" in sig.environment.lower()

    def test_aligned_bull(self):
        """ETH: 1D Bull + 4H Bull + 1H Bull -> ALIGNED_BULL."""
        regime = RegimeResult(pair="ETH/USDC", regime=MarketRegime.BULL)
        sig = SignalEngine.analyze("ETH/USDC", CTX, regime)
        assert sig.signal == SignalType.ALIGNED_BULL

    def test_aligned_bear(self):
        """XRP: 1D Bear + 4H Bear + 1H Bear -> ALIGNED_BEAR."""
        regime = RegimeResult(pair="XRP/USDC", regime=MarketRegime.BEAR)
        sig = SignalEngine.analyze("XRP/USDC", CTX, regime)
        assert sig.signal == SignalType.ALIGNED_BEAR

    def test_bull_weakening(self):
        """1D Bull + 4H Bear + 1H Bear -> BULL_WEAKENING."""
        regime = RegimeResult(pair="ETH/USDC", regime=MarketRegime.BULL)
        ctx_weak = {
            "4h": {"pairs": [{"pair": "ETH/USDC", "close": 3200, "ema_fast": 3100, "ema_slow": 3300, "rsi14": 40, "atr14": 50, "bias": "Bear"}]},
            "1h": {"pairs": [{"pair": "ETH/USDC", "close": 3200, "ema_fast": 3180, "ema_slow": 3220, "rsi14": 42, "atr14": 20, "bias": "Bear"}]},
        }
        sig = SignalEngine.analyze("ETH/USDC", ctx_weak, regime)
        assert sig.signal == SignalType.BULL_WEAKENING

    def test_analyze_all(self):
        """analyze_all uses local regimes (no clamping)."""
        regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, regimes)
        assert len(signals) == 3
        assert signals[0].signal == SignalType.SELL_BOUNCE    # BTC (local BEAR)
        assert signals[1].signal == SignalType.ALIGNED_BULL   # ETH (local BULL, no clamping)
        assert signals[2].signal == SignalType.ALIGNED_BEAR   # XRP (local BEAR)

    def test_analyze_all_with_btc_macro(self):
        """When btc_macro is provided, environment labels are enriched."""
        regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(
            PAIRS, CTX, regimes, btc_macro=MacroRegime.BEAR,
        )
        # BTC itself is not enriched
        assert "BTC macro" not in signals[0].environment
        # ETH and XRP get macro context
        assert "BTC macro BEAR" in signals[1].environment
        assert "BTC macro BEAR" in signals[2].environment

    def test_buy_dip_signal(self):
        """1D Bull + 4H Bull + 1H Bear -> BUY_DIP."""
        regime = RegimeResult(pair="ETH/USDC", regime=MarketRegime.BULL)
        ctx_dip = {
            "4h": {"pairs": [{"pair": "ETH/USDC", "close": 3200, "ema_fast": 3250, "ema_slow": 3150, "rsi14": 55, "atr14": 50, "bias": "Bull"}]},
            "1h": {"pairs": [{"pair": "ETH/USDC", "close": 3200, "ema_fast": 3180, "ema_slow": 3220, "rsi14": 42, "atr14": 20, "bias": "Bear"}]},
        }
        sig = SignalEngine.analyze("ETH/USDC", ctx_dip, regime)
        assert sig.signal == SignalType.BUY_DIP


# ================================================================== #
#  PortfolioStrategyEngine - V2 Spot-Only
# ================================================================== #

class TestPortfolioStrategyEngine:
    def test_full_pipeline(self, portfolio):
        """End-to-end: local regime + macro regime -> signal -> decision -> strategy."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        macro_regimes = BtcMacroRegimeDetector.detect_all(PAIRS, CTX)
        btc_macro = next(
            (m.macro for m in macro_regimes if m.pair.startswith("BTC")),
            MacroRegime.TRANSITION,
        )
        signals = SignalEngine.analyze_all(
            PAIRS, CTX, local_regimes, btc_macro=btc_macro,
        )
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
            macro_regimes=macro_regimes,
        )

        assert isinstance(result, PortfolioStrategyResult)
        assert len(result.positions) == 3
        assert result.cash_usdc == 2800
        assert result.overall_regime in ("BULL", "BEAR", "RANGE")

        # BTC: 1D local Bear + 4H Bull + RSI 1H > 70 -> REDUCE_SWING
        btc = result.positions[0]
        assert btc.pair == "BTC/USDC"
        assert btc.strategy == StrategyAction.REDUCE_SWING

        # ETH: local BULL + HOLD_OR_ADD, but BTC macro BEAR -> HOLD (gated)
        eth = result.positions[1]
        assert eth.pair == "ETH/USDC"
        assert eth.strategy == StrategyAction.HOLD
        assert "macro" in eth.rationale.lower()

        # XRP: aligned bear -> DEFENSIVE
        xrp = result.positions[2]
        assert xrp.pair == "XRP/USDC"
        assert xrp.strategy == StrategyAction.DEFENSIVE

    def test_full_pipeline_no_macro(self, portfolio):
        """Without macro_regimes, no macro gating - ETH gets ADD_SMALL."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )

        # ETH: local BULL + ALIGNED_BULL + no macro gate -> ADD_SMALL
        eth = result.positions[1]
        assert eth.pair == "ETH/USDC"
        assert eth.strategy == StrategyAction.ADD_SMALL

    def test_spot_actions_only(self, portfolio):
        """V2: only spot-compatible actions are produced."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        macro_regimes = BtcMacroRegimeDetector.detect_all(PAIRS, CTX)
        btc_macro = next(
            (m.macro for m in macro_regimes if m.pair.startswith("BTC")),
            MacroRegime.TRANSITION,
        )
        signals = SignalEngine.analyze_all(
            PAIRS, CTX, local_regimes, btc_macro=btc_macro,
        )
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
            macro_regimes=macro_regimes,
        )
        valid = {StrategyAction.ADD_SMALL, StrategyAction.HOLD,
                 StrategyAction.WAIT, StrategyAction.REDUCE_SWING,
                 StrategyAction.DEFENSIVE, StrategyAction.REBUILD_LADDER}
        for ps in result.positions:
            assert ps.strategy in valid, f"{ps.pair} has invalid action {ps.strategy}"

    def test_markdown_output_spot_framing(self, portfolio):
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        md = portfolio_strategy_to_markdown(result)

        assert "## Spot Portfolio Strategy" in md
        assert "SPOT ONLY" in md
        assert "### BTC/USDC" in md
        assert "### ETH/USDC" in md
        assert "### XRP/USDC" in md
        assert "### Cash" in md
        assert "Target reserve" in md

    def test_pnl_present(self, portfolio):
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        # BTC bought at 72575, now at 95000 -> positive PnL
        btc = result.positions[0]
        assert btc.pnl_pct > 0

    def test_core_swing_in_output(self, portfolio):
        """V2: core_qty, swing_qty, min_core_qty are populated."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        btc = result.positions[0]
        assert btc.core_qty > 0
        assert btc.swing_qty > 0
        assert btc.min_core_qty == 0.015

    def test_reduce_swing_respects_min_core(self):
        """When swing is at floor, REDUCE_SWING action becomes HOLD."""
        pos = Position(
            pair="BTC/USDC", quantity=0.015, avg_price=72575,
            core_pct=100, swing_pct=0, min_core_qty=0.015,
        )
        pos.enrich(95000.0)
        p = Portfolio(cash_usdc=3000, positions=[pos])
        regimes = [RegimeResult(pair="BTC/USDC", regime=MarketRegime.BEAR)]
        signals = [MultiTFSignal(
            pair="BTC/USDC", signal=SignalType.SELL_BOUNCE,
            bias_1d="Bear", bias_4h="Bull", bias_1h="Bull",
            environment="reduce swing on bounce",
        )]
        decisions = [DecisionResult(
            pair="BTC/USDC", suggested_action=Action.REDUCE_SWING,
            structure={"1d": "Bear", "4h": "Bull", "1h": "Bull"},
            rule_id="R1",
        )]
        result = PortfolioStrategyEngine.build(p, regimes, signals, decisions, CTX)
        assert result.positions[0].strategy == StrategyAction.HOLD
        assert "floor" in result.positions[0].adjustment.lower()

    def test_add_small_respects_cash_floor(self):
        """When cash is at the minimum reserve, ADD_SMALL becomes HOLD."""
        pos = Position(
            pair="ETH/USDC", quantity=0.53, avg_price=2129,
            core_pct=70, swing_pct=30, min_core_qty=0.35,
        )
        pos.enrich(3200.0)
        p = Portfolio(
            cash_usdc=100, positions=[pos],
            risk_limits=RiskLimits(cash_min_pct=20),
            defaults=DecisionDefaults(add_small_cash_pct=5),
        )
        regimes = [RegimeResult(pair="ETH/USDC", regime=MarketRegime.BULL)]
        signals = [MultiTFSignal(
            pair="ETH/USDC", signal=SignalType.ALIGNED_BULL,
            bias_1d="Bull", bias_4h="Bull", bias_1h="Bull",
            environment="full bull - hold & add",
        )]
        decisions = [DecisionResult(
            pair="ETH/USDC", suggested_action=Action.HOLD_OR_ADD,
            structure={"1d": "Bull", "4h": "Bull", "1h": "Bull"},
            rule_id="R3",
        )]
        result = PortfolioStrategyEngine.build(p, regimes, signals, decisions, CTX)
        assert result.positions[0].strategy == StrategyAction.HOLD
        assert "floor" in result.positions[0].adjustment.lower() or "reserve" in result.positions[0].rationale.lower()

    def test_rebuild_ladder_produces_steps(self, portfolio):
        """REBUILD_LADDER produces staged buy ladder steps."""
        regimes = [RegimeResult(pair="BTC/USDC", regime=MarketRegime.BULL)]
        signals = [MultiTFSignal(
            pair="BTC/USDC", signal=SignalType.BUY_DIP,
            bias_1d="Bull", bias_4h="Bear", bias_1h="Bear",
            rsi_1h=35.0,
            environment="buy dip - spot ladder",
        )]
        decisions = [DecisionResult(
            pair="BTC/USDC", suggested_action=Action.REBUILD_LADDER,
            structure={"1d": "Bull", "4h": "Bear", "1h": "Bear"},
            rule_id="R4",
        )]
        p = Portfolio(
            cash_usdc=portfolio.cash_usdc,
            positions=[portfolio.positions[0]],
            risk_limits=portfolio.risk_limits,
            defaults=portfolio.defaults,
        )
        result = PortfolioStrategyEngine.build(p, regimes, signals, decisions, CTX)
        btc = result.positions[0]
        assert btc.strategy == StrategyAction.REBUILD_LADDER
        assert "Step 1" in btc.adjustment
        assert "Step 2" in btc.adjustment

    def test_rebuild_ladder_gated_by_macro_bear(self, portfolio):
        """REBUILD_LADDER becomes WAIT when BTC macro is BEAR."""
        regimes = [RegimeResult(pair="BTC/USDC", regime=MarketRegime.BULL)]
        signals = [MultiTFSignal(
            pair="BTC/USDC", signal=SignalType.BUY_DIP,
            bias_1d="Bull", bias_4h="Bear", bias_1h="Bear",
            rsi_1h=35.0,
            environment="buy dip - spot ladder",
        )]
        decisions = [DecisionResult(
            pair="BTC/USDC", suggested_action=Action.REBUILD_LADDER,
            structure={"1d": "Bull", "4h": "Bear", "1h": "Bear"},
            rule_id="R4",
        )]
        macro_regimes = [MacroRegimeResult(
            pair="BTC/USDC", macro=MacroRegime.BEAR,
        )]
        p = Portfolio(
            cash_usdc=portfolio.cash_usdc,
            positions=[portfolio.positions[0]],
            risk_limits=portfolio.risk_limits,
            defaults=portfolio.defaults,
        )
        result = PortfolioStrategyEngine.build(
            p, regimes, signals, decisions, CTX,
            macro_regimes=macro_regimes,
        )
        btc = result.positions[0]
        assert btc.strategy == StrategyAction.WAIT
        assert "macro" in btc.rationale.lower()

    def test_adjustment_contains_ema_level(self, portfolio):
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        # BTC REDUCE_SWING should mention EMA20 4H level
        btc = result.positions[0]
        assert "EMA20 4H" in btc.adjustment

    def test_empty_portfolio(self):
        """Empty portfolio produces empty positions list."""
        p = Portfolio(cash_usdc=1000)
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, p, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            p, local_regimes, signals, decisions, CTX,
        )
        assert len(result.positions) == 0
        assert result.cash_usdc == 1000

    def test_serialization_roundtrip(self, portfolio):
        """PortfolioStrategyResult can be serialized and deserialized."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        data = result.model_dump(mode="json")
        assert isinstance(json.dumps(data), str)
        restored = PortfolioStrategyResult.model_validate(data)
        assert len(restored.positions) == len(result.positions)

    def test_summary_contains_spot_only(self, portfolio):
        """V2 summary line contains SPOT ONLY marker."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        assert "SPOT ONLY" in result.summary

    def test_cash_min_pct_in_result(self, portfolio):
        """V2 result carries cash_min_pct from risk_limits."""
        local_regimes = MarketRegimeDetector.detect_all(PAIRS, CTX)
        signals = SignalEngine.analyze_all(PAIRS, CTX, local_regimes)
        decisions = decide_all(PAIRS, CTX, portfolio, regimes=local_regimes)
        result = PortfolioStrategyEngine.build(
            portfolio, local_regimes, signals, decisions, CTX,
        )
        assert result.cash_min_pct == 20.0
