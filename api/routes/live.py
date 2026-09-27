"""Фоновый запуск живого конвейера без очереди и без расчётов в HTTP-потоке."""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import APIRouter, HTTPException, Request

from api.models import LiveAccepted, LiveRequest, LiveStatus
from api.store import Store

router = APIRouter(prefix="/api/v1", tags=["live"])

# Широкий запрос про ИИ — пример из ТЗ — ведём в готовый индекс: там выдача
# по 5000 работ с бэктестом и карточками. Живой режим на нём слабее (замер
# 27.09: «технологии в ИИ» — 2 тренда), потому что новости по «ИИ вообще»
# повторяют одни и те же зрелые термины. Узкие запросы («кибербезопасность ИИ»)
# в правило не попадают и идут в живой сбор.
СЛУЖЕБНЫЕ = {"технологии", "технология", "в", "во", "области", "сфере", "тренды",
             "тренд", "слабые", "сигналы", "перспективные", "зарождающиеся", "новые",
             "направление", "развитие", "и", "technologies", "technology", "in", "trends",
             "emerging", "weak", "signals", "the", "of"}
ИИ = {"ии", "ai", "искусственный интеллект", "artificial intelligence",
      "машинное обучение", "machine learning", "нейросети", "нейронные сети"}
ИНДЕКС_ИИ = ("golden", "ai-full")


def индекс_для(query: str, domains: list[str]) -> str | None:
    слова = [w for w in re.findall(r"[\w-]+", query.lower()) if w not in СЛУЖЕБНЫЕ]
    if " ".join(слова) in ИИ:
        return next((d for d in ИНДЕКС_ИИ if d in domains), None)
    return None


def _jobs(request: Request) -> dict[str, dict]:
    return request.app.state.live_jobs


def _run(job: dict, root: Path, query: str, budget: int, app) -> None:
    started = time.monotonic()
    work_dir = root.parent / "live" / job["job_id"]
    semantic_dir = work_dir / "semantic"
    try:
        job.update(status="collecting", stage_text="Собираем источники…")
        subprocess.run([sys.executable, "-m", "ingest.live", "--query", query,
                        "--budget", str(budget), "--output", str(work_dir)],
                       check=True, timeout=budget + 30)
        meta = json.loads((work_dir / "meta.json").read_text(encoding="utf-8"))
        job.update(n_docs=int(meta.get("n_docs", 0)),
                   n_sources_polled=int(meta.get("n_sources_polled", 0)),
                   domain=meta["domain"], status="candidates",
                   stage_text=f"Ищем кандидатов… {meta.get('n_docs', 0)} документов")
        subprocess.run([sys.executable, "-m", "semantic.build", "--scope", "live",
                        "--domain", meta["domain"], "--works", str(work_dir / "works.parquet"),
                        "--output", str(semantic_dir), "--cache",
                        str(root.parent / "live-semantic-cache"),
                        "--as-of", str(time.gmtime().tm_year)],
                       check=True, timeout=60)
        candidate_meta = json.loads((semantic_dir / "meta.json").read_text(encoding="utf-8"))
        job.update(n_candidates=int(candidate_meta.get("n_candidates", 0)), status="scoring",
                   stage_text="Считаем слабые сигналы…")
        subprocess.run([sys.executable, "-m", "core.build", "--domain", meta["domain"],
                        "--live", str(semantic_dir)], check=True, timeout=60)
        no_trends = pq.read_metadata(semantic_dir / "trends.parquet").num_rows == 0
        destination = root / meta["domain"]
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(semantic_dir), destination)
        shutil.rmtree(work_dir)
        app.state.store = Store(root)
        stage_text = "Поиск завершён: зарождающихся трендов не найдено" if no_trends else "Готово"
        job.update(status="done", no_trends=no_trends, stage_text=stage_text,
                   domain=meta["domain"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError) as exc:
        job.update(status="failed", stage_text="Не удалось собрать выдачу", error=str(exc))
    finally:
        job["elapsed_s"] = round(time.monotonic() - started, 1)


@router.post("/live", response_model=LiveAccepted, status_code=202)
def start_live(body: LiveRequest, request: Request) -> LiveAccepted:
    job_id = uuid.uuid4().hex
    store = request.app.state.store
    готовый = индекс_для(body.query, store.domains())
    if готовый:
        _jobs(request)[job_id] = {
            "job_id": job_id, "status": "done", "domain": готовый, "error": None,
            "stage_text": "Направление есть в индексе: выдача с бэктестом",
            "n_docs": store.n_works(готовый), "n_sources_polled": 0,
            "n_candidates": 0, "elapsed_s": 0.0, "no_trends": False}
        return LiveAccepted(job_id=job_id, domain=готовый)
    job = {"job_id": job_id, "status": "collecting", "stage_text": "Собираем источники…",
           "n_docs": 0, "n_sources_polled": 0, "n_candidates": 0, "elapsed_s": 0.0,
           "domain": None, "error": None}
    _jobs(request)[job_id] = job
    thread = threading.Thread(target=_run, args=(job, request.app.state.store.root,
                              body.query, body.budget_s, request.app), daemon=True)
    thread.start()
    return LiveAccepted(job_id=job_id, domain="pending")


@router.get("/live/{job_id}", response_model=LiveStatus)
def live_status(job_id: str, request: Request) -> LiveStatus:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(404, "Задача живого поиска не найдена")
    return LiveStatus(**job)
