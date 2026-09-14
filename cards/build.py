"""Стадия cards: тренды → текстовые карточки с обязательной проверкой цитат.

Запуск: python -m cards.build --domain golden --as-of 2026
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cards.llm import LLM
from cards.prompt import собрать
from cards.verify import проверить_цитаты
from contracts.schemas import CARDS

ROOT = Path(__file__).resolve().parents[1]
TITLE_RU_OVERRIDES = {"foundation model": "Фундаментальные модели"}


def _index_dir(domain: str) -> Path:
    """Возвращает каталог существующего домена и не допускает выхода из data/index."""
    index_root = ROOT / "data" / "index"
    known_domains = {path.name for path in index_root.iterdir() if path.is_dir()}
    if domain not in known_domains:
        raise ValueError(f"Домен '{domain}' отсутствует в data/index")
    return index_root / domain


def _read_trends(
    connection: duckdb.DuckDBPyConnection, index_dir: Path, as_of: int
) -> list[dict[str, Any]]:
    result = connection.execute(
        "SELECT * FROM read_parquet(?) WHERE as_of = ? ORDER BY rank",
        [str(index_dir / "trends.parquet"), as_of],
    )
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _read_documents(
    connection: duckdb.DuckDBPyConnection, works_path: Path, doc_ids: list[str]
) -> list[dict[str, Any]]:
    if not doc_ids:
        return []
    result = connection.execute(
        """
        SELECT doc_id, title, abstract, year
        FROM read_parquet(?)
        WHERE doc_id = ANY(?)
        """,
        [str(works_path), doc_ids],
    )
    columns = [column[0] for column in result.description]
    documents = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    by_id = {document["doc_id"]: document for document in documents}
    return [by_id[doc_id] for doc_id in doc_ids if doc_id in by_id]


def _card_row(
    trend: dict[str, Any], card: dict[str, Any], coverage: float, llm: LLM
) -> dict[str, Any]:
    """Приводит очищенный ответ модели к единой схеме CARDS."""
    case_type = card.get("case_type")
    return {
        "trend_id": trend["trend_id"],
        "title_ru": TITLE_RU_OVERRIDES.get(trend["label"], card.get("title_ru") or trend["label"]),
        "problem": card.get("problem", ""),
        "problem_docs": card.get("problem_docs", []),
        "advantage": card.get("advantage", ""),
        "advantage_docs": card.get("advantage_docs", []),
        "case_type": case_type if case_type in {"research", "company"} else "research",
        "case_name": card.get("case_name", ""),
        "case_text": card.get("case_text", ""),
        "case_docs": card.get("case_docs", []),
        # В CARDS нет fintech_note_docs, поэтому неподтверждаемое LLM-утверждение не пишем.
        "fintech_note": None,
        "citation_coverage": float(coverage),
        "model": f"{llm.backend}:{llm.model}",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def build(domain: str, as_of: int, llm: LLM | None = None) -> int:
    """Строит cards.parquet и возвращает число созданных карточек."""
    index_dir = _index_dir(domain)
    trends_path = index_dir / "trends.parquet"
    if not trends_path.is_file():
        raise FileNotFoundError(f"Не найден индекс трендов: {trends_path}")

    corpus_path = ROOT / "data" / "corpus" / domain / "works.parquet"
    works_path = corpus_path if corpus_path.is_file() else index_dir / "works.parquet"
    if not works_path.is_file():
        raise FileNotFoundError(f"Не найден корпус документов: {works_path}")

    model = llm or LLM()
    rows: list[dict[str, Any]] = []
    with duckdb.connect(":memory:") as connection:
        for trend in _read_trends(connection, index_dir, as_of):
            documents = _read_documents(connection, works_path, list(trend["top_doc_ids"]))
            prompt = собрать(trend, documents)
            try:
                raw_card = model.json(prompt)
            except (json.JSONDecodeError, ValueError) as exc:
                sys.stderr.write(
                    f"[cards] {trend['label'][:40]:<40} повтор: некорректный JSON ({exc})\n"
                )
                raw_card = model.json(prompt)
            clean_card, coverage = проверить_цитаты(
                raw_card, {document["doc_id"] for document in documents}
            )
            sys.stderr.write(f"[cards] {trend['label'][:40]:<40} покрытие {coverage:.0%}\n")
            rows.append(_card_row(trend, clean_card, coverage, model))

    output_path = index_dir / "cards.parquet"
    existing_rows = pq.read_table(output_path).to_pylist() if output_path.is_file() else []
    new_ids = {row["trend_id"] for row in rows}
    preserved_rows = [row for row in existing_rows if row["trend_id"] not in new_ids]
    all_rows = preserved_rows + rows
    pq.write_table(pa.Table.from_pylist(all_rows, schema=CARDS), output_path, compression="zstd")
    average_coverage = sum(row["citation_coverage"] for row in rows) / max(1, len(rows))
    sys.stderr.write(f"[готово] {len(rows)} карточек, среднее покрытие {average_coverage:.0%}\n")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--as-of", type=int, default=2026)
    args = parser.parse_args()
    build(args.domain, args.as_of)


if __name__ == "__main__":
    main()
