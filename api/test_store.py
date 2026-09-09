"""Проверки снимка индекса без сетевых источников."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from api.store import Store
from contracts.schemas import TRENDS, WORKS


@pytest.fixture
def index(tmp_path):
    index_root = tmp_path / "index"
    domain = index_root / "golden"
    domain.mkdir(parents=True)
    rows = []
    for year, rank in [(2026, 3), (2021, 1), (2026, 1), (2026, 2)]:
        rows.append({
            "trend_id": f"t:ai:{year}:{rank}", "domain": "artificial-intelligence",
            "as_of": year, "rank": rank, "cand_id": f"c{rank}", "label": "Тренд",
            "aliases": [], "emergence_score": 0.5,
            **dict.fromkeys(["c_novelty", "c_growth", "c_accel", "c_burst",
                            "c_diffusion", "maturity_pct"], 0.5),
            "first_mention": None, "takeoff_year": None,
            "years": [year], "counts": [20], "freq_per_million": [1.0],
            "n_docs": 20, "n_countries": 5, "n_orgs": None, "n_patents": None,
            "top_doc_ids": ["openalex:W1"], "stage": "emerging", "confidence": "low",
            "methodology_version": "1.0",
        })
    pq.write_table(pa.Table.from_pylist(rows, schema=TRENDS), domain / "trends.parquet")
    works = [{
        "doc_id": "openalex:W1", "source": "openalex", "doc_type": "article",
        "title": "Источник", "year": 2020, "url": "https://example.org/paper",
        "domain": "artificial-intelligence", "harvested_at": "2026-09-08",
    }]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), domain / "works.parquet")
    return index_root


def test_snapshot_filters_sorts_and_preserves_native_values(index):
    store = Store(index)
    assert store.domains() == ["golden"]
    rows = store.trends("golden", 2026, 2)
    assert [r["rank"] for r in rows] == [1, 2]
    assert all(r["as_of"] == 2026 for r in rows)
    assert rows[0]["aliases"] == []
    assert rows[0]["n_orgs"] is None
    assert store.trends("golden", 2000) == []
    assert store.trends("golden", 2026, 0) == []
    # Идентификатор и домен внутри файла не обязаны совпадать с именем golden.
    assert store.trend("t:ai:2021:1")["as_of"] == 2021
    assert store.trend_domain("t:ai:2021:1") == "golden"
    assert store.n_works("golden") == 1
    assert store.as_of_years("golden") == [2021, 2026]
    rows[0]["years"].append(9999)
    assert store.trend("t:ai:2026:1")["years"] == [2026]
    (index / "golden" / "trends.parquet").unlink()
    (index / "golden" / "works.parquet").unlink()
    assert len(store.trends("golden", 2026)) == 3
    assert store.works("golden", ["openalex:W1"])[0]["title"] == "Источник"


@pytest.mark.parametrize("domain", ["missing", "../../secret", "golden/../secret",
                                     "golden' OR '1'='1", ""])
def test_untrusted_domain(index, domain):
    store = Store(index)
    assert store.trends(domain, 2026) == []
    assert store.works(domain, ["openalex:W1"]) == []


def test_ids_are_looked_up_exactly(index):
    store = Store(index)
    assert store.trend("' OR '1'='1") is None
    assert store.works("golden", ["' OR '1'='1"]) == []
    assert store.works("golden", []) == []
    assert len(store.works("golden", ["missing", "openalex:W1", "openalex:W1"])) == 1


def test_empty_index(tmp_path):
    store = Store(tmp_path / "missing")
    assert store.domains() == []
    assert store.trend("missing") is None
    assert store.trend_domain("missing") is None
    assert store.n_works("missing") == 0
    assert store.as_of_years("missing") == []


def test_corpus_location_has_priority(index):
    corpus = index.parent / "corpus" / "golden"
    corpus.mkdir(parents=True)
    table = pq.read_table(index / "golden" / "works.parquet")
    pq.write_table(table, corpus / "works.parquet")
    (index / "golden" / "works.parquet").write_bytes(b"unused")
    assert Store(index).works("golden", ["openalex:W1"])[0]["year"] == 2020


def test_missing_works_is_allowed(index):
    (index / "golden" / "works.parquet").unlink()
    assert Store(index).works("golden", ["openalex:W1"]) == []


def test_broken_domain_does_not_hide_healthy_domain(index, caplog):
    broken = index / "broken"
    broken.mkdir()
    (broken / "trends.parquet").write_bytes(b"broken parquet")
    assert Store(index).domains() == ["golden"]
    assert "broken" in caplog.text


def test_works_only_directory_is_not_a_ready_domain(index):
    (index / "golden" / "trends.parquet").unlink()
    assert Store(index).domains() == []
