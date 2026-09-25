"""Модели публичного API из contracts/api.openapi.yaml."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DomainInfo(BaseModel):
    query: str
    resolved: str
    n_works: int = Field(ge=0)


class Components(BaseModel):
    novelty: float
    growth: float
    accel: float
    burst: float
    diffusion: float


class SeriesPoint(BaseModel):
    year: int
    count: int
    freq_per_million: float


class Evidence(BaseModel):
    first_mention: int | None = None
    takeoff_year: int | None = None
    series: list[SeriesPoint]
    n_docs: int = Field(ge=0)
    n_countries: int = Field(ge=0)
    n_orgs: int | None = Field(default=None, ge=0)
    n_patents: int | None = Field(default=None, ge=0)


class Source(BaseModel):
    doc_id: str
    title: str
    url: str
    year: int
    type: str
    date: str | None = None
    source_type: str | None = None
    lang: str | None = None
    trust_level: Literal["trusted", "indicator", "unknown"] | None = None


class Stats(BaseModel):
    n_sources_polled: int = Field(ge=0)
    n_candidates: int = Field(ge=0)
    n_rejected: int = Field(ge=0)
    n_confident: int = Field(ge=0)


class RejectedCandidate(BaseModel):
    label: str
    reason: str
    n_docs: int = Field(ge=0)


class Motivation(BaseModel):
    problem: str
    advantage: str
    sources: list[str] = Field(default_factory=list)


class CaseExample(BaseModel):
    type: Literal["research", "company"]
    name: str
    description: str
    source: str | None = None


class Backtest(BaseModel):
    at_cutoff: int
    peak_after: int
    growth_x: float


class Trend(BaseModel):
    trend_id: str
    rank: int = Field(ge=1)
    title: str
    label_en: str
    aliases: list[str] = Field(default_factory=list)
    emergence_score: float
    components: Components
    evidence: Evidence
    motivation: Motivation | None = None
    case_example: CaseExample | None = None
    sources: list[Source] = Field(default_factory=list)
    stage: Literal["emerging", "early_growth", "scaling"]
    confidence: Literal["high", "medium", "low"]
    confidence_pct: int = Field(ge=0, le=100)
    series_granularity: Literal["year", "month"] = "year"
    backtest: Backtest | None = None


class TrendsRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=200)
    top_n: int = Field(default=15, ge=1, le=50)
    as_of: int = Field(default=2026, ge=1900, le=2100)
    lang: Literal["ru", "en"] = "ru"


class TrendsResponse(BaseModel):
    domain: DomainInfo
    as_of: int
    methodology_version: str
    generated_at: datetime
    stats: Stats
    trends: list[Trend]
    rejected: list[RejectedCandidate] = Field(default_factory=list)


class ResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ResolveResponse(BaseModel):
    resolved: str | None = None
    display_name: str | None = None
    n_works: int = Field(default=0, ge=0)
    in_index: bool
    alternatives: list[str] = Field(default_factory=list)


class LiveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    budget_s: int = Field(default=180, ge=30, le=300)


class LiveAccepted(BaseModel):
    job_id: str
    domain: str


class LiveStatus(BaseModel):
    status: Literal["collecting", "candidates", "scoring", "cards", "done", "failed"]
    stage_text: str
    n_docs: int = Field(default=0, ge=0)
    n_sources_polled: int = Field(default=0, ge=0)
    n_candidates: int = Field(default=0, ge=0)
    elapsed_s: float = Field(default=0, ge=0)
    domain: str | None = None
    error: str | None = None
    no_trends: bool = False
