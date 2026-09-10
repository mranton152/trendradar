"""Методология в интерфейсе — прямое требование заказчика."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from core.filters import ПОРОГИ
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА

router = APIRouter(prefix="/api/v1", tags=["methodology"])

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "validation" / "report.json"

DESCRIPTIONS = {
    "novelty": "Новизна: сколько лет прошло с года взлёта — выхода на 10% собственного пика.",
    "growth": "Рост: наклон логарифма частоты за пятилетнее окно.",
    "accel": "Ускорение: разница наклонов второй и первой половины окна.",
    "burst": "Всплеск: во сколько раз последний год превысил базовую линию.",
    "diffusion": "Распространение: сколько разных стран публикует по теме.",
}


def _validation_report() -> dict[str, Any] | list[Any] | None:
    """Читает необязательный отчёт валидации; битый файл не ломает read-only API."""
    if not REPORT_PATH.is_file():
        return None
    try:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if isinstance(report, (dict, list)) else None


@router.get("/methodology")
def methodology() -> dict[str, Any]:
    """Отдаёт версию, веса и антифрод-пороги предрассчитанного индекса."""
    return {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "weights": ВЕСА,
        "descriptions": DESCRIPTIONS,
        "filters": ПОРОГИ,
        "validation": _validation_report(),
    }
