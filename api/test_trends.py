"""Контрактные проверки маршрутов M-02 на независимом мини-индексе."""
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from api.main import create_app
from api.test_store import index  # noqa: F401
from contracts.schemas import CARDS


def test_trends_response_contains_evidence_and_sources(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        response = client.post("/api/v1/trends", json={
            "domain": "golden", "top_n": 2, "as_of": 2026,
        })
    assert response.status_code == 200
    body = response.json()
    assert body["domain"] == {"query": "golden", "resolved": "golden", "n_works": 1}
    assert body["as_of"] == 2026
    assert body["methodology_version"] == "1.0"
    assert len(body["trends"]) == 2
    trend = body["trends"][0]
    assert trend["rank"] == 1
    assert set(trend["components"]) == {"novelty", "growth", "accel", "burst", "diffusion"}
    assert trend["evidence"]["series"] == [{
        "year": 2026, "count": 20, "freq_per_million": 1.0,
    }]
    assert trend["sources"] == [{
        "doc_id": "openalex:W1", "title": "Источник", "url": "https://example.org/paper",
        "year": 2020, "type": "article",
    }]
    assert trend["motivation"] is None
    assert trend["case_example"] is None
    assert trend["backtest"] is None


def test_single_trend_keeps_index_folder_for_source_lookup(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        response = client.get("/api/v1/trends/t:ai:2021:1")
    assert response.status_code == 200
    assert response.json()["sources"][0]["doc_id"] == "openalex:W1"


def test_trend_includes_generated_motivation_and_case(index):  # noqa: F811
    cards = [{
        "trend_id": "t:ai:2026:1", "title_ru": "Тестовый тренд",
        "problem": "Проблема", "problem_docs": ["openalex:W1"],
        "advantage": "Преимущество", "advantage_docs": ["openalex:W1"],
        "case_type": "research", "case_name": "Исследование", "case_text": "Кейс",
        "case_docs": ["openalex:W1"], "fintech_note": None, "citation_coverage": 1.0,
        "model": "test", "generated_at": "2026-09-11T00:00:00+00:00",
    }]
    pq.write_table(
        pa.Table.from_pylist(cards, schema=CARDS), index / "golden" / "cards.parquet"
    )
    with TestClient(create_app(index)) as client:
        response = client.get("/api/v1/trends/t:ai:2026:1")

    assert response.status_code == 200
    assert response.json()["motivation"] == {
        "problem": "Проблема", "advantage": "Преимущество", "sources": ["openalex:W1"],
    }
    assert response.json()["case_example"] == {
        "type": "research", "name": "Исследование", "description": "Кейс",
        "source": "openalex:W1",
    }


def test_unknown_domain_and_trend_have_404(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        unknown_domain = client.post("/api/v1/trends", json={"domain": "missing"})
        unknown_trend = client.get("/api/v1/trends/missing")
    assert unknown_domain.status_code == 404
    assert "не найден" in unknown_domain.json()["detail"]
    assert unknown_trend.status_code == 404


def test_known_domain_without_requested_snapshot_has_actionable_error(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        response = client.post("/api/v1/trends", json={"domain": "golden", "as_of": 2023})
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Домен 'golden' есть в индексе, но расчёта на срез 2023 нет. "
        "Доступные срезы: 2021, 2026."
    )


def test_request_limits_and_resolve(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        invalid = client.post("/api/v1/trends", json={"domain": "golden", "top_n": 51})
        exact = client.post("/api/v1/domains/resolve", json={"query": "golden"})
        fuzzy = client.post("/api/v1/domains/resolve", json={"query": "golden trends"})
        no_match = client.post("/api/v1/domains/resolve", json={"query": "quantum computing"})
    assert invalid.status_code == 422
    assert exact.json()["in_index"] is True
    assert fuzzy.json()["resolved"] == "golden"
    assert no_match.json() == {
        "resolved": None, "display_name": None, "n_works": 0,
        "in_index": False, "alternatives": ["golden"],
    }
