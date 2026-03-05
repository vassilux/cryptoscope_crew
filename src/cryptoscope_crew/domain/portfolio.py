# src/cryptoscope_crew/domain/portfolio.py
"""Modèle de portefeuille — positions réelles + cash.

Chargement depuis :
  - variable d'env PORTFOLIO_JSON  (inline)
  - fichier pointé par PORTFOLIO_FILE (chemin)
  - fallback : portefeuille vide

Format JSON attendu :
{
  "cash_usdc": 500.0,
  "positions": [
    {"pair": "BTC/USDC", "quantity": 0.12, "avg_price": 62000},
    {"pair": "ETH/USDC", "quantity": 2.5,  "avg_price": 3100},
    {"pair": "XRP/USDC", "quantity": 4000, "avg_price": 0.52}
  ]
}
"""
from __future__ import annotations

import json, os, pathlib
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError


# ------------------------------------------------------------------ #
#  Modèles
# ------------------------------------------------------------------ #

class Position(BaseModel):
    """Une ligne du portefeuille."""

    pair: str                                       # ex. "BTC/USDC"
    quantity: float = Field(ge=0)
    avg_price: float = Field(ge=0)                  # prix moyen d'entrée

    # Allocation core / swing (optionnel)
    core_pct: float = Field(default=100.0, ge=0, le=100)
    swing_pct: float = Field(default=0.0, ge=0, le=100)
    min_core_qty: float = Field(default=0.0, ge=0)

    # Champs calculés (remplis au runtime par enrich())
    current_price: float = 0.0
    pnl_pct: float = 0.0                            # (current - avg) / avg * 100

    def enrich(self, current_price: float) -> "Position":
        """Recalcule PnL à partir du prix courant. Retourne self (mutable)."""
        self.current_price = current_price
        if self.avg_price > 0:
            self.pnl_pct = round(
                (current_price - self.avg_price) / self.avg_price * 100, 2
            )
        return self


class Portfolio(BaseModel):
    """Portefeuille complet : positions + cash."""

    cash_usdc: float = Field(default=0.0, ge=0)
    positions: List[Position] = Field(default_factory=list)

    # --- helpers ---

    def get(self, pair: str) -> Optional[Position]:
        """Retourne la position pour *pair* ou None."""
        pair_u = pair.upper()
        return next((p for p in self.positions if p.pair.upper() == pair_u), None)

    def enrich_all(self, prices: Dict[str, float]) -> "Portfolio":
        """Met à jour current_price / pnl_pct pour chaque position."""
        for pos in self.positions:
            price = prices.get(pos.pair.upper(), prices.get(pos.pair, 0.0))
            pos.enrich(price)
        return self

    @property
    def total_value(self) -> float:
        return self.cash_usdc + sum(
            p.quantity * p.current_price for p in self.positions
        )


# ------------------------------------------------------------------ #
#  Normalisation du JSON riche → format Portfolio
# ------------------------------------------------------------------ #

def _normalize_data(data: dict) -> dict:
    """Convertit le format riche de portfolio.json vers le schéma Portfolio.

    Transformations :
      - cash.available  →  cash_usdc
      - Champs non-Position (asset, risk_limits, decision_defaults…) ignorés
        grâce à Pydantic model_config extra='ignore'.
    """
    out: dict = {}

    # --- cash ---
    if "cash_usdc" in data:
        out["cash_usdc"] = data["cash_usdc"]
    elif isinstance(data.get("cash"), dict):
        out["cash_usdc"] = data["cash"].get("available", 0.0)
    elif isinstance(data.get("cash"), (int, float)):
        out["cash_usdc"] = data["cash"]

    # --- positions ---
    raw_positions = data.get("positions", [])
    out["positions"] = []
    for p in raw_positions:
        pos = {
            "pair": p.get("pair", ""),
            "quantity": p.get("quantity", 0),
            "avg_price": p.get("avg_price", 0),
        }
        # Champs optionnels (core/swing)
        if "core_pct" in p:
            pos["core_pct"] = p["core_pct"]
        if "swing_pct" in p:
            pos["swing_pct"] = p["swing_pct"]
        if "min_core_qty" in p:
            pos["min_core_qty"] = p["min_core_qty"]
        out["positions"].append(pos)

    return out


# ------------------------------------------------------------------ #
#  Chargement
# ------------------------------------------------------------------ #

def load_portfolio() -> "Portfolio":
    """Load portfolio from env or JSON file.

    Priority:
      1) PORTFOLIO_JSON (inline JSON content)
      2) PORTFOLIO_FILE (path to a .json file)
      3) Empty Portfolio()
    """
    raw = os.getenv("PORTFOLIO_JSON", "").strip()
    source: Optional[str] = None

    if raw:
        source = "env:PORTFOLIO_JSON"
    else:
        fpath = os.getenv("PORTFOLIO_FILE", "").strip()
        if fpath:
            path = pathlib.Path(os.path.expanduser(fpath)).resolve()
            if path.is_file():
                try:
                    raw = path.read_text(encoding="utf-8")
                    source = f"file:{path}"
                except OSError:
                    # If file can't be read, fall back to empty.
                    return Portfolio()

    if not raw:
        return Portfolio()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Bad JSON -> safe fallback
        return Portfolio()

    data = _normalize_data(data)

    try:
        p = Portfolio.model_validate(data)
        if source:
            print(f"[PORTFOLIO] Portfolio charg\u00e9 depuis {source} -- {len(p.positions)} positions, cash {p.cash_usdc:.2f} USDC")
        return p
    except ValidationError as exc:
        print(f"[WARN] Portfolio validation error: {exc}")
        return Portfolio()