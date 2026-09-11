import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, WORKS
from core.series import country_spread, top_docs, year_counts


def _корпус(tmp_path):
    def работа(doc_id, year, countries, doc_type="article"):
        return {"doc_id": doc_id, "source": "openalex", "doc_type": doc_type,
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


def test_идентификатор_кандидата_не_склеивается_в_запрос(tmp_path):
    """DuckDB умеет read_parquet по любому пути, поэтому склейка SQL из внешних
    данных — это чтение произвольного файла, а не только порча выборки.
    Значения обязаны идти параметрами.
    """
    корпус = _корпус(tmp_path)
    злой = "c1' OR '1'='1"
    assert top_docs(tmp_path, корпус, злой) == []
    assert top_docs(tmp_path, корпус, "c1") == ["d2", "d1"]


def test_препринты_весят_больше_статей(tmp_path):
    """Препринты опережают журналы на год — значит, в ряду они должны весить
    больше, иначе зарождающийся сигнал виден только когда он уже не слабый."""
    def работа(doc_id, doc_type):
        return {"doc_id": doc_id, "source": "openalex", "doc_type": doc_type,
                "title": doc_id, "abstract": None, "year": 2024, "date": None,
                "lang": "en", "doi": None, "url": "u", "cited_by": 0,
                "countries": ["RU"], "institutions": [], "authors": [],
                "concepts": [], "domain": "d", "harvested_at": "2026-09-09"}

    works = [работа("p1", "preprint"), работа("p2", "preprint"),
             работа("a1", "article"), работа("a2", "article")]
    links = [{"cand_id": "препринты", "doc_id": "p1", "weight": 1.0},
             {"cand_id": "препринты", "doc_id": "p2", "weight": 1.0},
             {"cand_id": "статьи", "doc_id": "a1", "weight": 1.0},
             {"cand_id": "статьи", "doc_id": "a2", "weight": 1.0}]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")

    ряды = year_counts(tmp_path, tmp_path / "works.parquet")
    assert ряды["препринты"][2024] == 3     # 2 x 1.4 = 2.8
    assert ряды["статьи"][2024] == 2        # 2 x 1.0


def test_документы_берутся_из_нынешней_волны_термина(tmp_path):
    """У state space model старая жизнь — теория управления, новая — Mamba.
    Скоринг нашёл взлёт 2025 (Mamba), а документы по строке приходили из
    2018 года про угольную электростанцию. Карточка описывала не то,
    что оценка. Отбор документов обязан начинаться с года взлёта."""
    def работа(doc_id, year):
        return {"doc_id": doc_id, "source": "openalex", "doc_type": "article",
                "title": "state space model", "abstract": None, "year": year,
                "date": None, "lang": "en", "doi": None, "url": "u", "cited_by": 5,
                "countries": ["RU"], "institutions": [], "authors": [],
                "concepts": [], "domain": "d", "harvested_at": "2026-09-09"}

    works = [работа("старый", 2018), работа("новый", 2025), работа("новее", 2026)]
    links = [{"cand_id": "ssm", "doc_id": d["doc_id"], "weight": 1.0} for d in works]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")

    все = top_docs(tmp_path, tmp_path / "works.parquet", "ssm")
    assert "старый" in все
    волна = top_docs(tmp_path, tmp_path / "works.parquet", "ssm", since=2025)
    assert волна == ["новее", "новый"]
