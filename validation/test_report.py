"""Отчёт валидации собирается на синтетическом индексе — настоящего пока нет."""
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import CAND_DOCS, TRENDS, WORKS
from validation.report import написать_markdown, собрать_отчёт

РЯДЫ = {
    "c1": {2021: 40, 2022: 90, 2023: 200, 2024: 400},   # вырос после среза
    "c2": {2021: 100, 2022: 90, 2023: 80, 2024: 70},    # затух
}


@pytest.fixture
def индекс(tmp_path):
    works, links, n = [], [], 0
    for cand_id, ряд in РЯДЫ.items():
        for year, count in ряд.items():
            for _ in range(count):
                doc_id = f"openalex:W{n}"
                n += 1
                works.append({
                    "doc_id": doc_id, "source": "openalex", "doc_type": "article",
                    "title": doc_id, "abstract": None, "year": year, "date": None,
                    "lang": "en", "doi": None, "url": "u", "cited_by": 0,
                    "countries": ["RU"], "institutions": [], "authors": [],
                    "concepts": [], "domain": "t", "harvested_at": "2026-09-09"})
                links.append({"cand_id": cand_id, "doc_id": doc_id, "weight": 1.0})

    def тренд(rank, cand_id, label, takeoff):
        return {
            "trend_id": f"t:t:2021:{rank:02d}", "domain": "t", "as_of": 2021,
            "rank": rank, "cand_id": cand_id, "label": label, "aliases": [],
            "emergence_score": 0.9 - rank / 10,
            "c_novelty": 0.5, "c_growth": 0.5, "c_accel": 0.5,
            "c_burst": 0.5, "c_diffusion": 0.5, "maturity_pct": 0.2,
            "first_mention": 2019, "takeoff_year": takeoff,
            "years": sorted(РЯДЫ[cand_id]),
            "counts": [РЯДЫ[cand_id][y] for y in sorted(РЯДЫ[cand_id])],
            "freq_per_million": [1.0] * len(РЯДЫ[cand_id]),
            "n_docs": sum(РЯДЫ[cand_id].values()), "n_countries": 20,
            "n_orgs": None, "n_patents": None, "top_doc_ids": ["openalex:W0"],
            "stage": "emerging", "confidence": "high", "methodology_version": "1.0"}

    тренды = [тренд(1, "c1", "vision transformer", 2020),
              тренд(2, "c2", "convolutional neural network", 2016)]

    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS), tmp_path / "cand_docs.parquet")
    pq.write_table(pa.Table.from_pylist(тренды, schema=TRENDS), tmp_path / "trends.parquet")
    np.save(tmp_path / "embeddings.npy", np.eye(2, 1024, dtype=np.float32))
    return tmp_path


def test_отчёт_считает_попадания_в_эталон(индекс):
    отчёт = собрать_отчёт(индекс, индекс / "works.parquet", as_of=2021, до_года=2024)
    # 'vision transformer' есть в эталоне, 'convolutional neural network' — нет
    assert отчёт["precision_at_15"] == 0.5


def test_отчёт_отдельно_считает_мейнстрим(индекс):
    """Метрика, которую хочется спрятать. Не прячем: слайд про ограничения
    работает на защите лучше идеальной картинки."""
    отчёт = собрать_отчёт(индекс, индекс / "works.parquet", as_of=2021, до_года=2024)
    assert отчёт["доля_мейнстрима_в_топе"] == 0.5


def test_затухший_тренд_не_считается_выросшим(индекс):
    отчёт = собрать_отчёт(индекс, индекс / "works.parquet", as_of=2021, до_года=2024)
    assert отчёт["доля_выросших_после_среза"] == 0.5


def test_отчёт_пишется_в_два_файла(индекс, tmp_path):
    отчёт = собрать_отчёт(индекс, индекс / "works.parquet", as_of=2021, до_года=2024)
    md, js = tmp_path / "REPORT.md", tmp_path / "report.json"
    написать_markdown(отчёт, md, js)
    assert "Precision@15" in md.read_text()
    assert json.loads(js.read_text())["version"] == "1.0"
