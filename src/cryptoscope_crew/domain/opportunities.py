# src/cryptoscope_crew/domain/opportunities.py
"""Top Opportunities V1 — scoring déterministe, aucun LLM.

Prend en entrée :
  - context_by_tf  (dict issu de precompute_multi)
  - portfolio      (Portfolio)
  - decisions      (list[DecisionResult] produit par le Decision Engine)

Produit :
  - Top 3 Opportunity triées par score décroissant
  - Section Markdown prête à coller dans le rapport

Kinds d'opportunité (V1) :
  A) SELL_STRENGTH  – action == REDUCE_SWING
  B) BUY_PULLBACK   – close_4h ≤ 1% au-dessus de EMA20_4h, bias_4h Bull, RSI_4h ∈ [50, 55]
  C) DEFENSIVE      – action == DEFENSIVE
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from pydantic import BaseModel, Field

from cryptoscope_crew.domain.decision_engine import (
    Action,
    DecisionResult,
    _get_entry,
)

if TYPE_CHECKING:
    from cryptoscope_crew.domain.portfolio import Portfolio


# ------------------------------------------------------------------ #
#  Modèle
# ------------------------------------------------------------------ #

class Opportunity(BaseModel):
    """Une opportunité scorée, prête à afficher."""

    pair: str
    kind: str                                       # SELL_STRENGTH | BUY_PULLBACK | DEFENSIVE
    score: float = Field(ge=0, le=100)              # 0-100
    action_text: str = ""                            # phrase d'action lisible
    levels: Dict[str, str] = Field(default_factory=dict)  # reentry / risk
    suggested_sizes: Optional[str] = None            # taille suggérée (optionnel V1)


# ------------------------------------------------------------------ #
#  Scoring helpers
# ------------------------------------------------------------------ #

def _distance_to_ema20_4h_pct(ctx_4h: dict, pair: str) -> float:
    """Retourne la distance en % entre close_4h et EMA20_4h.

    Positif = close au-dessus ; négatif = close en dessous.
    """
    e = _get_entry(ctx_4h, pair)
    if e is None or e["ema_fast"] == 0:
        return 0.0
    return (e["close"] - e["ema_fast"]) / e["ema_fast"] * 100


def _atr_pct(ctx_4h: dict, pair: str) -> float:
    """ATR 4H en % du close — mesure de volatilité."""
    e = _get_entry(ctx_4h, pair)
    if e is None or e["close"] == 0:
        return 0.0
    return e["atr14"] / e["close"] * 100


def _score(
    *,
    rsi_1h: float,
    bias_4h_bull: bool,
    align_2of3: bool,
    distance_ema20_4h_pct: float,
    atr_pct: float,
    cash_pct: float,
    exposure_pct: float,
) -> float:
    """Calcul de score composite (0-100).

    Composantes :
      edge      – RSI 1H surchauffé (>70) + alignement multi-TF
      distance  – proximité du close à EMA20 4H (plus proche = meilleur)
      portfolio – cash disponible & faible exposition
      risk      – ATR en % (volatilité = risque)
    """
    edge = (25 if rsi_1h > 70 else 0) + (10 if align_2of3 else 0) + (5 if bias_4h_bull else 0)
    distance = max(0.0, 20 - abs(distance_ema20_4h_pct) * 10)
    portfolio_fit = min(20.0, cash_pct * 0.2 + (100 - exposure_pct) * 0.2)
    risk = atr_pct * 30

    raw = edge + distance + portfolio_fit - risk
    return round(max(0.0, min(100.0, raw)), 1)


# ------------------------------------------------------------------ #
#  Helpers portfolio
# ------------------------------------------------------------------ #

def _portfolio_metrics(portfolio: Optional["Portfolio"]) -> tuple[float, float]:
    """Retourne (cash_pct, exposure_pct) en 0-100, ou (50, 50) par défaut."""
    if portfolio is None or portfolio.total_value == 0:
        return 50.0, 50.0
    cash_pct = portfolio.cash_usdc / portfolio.total_value * 100
    exposure_pct = 100 - cash_pct
    return cash_pct, exposure_pct


# ------------------------------------------------------------------ #
#  Engine
# ------------------------------------------------------------------ #

class OpportunityEngine:
    """Moteur d'opportunités V1 — purement déterministe."""

    @staticmethod
    def build_top3(
        context_by_tf: Dict[str, dict],
        portfolio: Optional["Portfolio"],
        decisions: List[DecisionResult],
    ) -> List[Opportunity]:
        """Génère les opportunités candidates, score et retourne le top 3.

        Args:
            context_by_tf: données multi-TF (precompute_multi ou parse_md_tables)
            portfolio:     portefeuille chargé (ou None)
            decisions:     liste de DecisionResult issus du Decision Engine

        Returns:
            Liste de 0 à 3 Opportunity, triée par score décroissant.
        """
        ctx_4h = context_by_tf.get("4h", {})
        ctx_1h = context_by_tf.get("1h", {})

        cash_pct, exposure_pct = _portfolio_metrics(portfolio)

        candidates: list[Opportunity] = []

        for dec in decisions:
            pair = dec.pair

            # Données 4H
            e4h = _get_entry(ctx_4h, pair)
            bias_4h = dec.structure.get("4h", "?")
            bias_4h_bull = bias_4h == "Bull"
            rsi_4h = e4h["rsi14"] if e4h else 50.0

            # Données 1H
            e1h = _get_entry(ctx_1h, pair)
            rsi_1h = e1h["rsi14"] if e1h else 50.0

            # Alignement 2 sur 3 TF
            biases = [dec.structure.get(tf, "?") for tf in ("1d", "4h", "1h")]
            bull_count = sum(1 for b in biases if b == "Bull")
            bear_count = sum(1 for b in biases if b == "Bear")
            align_2of3 = bull_count >= 2 or bear_count >= 2

            dist_ema20 = _distance_to_ema20_4h_pct(ctx_4h, pair)
            atr_p = _atr_pct(ctx_4h, pair)

            score_args = dict(
                rsi_1h=rsi_1h,
                bias_4h_bull=bias_4h_bull,
                distance_ema20_4h_pct=dist_ema20,
                atr_pct=atr_p,
                cash_pct=cash_pct,
                exposure_pct=exposure_pct,
                align_2of3=align_2of3,
            )

            # --- A) SELL_STRENGTH ---
            if dec.suggested_action == Action.REDUCE_SWING:
                s = _score(**score_args)
                levels = {}
                if dec.reentry_zone:
                    levels["reentry"] = dec.reentry_zone
                if dec.invalidation:
                    levels["risk"] = dec.invalidation
                candidates.append(Opportunity(
                    pair=pair,
                    kind="SELL_STRENGTH",
                    score=s,
                    action_text=(
                        f"Alléger {dec.adjustment_pct or 15}% de la position swing. "
                        f"RSI 1H à {rsi_1h:.1f} — surchauffe dans un daily bear."
                    ),
                    levels=levels,
                    suggested_sizes=f"–{dec.adjustment_pct or 15}% swing",
                ))

            # --- B) BUY_PULLBACK ---
            elif (
                bias_4h_bull
                and 0 <= dist_ema20 <= 1.0
                and 50 <= rsi_4h <= 55
            ):
                s = _score(**score_args)
                ema20_str = f"{e4h['ema_fast']:.4f}" if e4h else "?"
                ema50_str = f"{e4h['ema_slow']:.4f}" if e4h else "?"
                candidates.append(Opportunity(
                    pair=pair,
                    kind="BUY_PULLBACK",
                    score=s,
                    action_text=(
                        f"Pullback vers EMA20 4H ({ema20_str}). "
                        f"RSI 4H neutre ({rsi_4h:.1f}) — bon point d'entrée potentiel."
                    ),
                    levels={
                        "reentry": f"EMA20 4H ({ema20_str})",
                        "risk": f"EMA50 4H ({ema50_str})",
                    },
                ))

            # --- C) DEFENSIVE ---
            elif dec.suggested_action == Action.DEFENSIVE:
                s = _score(**score_args)
                levels = {}
                if dec.invalidation:
                    levels["reactivation"] = dec.invalidation
                candidates.append(Opportunity(
                    pair=pair,
                    kind="DEFENSIVE",
                    score=s,
                    action_text=(
                        f"Structure baissière alignée. "
                        f"Conserver le cash et protéger les positions existantes."
                    ),
                    levels=levels,
                ))

        # Tri par score décroissant → top 3
        candidates.sort(key=lambda o: o.score, reverse=True)
        return candidates[:3]


# ------------------------------------------------------------------ #
#  Formatage Markdown
# ------------------------------------------------------------------ #

def opportunities_to_markdown(opps: List[Opportunity]) -> str:
    """Produit la section '## Top Opportunities (V1)' prête à coller."""
    if not opps:
        return "## Top Opportunities (V1)\n\nAucune opportunité identifiée."

    lines = ["## Top Opportunities (V1)", ""]
    for i, o in enumerate(opps, 1):
        lines.append(f"### {i}. {o.pair} — `{o.kind}`")
        lines.append(f"- **Score:** {o.score}/100")
        lines.append(f"- **Action:** {o.action_text}")
        for lbl, val in o.levels.items():
            lines.append(f"- **{lbl.capitalize()}:** {val}")
        if o.suggested_sizes:
            lines.append(f"- **Sizing:** {o.suggested_sizes}")
        lines.append("")

    return "\n".join(lines)
