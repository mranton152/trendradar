"""Отчёт валидации: validation/REPORT.md + JSON для /api/v1/methodology.

    python -m validation.report --domain artificial-intelligence --as-of 2021

Отчёт намеренно включает метрику, которую хотелось бы спрятать, — долю
мейнстрима в топе. Эксперты уровня департамента аналитики знают, что идеально
не бывает, и ищут, где команда себя обманывает. Признание ограничений на защите
работает лучше безупречной картинки.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import duckdb

from core.filters import ПОРОГИ
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА
from core.series import year_counts
from validation.metrics import lead_time, precision_at_k, рост_после_среза
from validation.reference import АНТИЭТАЛОН_ИИ_2021, ЭТАЛОН_ИИ_2021

ПОРОГ_РОСТА = 1.2   # ниже этого считаем, что тренд не вырос


def собрать_отчёт(index_dir: str | Path, corpus_path: str | Path,
                  as_of: int, до_года: int) -> dict:
    index_dir, corpus_path = Path(index_dir), Path(corpus_path)
    тренды = duckdb.connect().execute(
        "SELECT rank, label, takeoff_year, cand_id FROM read_parquet(?) "
        "WHERE as_of = ? ORDER BY rank",
        [str(index_dir / "trends.parquet"), int(as_of)]).fetchall()
    ряды = year_counts(index_dir, corpus_path)

    метки = [t[1] for t in тренды]
    выросли = [(t[1], рост_после_среза(ряды.get(t[3], {}), as_of, до_года))
               for t in тренды]
    лаги = [x for x in (lead_time(t[2], ряды.get(t[3], {})) for t in тренды)
            if x is not None]

    return {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "as_of": as_of,
        "до_года": до_года,
        "weights": ВЕСА,
        "filters": ПОРОГИ,
        "n_trends": len(тренды),
        "precision_at_15": round(precision_at_k(метки, ЭТАЛОН_ИИ_2021, k=15), 3),
        "доля_мейнстрима_в_топе": round(
            precision_at_k(метки, АНТИЭТАЛОН_ИИ_2021, k=15), 3),
        "доля_выросших_после_среза": round(
            sum(1 for _, x in выросли if x > ПОРОГ_РОСТА) / max(1, len(выросли)), 3),
        "медианный_lead_time": sorted(лаги)[len(лаги) // 2] if лаги else None,
        "тренды": [{"rank": t[0], "label": t[1], "takeoff_year": t[2],
                    "рост_после_среза": р}
                   for t, (_, р) in zip(тренды, выросли, strict=True)],
        "собран": dt.date.today().isoformat(),
    }


def собрать_по_пулу(as_of: int, до_года: int) -> dict:
    """Отчёт по фиксированному пулу кандидатов вместо индекса конвейера.

    Нужен, пока стадия semantic не выдаёт настоящих кандидатов: ряды берутся
    из кэша замера (validation/probe_cache.json), поэтому цифры настоящие,
    но относятся к качеству ранжирования, а не всей системы. Это записано
    в поле `на_чём_измерено`, чтобы отчёт нельзя было принять за большее.
    """
    from validation.scoring_probe import загрузить_кэш, прогнать

    итог = прогнать(as_of)
    кэш = загрузить_кэш()
    ряды = {т: {int(y): n for y, n in с.items()}
            for т, с in кэш.items() if not т.startswith("страны:")}

    метки = [r["label"] for r in итог["топ15"]]
    выросли = [(r["label"], рост_после_среза(ряды.get(r["label"], {}), as_of, до_года))
               for r in итог["топ15"]]
    лаги = [x for x in (lead_time(r["c"]["takeoff_year"], ряды.get(r["label"], {}))
                        for r in итог["топ15"]) if x is not None]

    return {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "as_of": as_of,
        "до_года": до_года,
        "на_чём_измерено": ("фиксированный пул кандидатов "
                            "(validation/reference.py + validation/pool.py); "
                            "меряет качество ранжирования, не генерацию кандидатов"),
        "weights": ВЕСА,
        "filters": ПОРОГИ,
        "n_trends": len(итог["топ15"]),
        "размер_пула": len(итог["строки"]) + len(итог["отсеяны"]),
        "precision_at_15": round(precision_at_k(метки, ЭТАЛОН_ИИ_2021, k=15), 3),
        "доля_мейнстрима_в_топе": round(
            precision_at_k(метки, АНТИЭТАЛОН_ИИ_2021, k=15), 3),
        "доля_выросших_после_среза": round(
            sum(1 for _, x in выросли if x > ПОРОГ_РОСТА) / max(1, len(выросли)), 3),
        "медианный_lead_time": sorted(лаги)[len(лаги) // 2] if лаги else None,
        "тренды": [{"rank": i, "label": r["label"],
                    "takeoff_year": r["c"]["takeoff_year"], "рост_после_среза": рост}
                   for i, (r, (_, рост)) in enumerate(
                       zip(итог["топ15"], выросли, strict=True), 1)],
        "собран": dt.date.today().isoformat(),
    }


def написать_markdown(отчёт: dict, md_path: str | Path, json_path: str | Path) -> None:
    md_path, json_path = Path(md_path), Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(отчёт, ensure_ascii=False, indent=2))

    строки = "\n".join(
        f"| {t['rank']} | {t['label']} | {t['takeoff_year'] or '—'} | x{t['рост_после_среза']} |"
        for t in отчёт["тренды"])

    # Строки таблицы собираются заранее: внутри f-строки они не помещаются
    # в лимит длины, а переносить их в готовом markdown нельзя.
    м_precision = (f"| Precision@15 по эталону | {отчёт['precision_at_15']:.0%} | "
                   "доля топа, попавшая в список заведомо выстреливших технологий |")
    м_мейнстрим = (f"| Доля мейнстрима в топе | {отчёт['доля_мейнстрима_в_топе']:.0%} | "
                   "**чем меньше, тем лучше**: это уже известные темы, "
                   "а не слабые сигналы |")
    м_выросли = (f"| Выросли после среза | {отчёт['доля_выросших_после_среза']:.0%} | "
                 f"доля трендов, чья активность выросла более чем "
                 f"в {ПОРОГ_РОСТА} раза |")
    м_лаг = (f"| Медианный lead time | {отчёт['медианный_lead_time']} лет | "
             "за сколько лет до пика тренд был обнаружен |")

    md_path.write_text(f"""# Отчёт валидации

Срез `as_of = {отчёт['as_of']}`, проверка по данным до {отчёт['до_года']}.
Методология версии {отчёт['version']}, собрано {отчёт['собран']}.

| Метрика | Значение | Смысл |
|---|---|---|
{м_precision}
{м_мейнстрим}
{м_выросли}
{м_лаг}

Эталонный список собран до прогонов и не менялся по их результатам —
иначе цифра Precision ничего не значит.

## ТОП-{отчёт['n_trends']} на срезе {отчёт['as_of']}

| # | Тренд | Год взлёта | Рост после среза |
|---|---|---|---|
{строки}

## Параметры

Веса компонент: `{отчёт['weights']}`

Пороги фильтров: `{отчёт['filters']}`
""", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="golden")
    ap.add_argument("--as-of", type=int, default=2021)
    ap.add_argument("--until", type=int, default=dt.date.today().year)
    ap.add_argument("--source", choices=["index", "pool"], default="index",
                    help="index — по кандидатам конвейера; pool — по фиксированному пулу")
    args = ap.parse_args()

    if args.source == "pool":
        отчёт = собрать_по_пулу(args.as_of, args.until)
        написать_markdown(отчёт, "validation/REPORT.md", "validation/report.json")
        print(json.dumps({k: v for k, v in отчёт.items() if k != "тренды"},
                         ensure_ascii=False, indent=2))
        return

    index_dir = Path("data/index") / args.domain
    corpus = Path("data/corpus") / args.domain / "works.parquet"
    if not corpus.exists():
        corpus = index_dir / "works.parquet"
    if not corpus.exists():
        raise SystemExit(f"нет корпуса для домена {args.domain}")

    отчёт = собрать_отчёт(index_dir, corpus, args.as_of, args.until)
    написать_markdown(отчёт, "validation/REPORT.md", "validation/report.json")
    print(json.dumps({k: v for k, v in отчёт.items() if k != "тренды"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
