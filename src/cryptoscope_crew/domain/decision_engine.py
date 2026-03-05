# src/cryptoscope_crew/domain/decision_engine.py
"""Moteur de décision déterministe V1 — aucun LLM impliqué.

Entrées possibles :
  A) context_by_tf  :  dict tel que produit par precompute_multi()
  B) tables MD      :  tech_table_md (1d) + tech_tables_md (4h, 1h)
     → parsés via parse_md_tables() pour reconstruire context_by_tf

Sorties :
  - DecisionResult (Pydantic)

Règles V1 :
  R1  1D Bear + 4H Bull + RSI 1H > 70   → REDUCE_SWING
  R2  1D Bear + 4H Bear                 → DEFENSIVE
  R3  1D Bull + 4H Bull                 → HOLD_OR_ADD
  R5  fallback                           → WAIT
"""
from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional

from pydantic import BaseModel, Field

from cryptoscope_crew.domain.portfolio import Position

if TYPE_CHECKING:
    from cryptoscope_crew.domain.portfolio import Portfolio


# ------------------------------------------------------------------ #
#  Types
# ------------------------------------------------------------------ #

class Action(str, Enum):
    REDUCE_SWING = "REDUCE_SWING"
    DEFENSIVE    = "DEFENSIVE"
    HOLD_OR_ADD  = "HOLD_OR_ADD"
    ADD_SMALL    = "ADD_SMALL"
    WAIT         = "WAIT"


class DecisionResult(BaseModel):
    pair: str
    suggested_action: Action
    adjustment_pct: Optional[float] = None          # % de la position à ajuster
    reentry_zone: Optional[str] = None              # niveau / zone textuel
    invalidation: Optional[str] = None              # condition d'invalidation
    watch_levels: Optional[Dict[str, str]] = None   # niveaux de surveillance (WAIT)
    distance_pct: Optional[float] = None            # distance close_4h vs EMA20_4H (%)
    rationale: str = ""                              # explication lisible
    rule_id: str = ""                                # R1, R2 … pour traçabilité

    # Structure multi-TF utilisée (debug)
    structure: Dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------------ #
#  Markdown table parser
# ------------------------------------------------------------------ #

def _parse_one_table(table_md: str) -> List[dict]:
    """Parse une table MD avec colonnes Pair|Close|EMA20|EMA50|RSI14|ATR14|Bias…

    Retourne une liste de dicts normalisés par pair :
        {"pair": "BTC/USDC", "close": 95000.0, "ema_fast": …, "ema_slow": …,
         "rsi14": 42.0, "atr14": 2000.0, "bias": "Bear"}
    """
    results = []
    lines = [l.strip() for l in table_md.splitlines() if l.strip()]

    # Cherche la ligne header
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("|") and "Pair" in line and "Close" in line:
            header_idx = i
            break
    if header_idx is None:
        return results

    headers = [re.sub(r"\*+", "", h).strip().lower() for h in lines[header_idx].split("|")]
    # headers: ['', 'pair', 'close', 'ema20', 'ema50', 'rsi14', 'atr14', 'bias', ...]

    def col_idx(name: str) -> int:
        try:
            return headers.index(name)
        except ValueError:
            return -1

    i_pair  = col_idx("pair")
    i_close = col_idx("close")
    i_ema20 = col_idx("ema20")
    i_ema50 = col_idx("ema50")
    i_rsi   = col_idx("rsi14")
    i_atr   = col_idx("atr14")
    i_bias  = col_idx("bias")

    if i_pair < 0 or i_close < 0:
        return results

    # Parse data rows (skip header + separator)
    for line in lines[header_idx + 1:]:
        if not line.startswith("|"):
            continue
        # Skip separator line (|------|...)
        if re.match(r"^\|[\s\-|]+$", line):
            continue
        cells = [c.strip() for c in line.split("|")]

        def cell(idx: int) -> str:
            if idx < 0 or idx >= len(cells):
                return ""
            return cells[idx]

        # Clean pair name: remove **bold** markers
        raw_pair = re.sub(r"\*+", "", cell(i_pair)).strip()
        if not raw_pair or "/" not in raw_pair:
            continue

        def to_float(idx: int, default: float = 0.0) -> float:
            v = cell(idx)
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        bias_str = cell(i_bias).strip().capitalize() if i_bias >= 0 else ""
        ema_fast = to_float(i_ema20)
        ema_slow = to_float(i_ema50)
        if not bias_str:
            bias_str = "Bull" if ema_fast > ema_slow else "Bear"

        results.append({
            "pair":     raw_pair,
            "close":    to_float(i_close),
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi14":    to_float(i_rsi, 50.0),
            "atr14":    to_float(i_atr),
            "bias":     bias_str,
        })
    return results


def parse_md_tables(
    tech_table_md: str,
    tech_tables_md: str,
    main_tf: str = "1d",
) -> Dict[str, dict]:
    """Reconstruit un context_by_tf à partir des tables MD du rapport.

    Args:
        tech_table_md:  la table du TF principal (1d par défaut)
        tech_tables_md: les blocs secondaires (### Table 4h / ### Table 1h …)
        main_tf:        le timeframe principal

    Returns:
        {"1d": {"pairs": [...]}, "4h": {"pairs": [...]}, ...}
    """
    context_by_tf: Dict[str, dict] = {}

    # --- Main TF ---
    main_pairs = _parse_one_table(tech_table_md)
    if main_pairs:
        context_by_tf[main_tf] = {"timeframe": main_tf, "pairs": main_pairs}

    # --- Secondary TFs ---
    # Format: ### Table 4h\n-----\n<table>\n-----
    pattern = r"###\s+Table\s+(\S+)\s*\n-{3,}\n(.*?)\n-{3,}"
    for m in re.finditer(pattern, tech_tables_md, re.DOTALL):
        tf_name = m.group(1).strip().lower()
        block = m.group(2).strip()
        pairs = _parse_one_table(block)
        if pairs:
            context_by_tf[tf_name] = {"timeframe": tf_name, "pairs": pairs}

    return context_by_tf


# ------------------------------------------------------------------ #
#  Helpers internes (accès context_by_tf)
# ------------------------------------------------------------------ #

def _get_entry(ctx_tf: dict, pair: str) -> Optional[dict]:
    """Trouve l'entrée d'une paire dans un contexte mono-TF."""
    return next((p for p in ctx_tf.get("pairs", []) if p["pair"] == pair), None)

def _bias(ctx_tf: dict, pair: str) -> str:
    e = _get_entry(ctx_tf, pair)
    if e is None:
        return "?"
    raw = e.get("bias", "Bull" if e["ema_fast"] > e["ema_slow"] else "Bear")
    return raw.capitalize()  # "bear" → "Bear", "BULL" → "Bull"

def _rsi(ctx_tf: dict, pair: str) -> float:
    e = _get_entry(ctx_tf, pair)
    return e["rsi14"] if e else 50.0

def _ema(ctx_tf: dict, pair: str, which: str = "fast") -> float:
    e = _get_entry(ctx_tf, pair)
    if e is None:
        return 0.0
    return e["ema_fast"] if which == "fast" else e["ema_slow"]


# ------------------------------------------------------------------ #
#  Moteur de décision V1
# ------------------------------------------------------------------ #

def decide(
    pair: str,
    context_by_tf: Dict[str, dict],
    position: Optional[Position] = None,
) -> DecisionResult:
    """Applique les règles déterministes V1 et retourne un DecisionResult.

    context_by_tf peut être construit soit par precompute_multi(),
    soit par parse_md_tables().
    """

    # --- récupère les biais & RSI par TF disponible ---
    b1d = _bias(context_by_tf["1d"], pair) if "1d" in context_by_tf else "?"
    b4h = _bias(context_by_tf["4h"], pair) if "4h" in context_by_tf else "?"
    b1h = _bias(context_by_tf["1h"], pair) if "1h" in context_by_tf else "?"

    rsi_1h = _rsi(context_by_tf["1h"], pair) if "1h" in context_by_tf else 50.0

    ema20_4h = _ema(context_by_tf["4h"], pair, "fast") if "4h" in context_by_tf else 0.0
    ema50_4h = _ema(context_by_tf["4h"], pair, "slow") if "4h" in context_by_tf else 0.0

    structure = {"1d": b1d, "4h": b4h, "1h": b1h}
    base = dict(pair=pair, structure=structure)

    # --- distance % entre close 4H et EMA20 4H ---
    close_4h = 0.0
    if "4h" in context_by_tf:
        e4h = _get_entry(context_by_tf["4h"], pair)
        if e4h:
            close_4h = e4h["close"]
    dist_pct = ((close_4h - ema20_4h) / ema20_4h * 100) if ema20_4h else 0.0

    # --- R1 : rebond court terme dans daily bear, surchauffe 1H ---
    if b1d == "Bear" and b4h == "Bull" and rsi_1h > 70:
        adj = 20 if dist_pct > 3 else 10
        return DecisionResult(
            **base,
            suggested_action=Action.REDUCE_SWING,
            adjustment_pct=adj,
            distance_pct=round(dist_pct, 2),
            reentry_zone=f"EMA20 4H ({ema20_4h:.4f})",
            invalidation=f"Clôture 4H sous EMA50 ({ema50_4h:.4f})",
            rationale=(
                f"Rebond court terme (4H Bull) dans un daily bear. "
                f"RSI 1H surchauffé ({rsi_1h:.1f} > 70). "
                f"Distance close/EMA20 4H : {dist_pct:+.2f}%. "
                f"Allégement swing recommandé, re-entry sur repli EMA20 4H."
            ),
            rule_id="R1",
        )

    # --- R2 : alignement baissier 1D + 4H ---
    if b1d == "Bear" and b4h == "Bear":
        return DecisionResult(
            **base,
            suggested_action=Action.DEFENSIVE,
            adjustment_pct=None,
            reentry_zone=None,
            invalidation=f"Reclaim EMA50 4H ({ema50_4h:.4f}) + RSI 4H > 55",
            rationale=(
                f"Alignement baissier 1D/4H. "
                f"Pas de setup long tant que le 4H ne reclaim pas EMA50. "
                f"Conserver le cash, protéger les positions."
            ),
            rule_id="R2",
        )

    # --- R3 : alignement haussier 1D + 4H ---
    if b1d == "Bull" and b4h == "Bull":
        return DecisionResult(
            **base,
            suggested_action=Action.HOLD_OR_ADD,
            adjustment_pct=None,
            reentry_zone=f"Pullback EMA20 4H ({ema20_4h:.4f})",
            invalidation=f"Clôture 1D sous EMA50 1D",
            rationale=(
                f"Structure haussière alignée 1D/4H. "
                f"Maintenir les positions, renforcer sur pullback EMA20 4H."
            ),
            rule_id="R3",
        )

    # --- R5 : fallback ---
    watch = None
    if ema20_4h:
        watch = {
            "reentry_zone": f"EMA20 4H ({ema20_4h:.4f})",
            "risk_line": f"EMA50 4H ({ema50_4h:.4f}) — clôture 4H dessous = risque",
        }
    return DecisionResult(
        **base,
        suggested_action=Action.WAIT,
        watch_levels=watch,
        rationale="Aucune règle déclenchée. Attendre un setup clair.",
        rule_id="R5",
    )


# ------------------------------------------------------------------ #
#  Batch sur toutes les paires
# ------------------------------------------------------------------ #

def decide_all(
    pairs: List[str],
    context_by_tf: Optional[Dict[str, dict]] = None,
    portfolio: Optional["Portfolio"] = None,
    *,
    tech_table_md: str = "",
    tech_tables_md: str = "",
    main_tf: str = "1d",
) -> List[DecisionResult]:
    """Applique decide() sur chaque paire.

    Accepte *soit* un context_by_tf pré-construit, *soit* les tables MD
    brutes (tech_table_md + tech_tables_md). Si les deux sont fournis,
    context_by_tf est prioritaire.
    """
    from cryptoscope_crew.domain.portfolio import Portfolio

    if context_by_tf is None:
        context_by_tf = parse_md_tables(tech_table_md, tech_tables_md, main_tf)

    results = []
    for pair in pairs:
        pos = portfolio.get(pair) if portfolio else None
        results.append(decide(pair, context_by_tf, pos))
    return results


# ------------------------------------------------------------------ #
#  Formatage Markdown
# ------------------------------------------------------------------ #

def decisions_to_markdown(decisions: List[DecisionResult]) -> str:
    """Produit la section '## Decision Summary (V1)' prête à coller dans le rapport."""
    lines = ["## Decision Summary (V1)", ""]
    for d in decisions:
        struct = " / ".join(f"{tf} {b}" for tf, b in d.structure.items() if b != "?")
        lines.append(f"### {d.pair}")
        lines.append(f"- **Market Structure:** {struct}")
        lines.append(f"- **Suggested Action:** `{d.suggested_action.value}`")
        if d.adjustment_pct is not None:
            lines.append(f"- **Adjustment:** {d.adjustment_pct}%")
        if d.distance_pct is not None:
            lines.append(f"- **Distance close/EMA20 4H:** {d.distance_pct:+.2f}%")
        lines.append(f"- **Reason:** {d.rationale}")
        if d.reentry_zone:
            lines.append(f"- **Re-entry zone:** {d.reentry_zone}")
        if d.invalidation and d.suggested_action == Action.DEFENSIVE:
            lines.append(f"- **Reactivation condition:** {d.invalidation}")
        elif d.invalidation:
            lines.append(f"- **Invalidation:** {d.invalidation}")
        if d.watch_levels:
            lines.append(f"- **Watch levels:**")
            lines.append(f"  - Re-entry zone: {d.watch_levels['reentry_zone']}")
            lines.append(f"  - Risk line: {d.watch_levels['risk_line']}")
        lines.append(f"- _Rule: {d.rule_id}_")
        lines.append("")
    return "\n".join(lines)