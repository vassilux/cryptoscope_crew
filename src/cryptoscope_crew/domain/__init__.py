# src/cryptoscope_crew/domain/__init__.py
"""Domain models: portfolio, decisions, opportunities, regime, signals, strategy."""
from cryptoscope_crew.domain.schemas import Narrative, NarrativeScanOutput  # noqa: F401
from cryptoscope_crew.domain.portfolio import (  # noqa: F401
    DecisionDefaults,
    Portfolio,
    Position,
    RiskLimits,
    load_portfolio,
)
from cryptoscope_crew.domain.decision_engine import (  # noqa: F401
    Action,
    DecisionResult,
    decide,
    decide_all,
    decisions_to_markdown,
    parse_md_tables,
)
from cryptoscope_crew.domain.opportunities import (  # noqa: F401
    Opportunity,
    OpportunityEngine,
    opportunities_to_markdown,
)
from cryptoscope_crew.domain.regime import (  # noqa: F401
    MarketRegime,
    MarketRegimeDetector,
    RegimeResult,
)
from cryptoscope_crew.domain.macro_regime import (  # noqa: F401
    BtcMacroRegimeDetector,
    MacroRegime,
    MacroRegimeResult,
)
from cryptoscope_crew.domain.signal_engine import (  # noqa: F401
    MultiTFSignal,
    SignalEngine,
    SignalType,
)
from cryptoscope_crew.domain.portfolio_strategy import (  # noqa: F401
    PortfolioStrategyEngine,
    PortfolioStrategyResult,
    PositionStrategy,
    StrategyAction,
    portfolio_strategy_to_markdown,
)