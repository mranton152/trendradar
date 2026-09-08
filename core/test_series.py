import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, WORKS
from core.series import country_spread, year_counts


def _корпус(tmp_path):
    def работа(doc_id, year, countries):
        return {"doc_id": doc_id, "source": "openalex", "doc_type": "article",
                "title": doc_id, "abstract": None, "year": year, "date": None,
                "lang": "en", "doi": None, "url": "u", "cited_by": 0,
                "countries": countries, "institutions": [], "authors": [],
                "concepts": [], "domain": "d", "harvested_at": "2026-09-09"}

    works = [работа("d1", 2020, ["RU", "US"]),
             работа("d2", 2021, ["US"]),
             работа("d3", 2021, ["CN"])]
    links = [{"cand_id": "c1", "doc_id": "d1", "weight": 1.0},
             {"cand_id": "c1", "doc_id": "d2", "weight": 1.0},
             {"cand_id": "c2", "doc_id": "d3", "weight": 1.0}]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")
    return tmp_path / "works.parquet"


def test_годовые_ряды_считаются_по_связям(tmp_path):
    корпус = _корпус(tmp_path)
    ряды = year_counts(tmp_path, корпус)
    assert ряды["c1"] == {2020: 1, 2021: 1}
    assert ряды["c2"] == {2021: 1}


def test_страны_считаются_уникально_в_окне(tmp_path):
    корпус = _корпус(tmp_path)
    страны = country_spread(tmp_path, корпус, 2020, 2021)
    assert страны["c1"] == 2      # RU, US — US не задваивается
    assert страны["c2"] == 1
