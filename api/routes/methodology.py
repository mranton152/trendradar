"""Методология в интерфейсе — прямое требование заказчика."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from core.filters import ОПИСАНИЯ_ПОРОГОВ, ПОРОГИ
from core.live import ОПИСАНИЯ_ПОРОГОВ_LIVE
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА

router = APIRouter(prefix="/api/v1", tags=["methodology"])

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "validation" / "report.json"
CLASSIFIER_PATH = ROOT / "classifier" / "report.json"

DESCRIPTIONS = {
    "novelty": "Новизна: сколько лет прошло с года взлёта — выхода на 10% собственного пика.",
    "growth": "Рост: наклон логарифма частоты за пятилетнее окно.",
    "accel": "Ускорение: разница наклонов второй и первой половины окна.",
    "burst": "Всплеск: во сколько раз последний год превысил базовую линию.",
    "diffusion": "Распространение: сколько разных стран публикует по теме.",
}


def _json(path: Path) -> dict[str, Any] | list[Any] | None:
    """Необязательный отчёт; отсутствующий или битый файл не ломает read-only API."""
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if isinstance(report, (dict, list)) else None


def _validation_report() -> dict[str, Any] | list[Any] | None:
    return _json(REPORT_PATH)


def _classifier_summary() -> dict[str, Any] | None:
    """Итог выбранной модели этапа 1 — то, что жюри проверяет по ТЗ."""
    report = _json(CLASSIFIER_PATH)
    if not isinstance(report, dict):
        return None
    выбор = report.get("выбор")
    модель = (report.get("модели") or {}).get(выбор)
    if not isinstance(модель, dict):
        return None
    ключи = ("accuracy", "accuracy_std", "accuracy_min", "accuracy_max", "precision",
             "recall", "f1", "разбиений", "разбиений_выше_мин")
    return {"model": выбор, "n": report.get("n"), **{k: модель.get(k) for k in ключи}}


@router.get("/methodology")
def methodology() -> dict[str, Any]:
    """Отдаёт версию, веса и антифрод-пороги предрассчитанного индекса."""
    return {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "weights": ВЕСА,
        "descriptions": DESCRIPTIONS,
        "filters": ПОРОГИ,
        # Фразы для аналитика: какой мусор ловит каждый порог. Без них страница
        # показывала «MAX_LAST_YEAR_SHARE = 0.8», что аналитику банка ничего не говорит.
        "filter_descriptions": ОПИСАНИЯ_ПОРОГОВ,
        "live_filter_descriptions": ОПИСАНИЯ_ПОРОГОВ_LIVE,
        "classifier": _classifier_summary(),
        "validation": _validation_report(),
    }
