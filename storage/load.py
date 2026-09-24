"""Загрузка набора parquet-файлов в PostgreSQL.

    uv run python -m storage.load --dataset golden
    uv run python -m storage.load --all
    uv run python -m storage.load --status

Набор загружается целиком в одной транзакции: либо все его таблицы заменены
новыми строками, либо база осталась как была. Перед загрузкой каждый файл
проверяется контрактом — файл, который не прошёл бы CI, в базу не попадает.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

from contracts.schemas import SCHEMAS
from contracts.validate import check
from storage.schema import DATASET_NAME, PATHS, TABLES, ddl, pg_type

DATA = Path(__file__).resolve().parents[1] / "data"
DSN_ENV = "TRENDRADAR_PG_DSN"
# 55432, а не 5432: на машинах команды 5432 и 5433 заняты чужими проектами.
DEFAULT_DSN = "postgresql://trendradar:trendradar@localhost:55432/trendradar"
BATCH = 50_000


class ОшибкаЗагрузки(Exception):
    pass


def dsn() -> str:
    return os.environ.get(DSN_ENV, DEFAULT_DSN)


def файлы_набора(dataset: str, data: Path = DATA) -> dict[str, Path]:
    """Таблица → файл. Берётся первый существующий путь из PATHS."""
    if not DATASET_NAME.fullmatch(dataset):
        raise ОшибкаЗагрузки(f"недопустимое имя набора: {dataset!r}")
    out = {}
    for table in TABLES:
        for pattern in PATHS[table]:
            path = data / pattern.format(d=dataset)
            if path.is_file():
                out[table] = path
                break
    return out


def все_наборы(data: Path = DATA) -> list[str]:
    names = set()
    for sub in ("index", "corpus", "features"):
        root = data / sub
        if root.is_dir():
            names |= {p.name for p in root.iterdir()
                      if p.is_dir() and DATASET_NAME.fullmatch(p.name)}
    return sorted(names)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def строки(path: Path, table: str):
    """Строки файла в порядке колонок контракта.

    Поле, добавленное в контракт позже файла, отдаётся как NULL — так же, как
    его читает валидатор контракта.
    """
    names = [f.name for f in SCHEMAS[table]]
    pf = pq.ParquetFile(path)
    present = [n for n in names if n in pf.schema_arrow.names]
    for batch in pf.iter_batches(batch_size=BATCH, columns=present):
        cols = {n: batch.column(n).to_pylist() for n in present}
        for i in range(batch.num_rows):
            yield [cols[n][i] if n in cols else None for n in names]


def загрузить_таблицу(cur: psycopg.Cursor, dataset: str, table: str, path: Path) -> int:
    problems = check(str(path), table)
    if problems:
        raise ОшибкаЗагрузки(f"{path} не соответствует контракту '{table}': "
                             + "; ".join(problems))
    fields = list(SCHEMAS[table])
    cols = ", ".join(["dataset", *(f.name for f in fields)])
    cur.execute(f"DELETE FROM {table} WHERE dataset = %s", [dataset])
    n = 0
    with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as copy:
        copy.set_types(["text", *(pg_type(f.type) for f in fields)])
        for row in строки(path, table):
            copy.write_row([dataset, *row])
            n += 1
    cur.execute(
        """INSERT INTO loads (dataset, tbl, n_rows, source, sha256)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (dataset, tbl) DO UPDATE
           SET n_rows = EXCLUDED.n_rows, source = EXCLUDED.source,
               sha256 = EXCLUDED.sha256, loaded_at = now()""",
        [dataset, table, n, str(path.relative_to(path.parents[2])), sha256(path)],
    )
    return n


def загрузить_набор(conn: psycopg.Connection, dataset: str, data: Path = DATA) -> dict[str, int]:
    files = файлы_набора(dataset, data)
    if not files:
        raise ОшибкаЗагрузки(f"набор {dataset!r}: в {data} нет ни одного файла")
    counts = {}
    # Схема обновляется отдельной короткой транзакцией: ALTER TABLE берёт
    # эксклюзивную блокировку до коммита, и внутри загрузки большого набора
    # она минутами не давала бы читать никакие наборы.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(ddl())
    with conn.transaction(), conn.cursor() as cur:
        # Таблица, которой в наборе больше нет, не должна остаться со старыми строками.
        for table in TABLES:
            if table not in files:
                cur.execute(f"DELETE FROM {table} WHERE dataset = %s", [dataset])
                cur.execute("DELETE FROM loads WHERE dataset = %s AND tbl = %s",
                            [dataset, table])
        for table, path in files.items():
            counts[table] = загрузить_таблицу(cur, dataset, table, path)
    return counts


def статус(conn: psycopg.Connection) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('loads')")
        if cur.fetchone()[0] is None:
            return []
        cur.execute("SELECT dataset, tbl, n_rows, loaded_at FROM loads ORDER BY 1, 2")
        return cur.fetchall()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dataset", help="имя набора: golden, ai-full, живой запрос")
    g.add_argument("--all", action="store_true", help="все наборы из data/")
    g.add_argument("--status", action="store_true", help="что сейчас лежит в базе")
    args = ap.parse_args(argv)

    try:
        conn = psycopg.connect(dsn())
    except psycopg.OperationalError as exc:
        print(f"✗ нет соединения с Postgres ({DSN_ENV}): {exc}\n"
              f"  поднять: docker compose up -d postgres", file=sys.stderr)
        return 1

    with conn:
        if args.status:
            rows = статус(conn)
            if not rows:
                print("· база пуста: ни один набор не загружен")
            for dataset, table, n, at in rows:
                print(f"{dataset:<20} {table:<12} {n:>10} строк  {at:%Y-%m-%d %H:%M}")
            return 0
        datasets = все_наборы() if args.all else [args.dataset]
        failed = False
        for dataset in datasets:
            try:
                counts = загрузить_набор(conn, dataset)
            except (ОшибкаЗагрузки, psycopg.Error) as exc:
                print(f"✗ {dataset}: {exc}", file=sys.stderr)
                failed = True
                continue
            summary = ", ".join(f"{t} {n}" for t, n in counts.items())
            print(f"✓ {dataset}: {summary}")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
