"""Сквозной тест стадии core на синтетическом индексе.

Проверяет весь путь «кандидаты -> ряды -> фильтры -> скоринг -> trends»,
не дожидаясь настоящего корпуса.
"""
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import CAND_DOCS, CANDIDATES, TRENDS, WORKS
from core.build import построить

СТРАНЫ = ["RU", "US", "CN", "DE", "FR", "GB", "JP", "IN"]

# c1 — зарождающийся: взлёт 2023, ускоряется
# c2 — мейнстрим: высокий ровный уровень с 2020
# c3 — разовый вброс: всё в одном году
РЯДЫ = {
    "c1": {2021: 8, 2022: 15, 2023: 25, 2024: 50, 2025: 80, 2026: 120},
    "c2": {2020: 200, 2021: 205, 2022: 210, 2023: 215,
           2024: 220, 2025: 225, 2026: 230},
    "c3": {2026: 300},
}


@pytest.fixture
def индекс(tmp_path):
    works, links, счётчик = [], [], 0
    for cand_id, ряд in РЯДЫ.items():
        for year, n in ряд.items():
            for i in range(n):
                doc_id = f"openalex:W{счётчик}"
                счётчик += 1
                works.append({
                    "doc_id": doc_id, "source": "openalex", "doc_type": "article",
                    "title": f"{cand_id} работа {i}", "abstract": None,
                    "year": year, "date": None, "lang": "en", "doi": None,
                    "url": f"https://example.org/{doc_id}", "cited_by": i,
                    "countries": [СТРАНЫ[i % len(СТРАНЫ)]], "institutions": [],
                    "authors": [], "concepts": [], "domain": "test",
                    "harvested_at": "2026-09-09"})
                links.append({"cand_id": cand_id, "doc_id": doc_id, "weight": 1.0})

    кандидаты = [
        {"cand_id": "c1", "kind": "cluster", "label": "physics-informed neural network",
         "aliases": [], "top_terms": [], "emb_row": 0, "n_docs": 298, "domain": "test"},
        {"cand_id": "c2", "kind": "term", "label": "convolutional neural network",
         "aliases": [], "top_terms": [], "emb_row": 1, "n_docs": 1505, "domain": "test"},
        {"cand_id": "c3", "kind": "term", "label": "lynching tree",
         "aliases": [], "top_terms": [], "emb_row": 2, "n_docs": 300, "domain": "test"},
    ]

    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")
    pq.write_table(pa.Table.from_pylist(кандидаты, schema=CANDIDATES),
                   tmp_path / "candidates.parquet")
    np.save(tmp_path / "embeddings.npy", np.eye(3, 1024, dtype=np.float32))
    return tmp_path


def test_разовый_вброс_не_попадает_в_выдачу(индекс):
    строки = построить(индекс, индекс / "works.parquet", "test", as_of=2026)
    assert "lynching tree" not in [r["label"] for r in строки]


def test_зарождающийся_обгоняет_мейнстрим(индекс):
    строки = построить(индекс, индекс / "works.parquet", "test", as_of=2026)
    метки = [r["label"] for r in строки]
    assert метки[0] == "physics-informed neural network"


def test_выдача_соответствует_схеме_trends(индекс, tmp_path):
    строки = построить(индекс, индекс / "works.parquet", "test", as_of=2026)
    путь = tmp_path / "trends.parquet"
    pq.write_table(pa.Table.from_pylist(строки, schema=TRENDS), путь)
    assert pq.read_schema(путь).equals(TRENDS)
    первый = строки[0]
    assert первый["rank"] == 1
    assert первый["takeoff_year"] == 2022
    assert len(первый["years"]) == len(первый["counts"])
    assert первый["top_doc_ids"]


def test_бэктест_не_видит_будущего(индекс):
    """При as_of=2023 расчёт не должен использовать данные 2024-2026."""
    строки = построить(индекс, индекс / "works.parquet", "test", as_of=2023)
    c1 = next(r for r in строки if r["label"] == "physics-informed neural network")
    assert max(c1["years"]) == 2023
    assert sum(c1["counts"]) == 48   # 2021:8 + 2022:15 + 2023:25, и ничего после


def test_отсеянные_возвращаются_с_причиной(индекс):
    """ТЗ: показывать причины исключения. lynching tree с нулём стран обязан
    быть виден, а не молча пропасть."""
    from core.build import построить_с_отсеянными
    строки, отсеянные = построить_с_отсеянными(
        индекс, индекс / "works.parquet", "test", as_of=2026)
    метки = {r["label"]: r["reason"] for r in отсеянные}
    assert "lynching tree" in метки
    assert метки["lynching tree"] == "всплеск одного года"
    поля = {"cand_id", "label", "domain", "reason", "n_docs", "as_of"}
    assert all(поля <= set(r) for r in отсеянные)


def test_бэктест_заполняется_только_для_прошлого(индекс):
    строки_2026 = построить(индекс, индекс / "works.parquet", "test", as_of=2026)
    assert all(r["bt_growth_x"] is None for r in строки_2026)

    строки_2023 = построить(индекс, индекс / "works.parquet", "test", as_of=2023)
    c1 = next(r for r in строки_2023 if r["label"] == "physics-informed neural network")
    assert c1["bt_at_cutoff"] == 25       # 2023
    assert c1["bt_peak_after"] == 120     # 2026
    assert c1["bt_growth_x"] > 4
