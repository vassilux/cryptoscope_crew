# cryptoscope_crew

[![CI](https://github.com/vassilux/cryptoscope_crew/actions/workflows/ci.yml/badge.svg)](https://github.com/vassilux/cryptoscope_crew/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![CrewAI](https://img.shields.io/badge/Agentic-CrewAI-5a67d8)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Projet educatif & de recherche** -- assistant de decision de portefeuille **SPOT-ONLY** pour le marche crypto.
> Combine analyse technique multi-timeframes, detection de regime de marche, moteur de decision deterministe et rapports Markdown automatises.
> :warning: _Aucune recommandation d'investissement. Utilisation a vos risques._

---

## Identite

| | |
|---|---|
| **Nom** | `cryptoscope_crew` |
| **Version** | 0.1.0 |
| **Langage** | Python 3.12, framework **CrewAI** (agents IA sequentiels) |
| **Licence** | MIT |
| **Taille** | 24 fichiers source (~3 130 lignes), 3 fichiers de tests (76 tests, tous verts) |

---

## Architecture en couches

```
+--------------------------------------------------------------+
|                     CrewAI Crew (crew.py)                     |
|  3 agents LLM : Researcher -> Technician -> Reporting Analyst |
+---------------+-----------------------------+-----------------+
                | inputs pre-calcules          | rapport .md
+---------------v-----------------------------v-----------------+
|                   Domain Layer (pure deterministe)             |
|                                                               |
|  market/exchange.py    OHLCV via CCXT (Kraken, Binance...)    |
|  ta/ema_rsi.py         EMA20, EMA50, EMA200, RSI14, ATR14    |
|  reporting/precompute  Tables TA, triggers, signaux prets     |
|                                                               |
|  domain/regime.py          Regime LOCAL   (EMA20/EMA50)       |
|  domain/macro_regime.py    Regime MACRO   (EMA50/EMA200, BTC) |
|  domain/signal_engine.py   SignalEngine multi-TF              |
|  domain/decision_engine.py Moteur de decision (regles R1-R5)  |
|  domain/portfolio.py       Portfolio + RiskLimits             |
|  domain/portfolio_strategy.py  Strategie SPOT-ONLY finale    |
|  domain/opportunities.py  Top 3 opportunites scorees          |
|  risk/risk.py              Position sizing                    |
+---------------------------------------------------------------+
```

---

## Modules cles

| Module | Role |
|---|---|
| **regime.py** | Regime local par paire : EMA20/EMA50 -> BULL / BEAR / RANGE |
| **macro_regime.py** | Regime macro BTC-led : EMA50/EMA200 sur 1D -> BULL / BEAR / TRANSITION. Hierarchie : BTC (primaire), ETH (secondaire, clamping leger), XRP+ (opportuniste, clamping strict) |
| **signal_engine.py** | Classification multi-TF : ALIGNED_BULL, ALIGNED_BEAR, SELL_BOUNCE, BUY_DIP, BULL_WEAKENING. Enrichissement environnement avec macro BTC |
| **decision_engine.py** | 5 regles deterministes (R1->R5) : REDUCE_SWING, DEFENSIVE, HOLD_OR_ADD, REBUILD_LADDER, WAIT |
| **portfolio_strategy.py** | Couche finale SPOT-ONLY : combine regime local + macro + signaux + decisions + contraintes de risque. Actions : ADD_SMALL, HOLD, WAIT, REDUCE_SWING, DEFENSIVE, REBUILD_LADDER |
| **portfolio.py** | Modele Pydantic : positions (core/swing split, min_core_qty), cash USDC, RiskLimits (cash_min_pct, max_exposure_pct), DecisionDefaults |
| **opportunities.py** | Scoring deterministe : SELL_STRENGTH, BUY_PULLBACK, DEFENSIVE -> Top 3 |

---

## Pipeline d'execution

1. **Fetch OHLCV** via CCXT -> DataFrame pandas
2. **Precompute** : EMA20/50/200, RSI14, ATR14, tables Markdown, triggers
3. **Regime local** (EMA20/EMA50) + **Regime macro** (EMA50/EMA200, BTC-led)
4. **SignalEngine** : classification multi-TF + enrichissement macro
5. **DecisionEngine** : regles R1-R5 deterministes
6. **PortfolioStrategyEngine** : strategie SPOT-ONLY avec gating macro (BTC BEAR bloque ADD_SMALL et REBUILD_LADDER)
7. **OpportunityEngine** : Top 3 opportunites scorees
8. **CrewAI agents** (LLM) : Researcher (catalyseurs + narratifs web), Technician (validation TA), Analyst (rapport Markdown final)
9. **Rapport Markdown** horodate avec : Points cles, Configuration technique, Synthese multi-TF, Signaux prets a tirer, Triggers, Narratifs, Risques, Watchlist

---

## Contraintes de risque (SPOT-ONLY)

- Jamais vendre en dessous de `min_core_qty`
- Toujours garder `cash_min_pct` (defaut 20%) en USDC
- Reductions touchent uniquement la portion swing
- Chaque step de ladder respecte `max_single_order_cash_pct` (defaut 12%)
- Macro BEAR BTC -> bloque les achats (ADD_SMALL -> HOLD, REBUILD_LADDER -> WAIT)

---

## Stack technique

| Composant | Technologie |
|---|---|
| Runtime | Python 3.12 |
| Framework agents | CrewAI 0.177+ |
| LLMs | GPT-5, GPT-4o-mini, GPT-4.1-mini (fallback) |
| Donnees marche | CCXT (multi-exchange) |
| Calcul TA | pandas + numpy (fallback Rust optionnel) |
| Modeles | Pydantic v2 |
| Recherche web | Serper API |
| Tests | pytest (76 tests, 0 echec) |
| CI | GitHub Actions |

---

## Prerequis

- Python **3.12**
- Cles API :
  - `OPENAI_API_KEY` (modeles GPT-5, GPT-4o-mini, etc.)
  - `SERPER_API_KEY` (recherche d'actus pour narratifs)
- (Optionnel) `uv` pour la gestion d'environnement rapide

---

## Configuration

Creez un fichier `.env` a la racine (ne pas committer vos vraies cles) :
```ini
# Langue & fuseau
LANG=fr
TZ=Europe/Paris

# Marche
PAIRS=BTC/USDC, ETH/USDC, XRP/USDC
TIMEFRAMES=1d,4h,1h
TIMEFRAME=1d
LOOKBACK=450

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL_RESEARCHER=gpt-5
OPENAI_MODEL_TECHNICIAN=gpt-4o-mini
OPENAI_MODEL_ANALYST=gpt-4o-mini

# Recherche (narratifs)
SERPER_API_KEY=serper-...

# Sortie
REPORT_DIR=reports
```

---

## Installation & lancement

```bash
# Cloner
git clone https://github.com/vassilux/cryptoscope_crew.git
cd cryptoscope_crew

# Environnement virtuel
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .\.venv\Scripts\activate  # Windows

# Dependances
pip install -e .

# Lancer le crew
cryptoscope_crew
# ou
python -m cryptoscope_crew.main
```

---

## Tests

```bash
pytest tests/ -v
# 76 tests, 0 echec
```

---

## Structure du projet

```
cryptoscope_crew/
+-- src/cryptoscope_crew/
|   +-- crew.py                    # Crew CrewAI, agents & tasks, injection inputs
|   +-- main.py                    # Point d'entree CLI
|   +-- config.py                  # Configuration exchange
|   +-- journal.py                 # Sauvegarde outputs intermediaires
|   +-- config/
|   |   +-- agents.yaml            # Roles des 3 agents
|   |   +-- tasks.yaml             # 4 taches (scan_market, narrative_scan, tech_review, reporting_task)
|   +-- domain/
|   |   +-- regime.py              # Regime local EMA20/EMA50
|   |   +-- macro_regime.py        # Regime macro BTC-led EMA50/EMA200
|   |   +-- signal_engine.py       # Classification multi-TF
|   |   +-- decision_engine.py     # Regles R1-R5
|   |   +-- portfolio.py           # Portfolio + RiskLimits + DecisionDefaults
|   |   +-- portfolio_strategy.py  # Strategie SPOT-ONLY finale
|   |   +-- opportunities.py       # Top 3 opportunites
|   |   +-- schemas.py             # Schemas Pydantic partages
|   +-- market/
|   |   +-- exchange.py            # Fetch OHLCV via CCXT
|   +-- reporting/
|   |   +-- precompute.py          # Pre-calcul TA, tables MD, triggers
|   +-- ta/
|   |   +-- ema_rsi.py             # EMA, RSI (pandas, fallback Rust)
|   +-- risk/
|       +-- risk.py                # Position sizing
+-- tests/
|   +-- test_decisions.py          # 30 tests decision engine
|   +-- test_opportunities.py      # 10 tests opportunities
|   +-- test_portfolio_strategy.py # 36 tests regime + signal + strategy
+-- reports/                       # Rapports generes
+-- runs/                          # Outputs intermediaires par run
+-- portfolio.json                 # Portefeuille reel (gitignored)
+-- pyproject.toml
+-- Makefile
+-- .env                           # Cles API (gitignored)
```

---

## Licence

Ce projet est publie sous licence **MIT**. Voir le fichier `LICENSE`.
