from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import List


class Narrative(BaseModel):
    """Un narratif marché détecté par le researcher."""

    title: str
    summary: str
    tickers: List[str] = Field(default_factory=list)
    heat: int = Field(ge=1, le=5, description="Intensité du narratif (1-5)")
    sources: List[str] = Field(default_factory=list)

    @field_validator("sources", mode="before")
    @classmethod
    def _non_empty_sources(cls, v: list) -> list:
        """Retire les entrées vides / blanches de la liste de sources."""
        if not isinstance(v, list):
            return v
        return [s for s in v if isinstance(s, str) and s.strip()]


class NarrativeScanOutput(BaseModel):
    """Wrapper validé pour la sortie de la task narrative_scan."""

    narratives: List[Narrative] = Field(default_factory=list)