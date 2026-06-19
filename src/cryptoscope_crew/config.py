# src/cryptoscope_crew/config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv, find_dotenv

# Charge .env où qu'il soit (racine projet le plus souvent)
load_dotenv(find_dotenv(), override=False)

@dataclass
class LLMConfig:
    # On ignore OpenRouter pour l’instant
    provider: str = os.getenv("LLM_PROVIDER", "openai")  # "openai" only pour toi
    model: str = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")

@dataclass
class ExchangeConfig:
    name: str = os.getenv("DEFAULT_EXCHANGE", "binance")
    # Accepte les deux conventions de nommage (BINANCE_KEY historique, BINANCE_API_KEY doc)
    key: str | None = os.getenv("BINANCE_KEY") or os.getenv("BINANCE_API_KEY")
    secret: str | None = os.getenv("BINANCE_SECRET") or os.getenv("BINANCE_API_SECRET")
    # endpoints publics suffisent pour OHLCV; les clés peuvent rester vides

@dataclass
class SerperConfig:
    api_key: str | None = os.getenv("SERPER_API_KEY")

llm_cfg = LLMConfig()
ex_cfg = ExchangeConfig()
serper_cfg = SerperConfig()
