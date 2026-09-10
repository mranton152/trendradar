"""Публичная методология должна быть доступна и при пустом индексе."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_methodology_exposes_version_weights_and_filters(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/v1/methodology")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "1.0"
    assert set(body["weights"]) == {"novelty", "growth", "accel", "burst", "diffusion"}
    assert body["descriptions"]["growth"].startswith("Рост:")
    assert body["filters"]["MIN_EVIDENCE"] == 20
