from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List


def _is_valid_source_url(url: str) -> bool:
    """Une source doit être une URL http(s) avec un domaine plausible."""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and "." in parsed.netloc


class Narrative(BaseModel):
    """Un narratif marché détecté par le researcher."""

    title: str
    summary: str
    tickers: List[str] = Field(default_factory=list)
    heat: int = Field(ge=1, le=5, description="Intensité du narratif (1-5)")
    sources: List[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _valid_sources(cls, v: list) -> list:
        """Garde uniquement les URLs http(s) valides (anti-hallucination)."""
        if not isinstance(v, list):
            return v
        return [s.strip() for s in v if isinstance(s, str) and _is_valid_source_url(s)]


class NarrativeScanOutput(BaseModel):
    """Wrapper validé pour la sortie de la task narrative_scan."""

    narratives: List[Narrative] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dedupe_and_require_sources(self) -> "NarrativeScanOutput":
        """Une même URL ne peut sourcer qu'un narratif (le premier listé) ;
        un narratif sans source valide restante est écarté."""
        seen: set[str] = set()
        kept: List[Narrative] = []
        for n in self.narratives:
            uniq = [s for s in n.sources if s not in seen]
            seen.update(uniq)
            n.sources = uniq
            if uniq:
                kept.append(n)
        self.narratives = kept
        return self
