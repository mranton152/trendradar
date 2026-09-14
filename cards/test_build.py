import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cards import build as build_module


class FakeLLM:
    backend = "fake"
    model = "test"

    def json(self, prompt: str) -> dict[str, object]:
        assert "[openalex:W1]" in prompt
        return {
            "title_ru": "Тестовый тренд",
            "problem": "Подтверждённая проблема",
            "problem_docs": ["openalex:W1"],
            "advantage": "Неподтверждённое преимущество",
            "advantage_docs": ["openalex:W404"],
            "case_type": "company",
            "case_name": "Компания из документа",
            "case_text": "Подтверждённый кейс",
            "case_docs": ["openalex:W1"],
        }


class FlakyLLM(FakeLLM):
    calls = 0

    def json(self, prompt: str) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            raise json.JSONDecodeError("битый JSON", "{", 1)
        return super().json(prompt)


def test_build_removes_unsupported_claims(tmp_path: Path, monkeypatch) -> None:
    index_dir = tmp_path / "data" / "index" / "demo"
    index_dir.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "trend_id": ["t:demo:2026:01"],
                "as_of": [2026],
                "rank": [1],
                "label": ["demo trend"],
                "takeoff_year": [2025],
                "n_docs": [1],
                "n_countries": [1],
                "top_doc_ids": [["openalex:W1"]],
            }
        ),
        index_dir / "trends.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "doc_id": ["openalex:W1"],
                "title": ["Подтверждающий документ"],
                "abstract": ["Текст документа"],
                "year": [2026],
            }
        ),
        index_dir / "works.parquet",
    )
    monkeypatch.setattr(build_module, "ROOT", tmp_path)

    assert build_module.build("demo", 2026, llm=FakeLLM()) == 1

    row = pq.read_table(index_dir / "cards.parquet").to_pylist()[0]
    assert row["problem"] == "Подтверждённая проблема"
    assert row["advantage"] == ""
    assert row["advantage_docs"] == []
    assert row["case_docs"] == ["openalex:W1"]
    assert row["citation_coverage"] == pytest.approx(2 / 3)


def test_build_preserves_cards_from_another_snapshot(tmp_path: Path, monkeypatch) -> None:
    index_dir = tmp_path / "data" / "index" / "demo"
    index_dir.mkdir(parents=True)
    trends = pa.table(
        {
            "trend_id": ["t:demo:2021:01", "t:demo:2026:01"],
            "as_of": [2021, 2026],
            "rank": [1, 1],
            "label": ["demo trend", "foundation model"],
            "takeoff_year": [2020, 2025],
            "n_docs": [1, 1],
            "n_countries": [1, 1],
            "top_doc_ids": [["openalex:W1"], ["openalex:W1"]],
        }
    )
    pq.write_table(trends, index_dir / "trends.parquet")
    pq.write_table(
        pa.table(
            {
                "doc_id": ["openalex:W1"],
                "title": ["Подтверждающий документ"],
                "abstract": ["Текст документа"],
                "year": [2026],
            }
        ),
        index_dir / "works.parquet",
    )
    monkeypatch.setattr(build_module, "ROOT", tmp_path)

    build_module.build("demo", 2026, llm=FakeLLM())
    build_module.build("demo", 2021, llm=FakeLLM())

    rows = pq.read_table(index_dir / "cards.parquet").to_pylist()
    assert {row["trend_id"] for row in rows} == {"t:demo:2021:01", "t:demo:2026:01"}
    title_2026 = next(row["title_ru"] for row in rows if row["trend_id"] == "t:demo:2026:01")
    assert title_2026 == "Фундаментальные модели"


def test_build_retries_once_after_invalid_model_json(tmp_path: Path, monkeypatch) -> None:
    index_dir = tmp_path / "data" / "index" / "demo"
    index_dir.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "trend_id": ["t:demo:2026:01"],
                "as_of": [2026],
                "rank": [1],
                "label": ["demo trend"],
                "takeoff_year": [2025],
                "n_docs": [1],
                "n_countries": [1],
                "top_doc_ids": [["openalex:W1"]],
            }
        ),
        index_dir / "trends.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "doc_id": ["openalex:W1"],
                "title": ["Документ"],
                "abstract": ["Текст"],
                "year": [2026],
            }
        ),
        index_dir / "works.parquet",
    )
    monkeypatch.setattr(build_module, "ROOT", tmp_path)
    llm = FlakyLLM()

    assert build_module.build("demo", 2026, llm=llm) == 1
    assert llm.calls == 2
