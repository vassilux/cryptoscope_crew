---
name: sentiment-tool
description: >
  Use this skill when writing or modifying sentiment analysis tools that
  use Twitter/X or Serper (Google Search). Triggers on: 'sentiment',
  'Twitter', 'X API', 'Serper', 'news', 'macro', 'political', 'social media',
  'search news', 'tweet search', 'sentiment score'.
---

# Sentiment Analysis Tools — CryptoScope

## Architecture
Sentiment is **macro context**, not a standalone trading signal.
Always combined with TA + on-chain before generating a decision.

```
Twitter/X search  ──┐
Serper news search ─┼──→ SentimentOutput (score + events) ──→ signal_aggregator
Google Trends      ─┘
```

## Twitter/X Tool

```python
# tools/sentiment_tools.py
import os
import tweepy
from crewai.tools import tool
from pydantic import BaseModel
from models.signals import SentimentOutput

def _get_twitter_client() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
        wait_on_rate_limit=True,
    )

CRYPTO_ACCOUNTS = [
    "michael_saylor", "CathieDWood", "elonmusk",
    "federalreserve", "SecYellen",  # macro/political
]

@tool("twitter_sentiment_tool")
def twitter_sentiment_tool(symbol: str, query: str = "", max_results: int = 50) -> SentimentOutput:
    """
    Search recent tweets about a crypto asset or macro event.
    Scores sentiment from -1 (bearish) to +1 (bullish).
    Symbol examples: 'BTC', 'ETH', 'crypto regulation'.
    """
    client = _get_twitter_client()

    search_query = query or f"#{symbol} OR ${symbol} -is:retweet lang:en"
    tweets = client.search_recent_tweets(
        query=search_query,
        max_results=max_results,
        tweet_fields=["text", "public_metrics", "created_at"],
    )

    if not tweets.data:
        return SentimentOutput(
            symbol=symbol, sentiment="neutral", score=0.0,
            key_events=[], sources_count=0
        )

    # Simple keyword scoring — replace with fine-tuned model if needed
    score = _score_tweets([t.text for t in tweets.data])
    key_events = _extract_key_events([t.text for t in tweets.data])

    sentiment = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"

    return SentimentOutput(
        symbol=symbol,
        sentiment=sentiment,
        score=round(score, 3),
        key_events=key_events[:5],
        sources_count=len(tweets.data),
    )
```

## Serper (Google Search) Tool

```python
import requests

@tool("serper_news_tool")
def serper_news_tool(query: str, num_results: int = 10) -> dict:
    """
    Search Google News for macro/regulatory events affecting crypto markets.
    Use for: FOMC decisions, regulatory news, ETF flows, exchange incidents.
    """
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY"),
        "Content-Type": "application/json",
    }
    payload = {"q": query, "type": "news", "num": num_results}
    response = requests.post("https://google.serper.dev/news", json=payload, headers=headers)
    response.raise_for_status()

    data = response.json()
    news_items = [
        {"title": item["title"], "snippet": item["snippet"], "date": item.get("date", "")}
        for item in data.get("news", [])
    ]
    return {"query": query, "results": news_items, "count": len(news_items)}
```

## Scoring Helpers

```python
BULLISH_KEYWORDS = ["buy", "bull", "moon", "breakout", "ETF approved", "adoption",
                    "accumulate", "institutional", "halving", "all-time high"]
BEARISH_KEYWORDS = ["sell", "bear", "crash", "regulation", "ban", "hack",
                    "SEC", "lawsuit", "liquidation", "FUD", "dump"]

def _score_tweets(texts: list[str]) -> float:
    """Returns score in [-1, +1]. Replace with ML model for production."""
    total = 0
    for text in texts:
        text_lower = text.lower()
        bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
        bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text_lower)
        total += (bull - bear)
    return max(-1.0, min(1.0, total / max(len(texts), 1) / 3))

def _extract_key_events(texts: list[str]) -> list[str]:
    """Extract mentions of key macro events from tweet texts."""
    events = []
    triggers = ["FOMC", "Fed rate", "ETF", "SEC", "regulation", "halving",
                "CLARITY Act", "inflation", "CPI", "interest rate"]
    for text in texts:
        for trigger in triggers:
            if trigger.lower() in text.lower() and text not in events:
                events.append(text[:120])
    return events
```

## Key Macro Triggers to Monitor

```python
MACRO_QUERIES = {
    "fed_policy":   "Federal Reserve interest rate decision crypto",
    "regulation":   "crypto regulation SEC CFTC CLARITY Act 2026",
    "etf_flows":    "Bitcoin ETF inflows outflows BlackRock Fidelity",
    "btc_specific": "Bitcoin mining production halving on-chain",
}
```

## Anti-patterns

```python
# WRONG — sentiment used as direct trigger
if sentiment.score > 0.5:
    place_order("BTC/USDT", "buy", ...)  # ignores TA and on-chain

# WRONG — no rate limit handling
client.search_recent_tweets(...)  # will 429 in burst — use wait_on_rate_limit=True

# WRONG — raw tweet text passed to LLM for scoring
Task(description=f"Score the sentiment of these tweets: {all_tweets_text}")
# → use _score_tweets() tool-side, pass only the score
```
