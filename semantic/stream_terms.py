"""Точная потоковая выгрузка терминов полного корпуса; SQLite ограничивает RAM.

Манифест ingest рядом с works обязателен. Публикация — переименование новой
папки; существующий output не перезаписывается. Незавершённая stage сохраняется
для диагностики, но автоматического продолжения после сбоя пока нет.
"""

import argparse
import hashlib
import json
import logging
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, CANDIDATES, WORKS
from semantic.embed import MODEL, REVISION
from semantic.filter import technology_reason
from semantic.terms import _MAX_TITLE_CHARS, _MAX_TITLE_TOKENS, ngrams

LOG = logging.getLogger(__name__)


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rows(path, schema, cursor, convert, batch_size):
    count = 0
    with pq.ParquetWriter(path, schema, compression="zstd") as writer:
        while rows := cursor.fetchmany(batch_size):
            writer.write_table(
                pa.Table.from_pylist([convert(row) for row in rows], schema=schema)
            )
            count += len(rows)
    return count


def export_terms(works, output, domain, as_of=2026, min_docs=20, batch_size=1024):
    """Два прохода parquet, дисковые частоты/связи, атомарная публикация папки."""
    for name, value in (
        ("min_docs", min_docs),
        ("batch_size", batch_size),
        ("as_of", as_of),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} должен быть положительным целым")
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain не должен быть пустым")
    works, output = Path(works).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    manifest_path = works.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parquet = pq.ParquetFile(works)
    if not parquet.schema_arrow.equals(WORKS, check_metadata=False):
        raise ValueError("Схема works не соответствует WORKS")
    if not str(manifest.get("config", {}).get("as_of", "")).startswith(f"{as_of}-"):
        raise ValueError("as_of не совпадает с manifest")
    if manifest.get("status") != "complete":
        raise ValueError("Для полного корпуса нужен complete manifest")
    if manifest.get("config", {}).get("domain") != domain:
        raise ValueError("domain не совпадает с manifest")
    if manifest.get("n_works") != parquet.metadata.num_rows:
        raise ValueError("n_works не совпадает с parquet")
    LOG.info("Проверка SHA256 полного корпуса")
    source_hash = _hash(works)
    if manifest.get("sha256") != source_hash:
        raise ValueError("sha256 не совпадает с manifest")
    source_stat = (works.stat().st_size, works.stat().st_mtime_ns)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    db_path = stage / "terms.sqlite"
    db = sqlite3.connect(db_path)
    accepted_reason = lru_cache(maxsize=65536)(technology_reason)
    try:
        db.executescript("""
            PRAGMA cache_size=-32768;
            PRAGMA temp_store=FILE;
            CREATE TABLE docs (doc_id TEXT PRIMARY KEY) WITHOUT ROWID;
            CREATE TABLE counts (term TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID;
            CREATE TABLE accepted (term TEXT PRIMARY KEY, cand_id TEXT NOT NULL, n INTEGER NOT NULL)
                WITHOUT ROWID;
            CREATE TABLE links (cand_id TEXT, doc_id TEXT, PRIMARY KEY(cand_id, doc_id))
                WITHOUT ROWID;
            CREATE TABLE incoming (term TEXT, doc_id TEXT);
        """)
        n_documents = 0
        for batch_index, batch in enumerate(
            parquet.iter_batches(
                batch_size=batch_size, columns=["doc_id", "title", "domain", "year"]
            ),
            1,
        ):
            counts = Counter()
            for row in batch.to_pylist():
                if row["domain"] != domain:
                    raise ValueError("domain строки не совпадает с запросом")
                if not isinstance(row["year"], int) or row["year"] > as_of:
                    raise ValueError("Год строки выходит за as_of")
                if not isinstance(row["doc_id"], str) or not row["doc_id"]:
                    raise ValueError("doc_id должен быть непустой строкой")
                if not isinstance(row["title"], str):
                    raise TypeError("title должен быть строкой")
                try:
                    db.execute("INSERT INTO docs VALUES (?)", (row["doc_id"],))
                except sqlite3.IntegrityError as exc:
                    raise ValueError("doc_id должен быть уникальным") from exc
                counts.update(
                    term
                    for term in set(ngrams(row["title"]))
                    if accepted_reason(term) is None
                )
            db.executemany(
                "INSERT INTO counts VALUES (?, ?) ON CONFLICT(term) DO UPDATE SET n=n+excluded.n",
                counts.items(),
            )
            db.commit()
            n_documents += batch.num_rows
            (stage / "checkpoint.json").write_text(
                json.dumps(
                    {
                        "pass": 1,
                        "batches": batch_index,
                        "documents": n_documents,
                        "source_sha256": source_hash,
                        "resumable": False,
                    }
                ),
                encoding="utf-8",
            )
            if batch_index % 100 == 0:
                LOG.info("Проход 1: %s документов", n_documents)
        for term, frequency in db.execute(
            "SELECT term,n FROM counts WHERE n>=? ORDER BY term", (min_docs,)
        ):
            digest = hashlib.sha256((domain + "\0" + term).encode()).hexdigest()[:24]
            db.execute(
                "INSERT INTO accepted VALUES (?, ?, ?)",
                (term, f"t:{domain}:{digest}", frequency),
            )
        db.commit()
        n_candidates = _write_rows(
            stage / "candidates.parquet",
            CANDIDATES,
            db.execute("SELECT term,cand_id,n FROM accepted ORDER BY term"),
            lambda row: {
                "cand_id": row[1],
                "kind": "term",
                "label": row[0],
                "aliases": [],
                "top_terms": [row[0]],
                "emb_row": None,
                "n_docs": row[2],
                "domain": domain,
            },
            batch_size,
        )
        for batch_index, batch in enumerate(
            parquet.iter_batches(batch_size=batch_size, columns=["doc_id", "title"]), 1
        ):
            db.execute("DELETE FROM incoming")
            db.executemany(
                "INSERT INTO incoming VALUES (?, ?)",
                (
                    (term, row["doc_id"])
                    for row in batch.to_pylist()
                    for term in set(ngrams(row["title"]))
                    if accepted_reason(term) is None
                ),
            )
            db.execute(
                "INSERT INTO links SELECT a.cand_id,i.doc_id FROM incoming i "
                "JOIN accepted a ON a.term=i.term"
            )
            db.commit()
            if batch_index % 100 == 0:
                LOG.info("Проход 2: %s пакетов", batch_index)
        n_links = _write_rows(
            stage / "cand_docs.parquet",
            CAND_DOCS,
            db.execute("SELECT cand_id,doc_id FROM links ORDER BY cand_id,doc_id"),
            lambda row: {"cand_id": row[0], "doc_id": row[1], "weight": 1.0},
            batch_size,
        )
        if (
            db.execute("SELECT COALESCE(SUM(n),0) FROM accepted").fetchone()[0]
            != n_links
        ):
            raise ValueError("Сумма n_docs не совпадает с числом связей")
        if db.execute(
            "SELECT 1 FROM accepted a LEFT JOIN "
            "(SELECT cand_id, COUNT(*) n FROM links GROUP BY cand_id) l "
            "ON a.cand_id=l.cand_id WHERE a.n != COALESCE(l.n,0) LIMIT 1"
        ).fetchone():
            raise ValueError("n_docs кандидата не совпадает со связями")
        if source_stat != (works.stat().st_size, works.stat().st_mtime_ns):
            raise ValueError("Исходный parquet изменился во время обработки")
        np.save(stage / "embeddings.npy", np.empty((0, 1024), dtype=np.float32))
        meta = {
            "domain": domain,
            "domain_query": domain.replace("-", " "),
            "built_at": datetime.now(UTC).isoformat(),
            "stages": {"semantic": "terms-only"},
            "embedding_model": MODEL,
            "embedding_revision": REVISION,
            "methodology_version": "1.0",
            "corpus_sha256": source_hash,
            "max_title_chars": _MAX_TITLE_CHARS,
            "max_title_tokens": _MAX_TITLE_TOKENS,
            "as_of": as_of,
            "corpus_scope": "full",
            "n_works": n_documents,
            "n_candidates": n_candidates,
            "n_links": n_links,
            "min_docs": min_docs,
            "method": "title_ngrams_2_4_lexical_v1",
            "source_works": str(works),
            "source_sha256": source_hash,
            "source_manifest": manifest,
            "source_manifest_path": str(manifest_path),
            "batch_size": batch_size,
            "lexical_prefilter": True,
            "embeddings_scope": "none_terms_only",
        }
        (stage / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        db.close()
        accepted_reason.cache_clear()
        parquet.close()
    db_path.unlink()
    (stage / "checkpoint.json").unlink(missing_ok=True)
    stage.rename(output)
    LOG.info("Опубликовано: %s кандидатов, %s связей", n_candidates, n_links)
    return meta


def main():
    """CLI для независимого запуска стадии без загрузки эмбеддингов."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--works", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--as-of", type=int, default=2026)
    parser.add_argument("--min-docs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1024)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    export_terms(
        args.works, args.output, args.domain, args.as_of, args.min_docs, args.batch_size
    )


if __name__ == "__main__":
    main()
