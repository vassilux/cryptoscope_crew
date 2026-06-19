<!--
  GENERATED FILE - DO NOT EDIT.
  Source of truth: Claude.md (repo root). Regenerate with ./sync-ai-skills.ps1.
  Shared project context for GitHub Copilot, mirrored verbatim from Claude.md.
-->
# CryptoScope — Trading Bot

> **Contexte partagé Claude ↔ Copilot.** Ce fichier `Claude.md` est la **source unique**
> du contexte projet. Claude le lit nativement ; pour GitHub Copilot il est **mirroré**
> vers `.github/copilot-instructions.md` (généré — ne pas éditer) par `sync-ai-skills`.
> Après toute édition de `Claude.md`, relancer `pwsh ./sync-ai-skills.ps1`.

## Overview
Multi-agent crypto trading bot (CrewAI + Python). Combines technical analysis,
on-chain data, and macro/political sentiment (Twitter/X + Serper) to generate
signals and execute orders on Kraken (perps) and Binance (spot).

## Monitored Assets
BTC, ETH, SOL, XRP, BNB

## Exchanges
- **Kraken** → Derivatives / Perpetuals (REST + WS)
- **Binance** → Spot accumulation (REST)

## Project Structure
```
cryptoscope/
├── src/cryptoscope_crew/      # Application code
│   ├── crew.py, main.py       # CrewAI orchestration + entrypoint
│   ├── config/                # agents.yaml, tasks.yaml
│   ├── config.py              # settings / env loader
│   ├── domain/                # business logic (decision/signal engine, portfolio, regime, schemas)
│   ├── ta/                    # technical analysis (pure, deterministic)
│   ├── risk/                  # risk management (pure, deterministic)
│   ├── market/                # exchange access (CCXT I/O)
│   ├── tools/                 # custom CrewAI tools
│   ├── forecast/              # Kronos K-line forecast (observation only)
│   ├── reporting/             # precompute tables + markdown
│   └── journal.py             # run logging / observability
├── tests/                     # pytest (mock all exchange calls)
├── runs/                      # per-run outputs (JSON + report.md)
├── reports/                   # market analysis reports
├── ai/skills/                 # Domain skills — SOURCE of truth (synced to .github/.claude)
├── docs/                      # Living reference docs (ARCHITECTURE.md, RUNS.md)
└── analyses/                  # Project context & evolution log (decisions, audits)
```

> **Architecture & conventions** (carte du repo, flow d'exécution, observabilité) :
> voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Analyses (journal de contexte)

`analyses/AAAA-MM-JJ_sujet.md` consigne les **décisions structurantes** et
**évolutions d'architecture/gouvernance** (≠ `runs/` = exécutions, ≠ `reports/` =
marché). Voir [analyses/README.md](analyses/README.md) pour la convention.
Créer une entrée à chaque réorganisation, nouvelle décision d'archi ou audit.

## Dev Commands
```bash
python main.py --mode paper             # paper trading
python main.py --agent ta --symbol BTC  # single agent
pytest tests/ -v                        # test suite
pip install -r requirements.txt
```

## ⚠️ Hard Rules (always active)

1. **TA tool-side only** — pandas-ta in tool functions, never LLM inference
2. **Prices via CCXT** — never hardcode levels, zones, or breakevens
3. **Pydantic on every task** — `output_pydantic=` required, fail loud not silent
4. **Sentiment = context, not signal** — always combined with TA + on-chain
5. **No open perps unmonitored** — close Kraken positions before offline windows

## Skills (auto-loaded on demand)

**Source unique de vérité** : `ai/skills/<catégorie>/<skill>/SKILL.md`.
Un script de sync aplatit les skills (par nom) vers `.github/skills/` (Copilot)
et `.claude/skills/` (Claude). Ces deux dossiers sont **générés** — ne pas les
éditer à la main.

```
ai/skills/
├── framework/
│   ├── crewai-agent/SKILL.md     → creating/modifying CrewAI agents & tasks
│   └── pydantic-schema/SKILL.md  → Pydantic output schemas
└── tools/
    ├── ta-tool/SKILL.md          → technical analysis tools (pandas-ta)
    ├── ccxt-tool/SKILL.md        → exchange connectivity (CCXT)
    ├── sentiment-tool/SKILL.md   → Twitter/X + Serper sentiment tools
    └── kronos/SKILL.md           → Kronos K-line forecasting integration
```

Après avoir ajouté, renommé ou édité un skill sous `ai/skills/`, relancer la sync :
```bash
pwsh ./sync-ai-skills.ps1   # Windows / cross-platform
./sync-ai-skills.sh         # macOS / Linux
```

## Kronos Forecasting (mode observation)

Foundation model K-line vendorisé dans `src/cryptoscope_crew/forecast/kronos_model/`
(MIT, https://github.com/shiyu-coder/Kronos). Wrapper: `forecast/kronos.py`.
- Section "Kronos Forecast" injectée dans le rapport + `kronos_forecast.json` par run
- **Observation seulement** : n'entre ni dans le score de conviction ni dans les décisions
- Env: `KRONOS_ENABLED` (1 défaut), `KRONOS_TIMEFRAME` (4h), `KRONOS_PRED_LEN` (24),
  `KRONOS_LOOKBACK` (400, max 512), `KRONOS_SAMPLE_COUNT` (1), `KRONOS_MODEL`
- CPU ~10 s/paire (Kronos-small) ; poids téléchargés de HuggingFace au 1er run

## Environment Variables
```
KRAKEN_API_KEY, KRAKEN_SECRET
BINANCE_KEY, BINANCE_SECRET   (alias acceptés: BINANCE_API_KEY/BINANCE_API_SECRET)
TWITTER_BEARER_TOKEN
SERPER_API_KEY
GLASSNODE_API_KEY
KRONOS_ENABLED=1
```
Use `python-dotenv`. Never commit `.env`.

