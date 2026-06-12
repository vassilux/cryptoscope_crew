# CryptoScope — Trading Bot

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
├── .agent/          # CrewAI agent definitions
├── tools/           # Tool functions (TA, price, sentiment, on-chain)
├── tasks/           # CrewAI tasks + Pydantic output schemas
├── models/          # Shared Pydantic schemas
├── data/            # OHLCV cache, CSV
├── config/          # settings.py, env loader
├── tests/           # pytest (mock all exchange calls)
└── .claude/skills/  # Domain skills — loaded on demand
```

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
- `.claude/skills/crewai-agent/`   → creating/modifying CrewAI agents & tasks
- `.claude/skills/ta-tool/`        → technical analysis tools (pandas-ta)
- `.claude/skills/ccxt-tool/`      → exchange connectivity (CCXT)
- `.claude/skills/pydantic-schema/`→ Pydantic output schemas
- `.claude/skills/sentiment-tool/` → Twitter/X + Serper sentiment tools
- `.claude/skills/kronos/`         → Kronos K-line forecasting integration

## Environment Variables
```
KRAKEN_API_KEY, KRAKEN_SECRET
BINANCE_API_KEY, BINANCE_SECRET
TWITTER_BEARER_TOKEN
SERPER_API_KEY
GLASSNODE_API_KEY
```
Use `python-dotenv`. Never commit `.env`.
