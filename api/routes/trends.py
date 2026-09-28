"""Поиск готовых трендов и источников в предрассчитанном индексе."""
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from api.models import (
    Backtest,
    CaseExample,
    Components,
    DomainInfo,
    Evidence,
    Motivation,
    RejectedCandidate,
    ResolveRequest,
    ResolveResponse,
    SeriesPoint,
    Source,
    Stats,
    Trend,
    TrendsRequest,
    TrendsResponse,
)
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
    card = store.card(domain, row["trend_id"])
    motivation = None
    case_example = None
    backtest = None
    if card is not None:
        problem = card["problem"]
        advantage = card["advantage"]
        if problem or advantage:
            motivation = Motivation(
                problem=problem,
                advantage=advantage,
                sources=list(dict.fromkeys(card["problem_docs"] + card["advantage_docs"])),
            )
        if card["case_name"] and card["case_text"]:
            case_example = CaseExample(
                type=card["case_type"],
                name=card["case_name"],
                description=card["case_text"],
                source=card["case_docs"][0] if card["case_docs"] else None,
            )
    backtest_values = (
        row.get("bt_at_cutoff"), row.get("bt_peak_after"), row.get("bt_growth_x")
    )
    if all(value is not None for value in backtest_values):
        backtest = Backtest(
            at_cutoff=int(backtest_values[0]),
            peak_after=int(backtest_values[1]),
            growth_x=float(backtest_values[2]),
        )
    return Trend(
        trend_id=row["trend_id"],
        rank=int(row["rank"]),
        # ТЗ: аналитическая выдача на русском. Русское название — из карточки,
        # английский термин остаётся в label_en: по нему ищут источники.
        title=(card or {}).get("title_ru") or row["label"],
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
                date=document.get("date"),
                source_type=document.get("source_type") or document["doc_type"],
                lang=document.get("lang"),
                trust_level=document.get("trust_level"),
            )
            for document in documents
        ],
        motivation=motivation,
        case_example=case_example,
        stage=row["stage"],
        confidence=row["confidence"],
        confidence_pct=round(float(row["emergence_score"]) * 100),
        series_granularity=row.get("series_granularity") or "year",
        backtest=backtest,
    )


ИМЕНА_ИНДЕКСОВ = {"golden": "Искусственный интеллект", "ai-full": "Искусственный интеллект"}


def _title(store: Store, domain: str) -> tuple[str, bool]:
    """Заголовок направления и признак живого запроса."""
    if domain.startswith("live-"):
        return str(store.meta(domain).get("domain_query") or domain), True
    return ИМЕНА_ИНДЕКСОВ.get(domain, domain), False


def _stats(store: Store, domain: str, as_of: int) -> Stats:
    """Счётчики для шапки; meta.json точнее, fallback сохраняет работу старого индекса."""
    rows = store.trends(domain, as_of, top=50)
    rejected = store.rejected(domain, as_of)
    meta = store.meta(domain)

    def meta_count(key: str, fallback: int) -> int:
        value = meta.get(key)
        return value if isinstance(value, int) and value >= 0 else fallback

    return Stats(
        # В живом режиме n_sources_polled в meta — число опрошенных лент (9),
        # а в шапке аналитик ждёт число обработанных документов (сотни).
        n_sources_polled=(meta_count("n_works", store.n_works(domain))
                          if domain.startswith("live-")
                          else meta_count("n_sources_polled", store.n_works(domain))),
        n_candidates=meta_count("n_candidates", len(rows) + len(rejected)),
        n_rejected=meta_count("n_rejected", len(rejected)),
        n_confident=sum(float(row["emergence_score"]) > 0.75 for row in rows),
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
    if domain is None:
        available = ", ".join(store.domains()) or "индекс пуст"
        raise HTTPException(404, f"Домен '{body.domain}' не найден. Доступно: {available}")
    rows = store.trends(domain, body.as_of, body.top_n)
    if not rows:
        available_years = ", ".join(map(str, store.as_of_years(domain))) or "нет"
        raise HTTPException(
            422,
            f"Домен '{domain}' есть в индексе, но расчёта на срез {body.as_of} нет. "
            f"Доступные срезы: {available_years}.",
        )
    return TrendsResponse(
        domain=DomainInfo(query=body.domain, resolved=domain, n_works=store.n_works(domain),
                          title=_title(store, domain)[0], live=_title(store, domain)[1]),
        as_of=body.as_of,
        methodology_version=rows[0]["methodology_version"],
        generated_at=datetime.now(UTC),
        stats=_stats(store, domain, body.as_of),
        trends=[_as_model(row, store, domain) for row in rows],
        rejected=[
            RejectedCandidate(label=row["label"], reason=row["reason"], n_docs=row["n_docs"])
            for row in store.rejected(domain, body.as_of)
        ],
    )


@router.get("/trends/{trend_id}", response_model=Trend)
def trend(trend_id: str, request: Request) -> Trend:
    store = _store(request)
    row = store.trend(trend_id)
    domain = store.trend_domain(trend_id)
    if row is None or domain is None:
        raise HTTPException(404, f"Тренд '{trend_id}' не найден")
    return _as_model(row, store, domain)
