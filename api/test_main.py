"""Живость API проверяется отдельно от наличия готовых трендов."""
from fastapi.testclient import TestClient

from api.main import create_app
from api.test_store import index  # noqa: F401


def test_empty_health_and_startup_log(tmp_path, caplog):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok", "indexed_domains": [], "offline_mode": True,
        }
        assert "Индекс пуст" in caplog.text


def test_loaded_health_and_cors(index, caplog):  # noqa: F811
    caplog.set_level("INFO", logger="trendradar")
    with TestClient(create_app(index)) as client:
        assert "golden" in caplog.text
        assert client.get("/api/v1/health").json()["indexed_domains"] == ["golden"]
        response = client.options("/api/v1/health", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
