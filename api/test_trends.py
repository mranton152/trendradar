"""Контрактные проверки маршрутов M-02 на независимом мини-индексе."""
from fastapi.testclient import TestClient

from api.main import create_app
from api.test_store import index  # noqa: F401


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


def test_unknown_domain_and_trend_have_404(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        unknown_domain = client.post("/api/v1/trends", json={"domain": "missing"})
        unknown_trend = client.get("/api/v1/trends/missing")
    assert unknown_domain.status_code == 404
    assert "не найден" in unknown_domain.json()["detail"]
    assert unknown_trend.status_code == 404


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
