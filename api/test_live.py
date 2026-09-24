"""Контракт M-13: HTTP запускает фон, а ошибка стадии видна клиенту."""
import subprocess

from fastapi.testclient import TestClient

from api.main import create_app
from api.routes import live
from api.test_store import index  # noqa: F401


class ImmediateThread:
    """Запускает target синхронно, чтобы тест не зависел от планировщика."""

    def __init__(self, *, target, args, daemon):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_live_job_exposes_stage_failure(index, monkeypatch):  # noqa: F811
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(live.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(live.subprocess, "run", fail)
    with TestClient(create_app(index)) as client:
        started = client.post("/api/v1/live", json={"query": "кибербезопасность", "budget_s": 30})
        assert started.status_code == 202
        status = client.get(f"/api/v1/live/{started.json()['job_id']}")

    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["error"]


def test_unknown_live_job_returns_404(index):  # noqa: F811
    with TestClient(create_app(index)) as client:
        response = client.get("/api/v1/live/missing")
    assert response.status_code == 404
