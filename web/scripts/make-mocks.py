"""Создаёт локальный ответ фронтенда из демонстрационного индекса."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "data" / "index" / "golden" / "trends.parquet"
WORKS_PATH = ROOT / "data" / "index" / "golden" / "works.parquet"
REJECTED_PATH = ROOT / "data" / "index" / "golden" / "rejected.parquet"


def output_path(as_of: int) -> Path:
    """Сохраняет основной срез в прежний файл, исторические — в отдельные."""
    filename = "trends.json" if as_of == 2026 else f"trends-{as_of}.json"
    return ROOT / "web" / "mocks" / filename


def make_mocks(as_of: int) -> None:
    """Собирает ответ POST /api/v1/trends для витрины golden."""
    if not INDEX_PATH.is_file():
        raise FileNotFoundError(f"Не найден демонстрационный индекс: {INDEX_PATH}")

    rejected: list[dict[str, object]] = []
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(
            """
            SELECT *
            FROM read_parquet(?)
            WHERE as_of = ?
            ORDER BY rank
            """,
            [str(INDEX_PATH), as_of],
        )
        columns = [description[0] for description in result.description]
        rows = result.fetchall()
        works = connection.execute("SELECT * FROM read_parquet(?)", [str(WORKS_PATH)])
        work_columns = [description[0] for description in works.description]
        documents = {}
        for values in works.fetchall():
            work = dict(zip(work_columns, values, strict=True))
            documents[work["doc_id"]] = {
                "doc_id": work["doc_id"],
                "title": work["title"],
                "url": work["url"],
                "year": int(work["year"]),
                "type": work["doc_type"],
                "date": work.get("date"),
                "source_type": work.get("source_type") or work["doc_type"],
                "lang": work.get("lang"),
                "trust_level": work.get("trust_level"),
            }
        if REJECTED_PATH.is_file():
            rejected_result = connection.execute(
                "SELECT label, reason, n_docs FROM read_parquet(?) WHERE as_of = ?",
                [str(REJECTED_PATH), as_of],
            )
            rejected_columns = [description[0] for description in rejected_result.description]
            rejected = [
                dict(zip(rejected_columns, values, strict=True))
                for values in rejected_result.fetchall()
            ]

    if not rows:
        raise ValueError(f"В golden нет трендов для среза {as_of}")

    trends = [_trend(dict(zip(columns, row, strict=True)), documents) for row in rows]
    payload = {
        "domain": {
            "query": "golden",
            "resolved": "golden",
            "n_works": _n_works(),
        },
        "as_of": as_of,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology_version": "1.0",
        "stats": {
            "n_sources_polled": _n_works(),
            "n_candidates": len(trends) + len(rejected),
            "n_rejected": len(rejected),
            "n_confident": sum(trend["confidence_pct"] > 75 for trend in trends),
        },
        "trends": trends,
        "rejected": rejected,
    }

    path = output_path(as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _n_works() -> int:
    with duckdb.connect(":memory:") as connection:
        result = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(WORKS_PATH)])
        return int(result.fetchone()[0])


def _trend(row: dict[str, object], documents: dict[str, dict[str, object]]) -> dict[str, object]:
    years = row["years"]
    counts = row["counts"]
    frequencies = row["freq_per_million"]
    return {
        "trend_id": row["trend_id"],
        "rank": int(row["rank"]),
        "title": row["label"],
        "label_en": row["label"],
        "aliases": list(row["aliases"] or []),
        "emergence_score": float(row["emergence_score"]),
        "confidence_pct": round(float(row["emergence_score"]) * 100),
        "components": {
            "novelty": float(row["c_novelty"]),
            "growth": float(row["c_growth"]),
            "accel": float(row["c_accel"]),
            "burst": float(row["c_burst"]),
            "diffusion": float(row["c_diffusion"]),
        },
        "evidence": {
            "first_mention": row["first_mention"],
            "takeoff_year": row["takeoff_year"],
            "series": [
                {"year": int(year), "count": int(count), "freq_per_million": float(freq)}
                for year, count, freq in zip(years, counts, frequencies, strict=True)
            ],
            "n_docs": int(row["n_docs"]),
            "n_countries": int(row["n_countries"]),
            "n_orgs": _optional_int(row["n_orgs"]),
            "n_patents": _optional_int(row["n_patents"]),
        },
        "sources": [
            documents[doc_id]
            for doc_id in row["top_doc_ids"]
            if doc_id in documents and documents[doc_id]["url"]
        ],
        "stage": row["stage"],
        "confidence": row["confidence"],
        "series_granularity": row.get("series_granularity") or "year",
    }


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=int, default=2026, help="Год среза")
    args = parser.parse_args()
    make_mocks(args.as_of)


if __name__ == "__main__":
    main()
