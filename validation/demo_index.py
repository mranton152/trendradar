"""Демонстрационный индекс трендов на фиксированном пуле кандидатов.

    python -m validation.demo_index

ЧТО ЭТО. Полноценный trends.parquet по контракту TRENDS, посчитанный настоящим
скорингом на настоящих годовых рядах OpenAlex. Пишется для домена `golden`
на два среза — 2026 и 2021, — чтобы работал переключатель as_of.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это не выход конвейера. Кандидаты здесь заданы вручную
(validation/reference.py и validation/pool.py), а не найдены стадией semantic.
Как только появятся настоящие candidates.parquet, индекс пересоберётся через
`python -m core.build`, и этот скрипт станет не нужен.

Зачем всё равно нужен: без trends.parquet фронт и API нечего показывать,
а ждать генерацию кандидатов — значит потерять несколько дней разработки
продукта. Данные при этом честные: каждое число посчитано по настоящим рядам,
каждая ссылка ведёт в настоящий документ из золотого снапшота.

Термины без документов в снапшоте отбрасываются: карточка без работающих
ссылок нарушает главное свойство продукта — любое число кликабельно
до первоисточника.
"""
import datetime as dt
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import TRENDS
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, стадия, уверенность
from validation.scoring_probe import прогнать

ИНДЕКС = Path("data/index/golden")
КОРПУС = ИНДЕКС / "works.parquet"
ДОМЕН = "golden"
СРЕЗЫ = (2026, 2021)
МАКС_ДОКУМЕНТОВ = 20


def документы(термин: str, as_of: int, con: duckdb.DuckDBPyConnection) -> list[str]:
    """Документы снапшота, где термин встречается в заголовке или аннотации.

    Свежие и цитируемые вперёд — их и увидит пользователь в списке источников.
    """
    шаблон = f"%{термин.lower()}%"
    строки = con.execute(
        "SELECT doc_id FROM read_parquet(?) "
        "WHERE year <= ? AND (lower(title) LIKE ? "
        "   OR lower(coalesce(abstract, '')) LIKE ?) "
        "ORDER BY year DESC, cited_by DESC NULLS LAST LIMIT ?",
        [str(КОРПУС), int(as_of), шаблон, шаблон, МАКС_ДОКУМЕНТОВ]).fetchall()
    return [r[0] for r in строки]


def собрать(as_of: int, con: duckdb.DuckDBPyConnection) -> list[dict]:
    итог = прогнать(as_of)
    строки, ранг = [], 0
    for r in итог["строки"]:
        doc_ids = документы(r["label"], as_of, con)
        if not doc_ids:
            continue          # карточка без ссылок ломает главное свойство продукта
        ранг += 1
        c = r["c"]
        строки.append({
            "trend_id": f"t:{ДОМЕН}:{as_of}:{ранг:02d}",
            "domain": ДОМЕН, "as_of": as_of, "rank": ранг,
            "cand_id": f"c:{ДОМЕН}:{r['label'].replace(' ', '-')}",
            "label": r["label"], "aliases": [],
            "emergence_score": float(r["es"]),
            "c_novelty": float(r["parts"]["novelty"]),
            "c_growth": float(r["parts"]["growth"]),
            "c_accel": float(r["parts"]["accel"]),
            "c_burst": float(r["parts"]["burst"]),
            "c_diffusion": float(r["parts"]["diffusion"]),
            "maturity_pct": float(r["maturity_pct"]),
            "first_mention": c["first_mention"], "takeoff_year": c["takeoff_year"],
            "years": c["years"], "counts": c["counts_series"],
            "freq_per_million": [float(f) for f in c["freq_series"]],
            "n_docs": c["counts_recent"], "n_countries": int(r["countries"]),
            "n_orgs": None, "n_patents": None,
            "top_doc_ids": doc_ids,
            "stage": стадия(c, r["maturity_pct"]),
            "confidence": уверенность(c, r["countries"]),
            "methodology_version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        })
        if ранг >= 15:
            break
    return строки


def main() -> None:
    if not КОРПУС.exists():
        raise SystemExit(f"нет {КОРПУС} — сначала нужен золотой снапшот")

    con = duckdb.connect()
    все = []
    for as_of in СРЕЗЫ:
        строки = собрать(as_of, con)
        все.extend(строки)
        print(f"срез {as_of}: {len(строки)} трендов")
        for r in строки[:5]:
            print(f"   {r['rank']:>2} {r['emergence_score']:.3f}  {r['label']:<40}"
                  f" источников: {len(r['top_doc_ids'])}")

    pq.write_table(pa.Table.from_pylist(все, schema=TRENDS),
                   ИНДЕКС / "trends.parquet", compression="zstd")

    (ИНДЕКС / "TRENDS_PROVENANCE.json").write_text(json.dumps({
        "источник": "validation/demo_index.py",
        "что_это": "демо-индекс на фиксированном пуле кандидатов",
        "чем_не_является": "не выход стадии semantic; кандидаты заданы вручную",
        "ряды": "настоящие, OpenAlex, концепт C154945302, кэш validation/probe_cache.json",
        "ссылки": "настоящие doc_id из data/index/golden/works.parquet",
        "срезы": list(СРЕЗЫ),
        "методология": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "собран": dt.date.today().isoformat(),
        "заменить_на": "python -m core.build --domain <домен> --as-of <год>",
        "известные_дефекты": [
            "На срезе 2021 в выдачу попадает 'covid-19 pandemic' — это событие, "
            "а не технология. Его снимает технологический фильтр на стадии "
            "генерации кандидатов (semantic/techfilter.py, задача K-07), которого "
            "пока нет. Руками из демо не убираем: курировать выдачу — ровно то, "
            "за что мы критикуем решения-обёртки над чат-ботом.",
            "У части трендов одна-две ссылки: золотой снапшот — выборка из 5000 "
            "документов, а не полный корпус. На полном корпусе ссылок будут десятки.",
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(все)} строк -> {ИНДЕКС / 'trends.parquet'}")


if __name__ == "__main__":
    main()
