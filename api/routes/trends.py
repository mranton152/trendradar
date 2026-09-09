"""Поиск готовых трендов и источников в предрассчитанном индексе."""
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from api.models import (Components, DomainInfo, Evidence, ResolveRequest, ResolveResponse,
                        SeriesPoint, Source, Trend, TrendsRequest, TrendsResponse)
from api.store import Store

router = APIRouter(prefix="/api/v1", tags=["trends"])


def _store(request: Request) -> Store:
    return request.app.state.store


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _resolve_domain(query: str, store: Store) -> str | None:
    """Точный slug и простое включение до появления семантического поиска."""
    domains = store.domains()
    slug = _slug(query)
    if query in domains:
        return query
    if slug in domains:
        return slug
    matches = [domain for domain in domains if slug and (slug in domain or domain in slug)]
    return matches[0] if len(matches) == 1 else None


def _as_model(row: dict, store: Store, domain: str) -> Trend:
    documents = store.works(domain, list(row["top_doc_ids"]))
    return Trend(
        trend_id=row["trend_id"],
        rank=int(row["rank"]),
        title=row["label"],
        label_en=row["label"],
        aliases=list(row["aliases"] or []),
        emergence_score=float(row["emergence_score"]),
        components=Components(
            novelty=float(row["c_novelty"]),
            growth=float(row["c_growth"]),
            accel=float(row["c_accel"]),
            burst=float(row["c_burst"]),
            diffusion=float(row["c_diffusion"]),
        ),
        evidence=Evidence(
            first_mention=row["first_mention"],
            takeoff_year=row["takeoff_year"],
            series=[
                SeriesPoint(year=int(year), count=int(count), freq_per_million=float(freq))
                for year, count, freq in zip(
                    row["years"], row["counts"], row["freq_per_million"], strict=True)
            ],
            n_docs=int(row["n_docs"]),
            n_countries=int(row["n_countries"]),
            n_orgs=row["n_orgs"],
            n_patents=row["n_patents"],
        ),
        sources=[
            Source(
                doc_id=document["doc_id"],
                title=document["title"],
                url=document["url"],
                year=int(document["year"]),
                type=document["doc_type"],
            )
            for document in documents
        ],
        stage=row["stage"],
        confidence=row["confidence"],
    )


@router.post("/domains/resolve", response_model=ResolveResponse)
def resolve(body: ResolveRequest, request: Request) -> ResolveResponse:
    store = _store(request)
    resolved = _resolve_domain(body.query, store)
    domains = store.domains()
    return ResolveResponse(
        resolved=resolved,
        display_name=resolved,
        n_works=store.n_works(resolved) if resolved else 0,
        in_index=resolved is not None,
        alternatives=[domain for domain in domains if domain != resolved],
    )


@router.post("/trends", response_model=TrendsResponse)
def trends(body: TrendsRequest, request: Request) -> TrendsResponse:
    store = _store(request)
    domain = _resolve_domain(body.domain, store)
    rows = store.trends(domain, body.as_of, body.top_n) if domain else []
    if not rows:
        available = ", ".join(store.domains()) or "индекс пуст"
        raise HTTPException(404, f"Домен '{body.domain}' не найден. Доступно: {available}")
    return TrendsResponse(
        domain=DomainInfo(query=body.domain, resolved=domain, n_works=store.n_works(domain)),
        as_of=body.as_of,
        methodology_version=rows[0]["methodology_version"],
        generated_at=datetime.now(UTC),
        trends=[_as_model(row, store, domain) for row in rows],
    )


@router.get("/trends/{trend_id}", response_model=Trend)
def trend(trend_id: str, request: Request) -> Trend:
    store = _store(request)
    row = store.trend(trend_id)
    domain = store.trend_domain(trend_id)
    if row is None or domain is None:
        raise HTTPException(404, f"Тренд '{trend_id}' не найден")
    return _as_model(row, store, domain)
