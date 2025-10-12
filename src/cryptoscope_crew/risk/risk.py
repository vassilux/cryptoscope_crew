from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RiskParams:
    risk_per_trade: float = 0.005  # 0.5%
    max_portfolio_risk: float = 0.02

def position_size(balance: float, entry: float, stop: float, rp: RiskParams) -> float:
    # Basic fixed‑fractional sizing
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    capital_risk = balance * rp.risk_per_trade
    size = capital_risk / risk
    return max(size, 0.0)
