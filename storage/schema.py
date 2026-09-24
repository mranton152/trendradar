"""DDL для PostgreSQL, выведенный из контрактов.

Каждая таблица контракта получает колонку dataset — имя набора (папки индекса:
golden, ai-full, живой запрос). Перезагрузка набора заменяет только его строки.
"""
import re

import pyarrow as pa

from contracts.schemas import SCHEMAS

# Имя набора совпадает с именем папки; то же правило, что в api/store.py.
DATASET_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

# Порядок важен только для читаемости DDL: сырые данные, потом результаты.
TABLES = ("works", "candidates", "cand_docs", "trends", "rejected", "cards", "features")

# Где лежит файл каждой таблицы относительно data/. {d} — имя набора.
PATHS = {
    "works": ("corpus/{d}/works.parquet", "index/{d}/works.parquet"),
    "candidates": ("index/{d}/candidates.parquet",),
    "cand_docs": ("index/{d}/cand_docs.parquet",),
    "trends": ("index/{d}/trends.parquet",),
    "rejected": ("index/{d}/rejected.parquet",),
    "cards": ("index/{d}/cards.parquet",),
    "features": ("features/{d}/features.parquet",),
}

# Естественные ключи. Нужны, чтобы повтор строки в файле был ошибкой загрузки,
# а не тихим дублем в базе.
KEYS = {
    "works": ("doc_id",),
    "candidates": ("cand_id",),
    "cand_docs": ("cand_id", "doc_id"),
    "trends": ("trend_id",),
    "rejected": ("cand_id", "as_of"),
    "cards": ("trend_id",),
    "features": ("cand_id", "as_of"),
}

_SCALAR = {
    pa.string(): "text",
    pa.int32(): "integer",
    pa.int64(): "bigint",
    pa.float32(): "real",
    pa.float64(): "double precision",
    pa.bool_(): "boolean",
}


def pg_type(t: pa.DataType) -> str:
    """Тип Postgres для типа arrow. Неизвестный тип — ошибка, а не молчаливый text."""
    if pa.types.is_list(t):
        return pg_type(t.value_type) + "[]"
    for arrow, pg in _SCALAR.items():
        if t.equals(arrow):
            return pg
    raise TypeError(f"нет соответствия в Postgres для типа {t}")


def create_table(name: str) -> str:
    schema = SCHEMAS[name]
    cols = ["    dataset text NOT NULL"]
    for f in schema:
        null = "" if f.nullable else " NOT NULL"
        cols.append(f"    {f.name} {pg_type(f.type)}{null}")
    key = ", ".join(("dataset", *KEYS[name]))
    cols.append(f"    PRIMARY KEY ({key})")
    return f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(cols) + "\n);"


LOADS = """CREATE TABLE IF NOT EXISTS loads (
    dataset   text NOT NULL,
    tbl       text NOT NULL,
    n_rows    bigint NOT NULL,
    source    text NOT NULL,
    sha256    text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset, tbl)
);"""

# Индексы под запросы, которые реально задают: выдача по срезу и источники тренда.
INDEXES = (
    "CREATE INDEX IF NOT EXISTS trends_rank ON trends (dataset, as_of, rank);",
    "CREATE INDEX IF NOT EXISTS cand_docs_doc ON cand_docs (dataset, doc_id);",
    "CREATE INDEX IF NOT EXISTS works_year ON works (dataset, year);",
)


def add_columns(name: str) -> list[str]:
    """Колонки, добавленные в контракт после создания таблицы.

    Новые поля контракта всегда nullable (иначе старые файлы не прочитаются),
    поэтому ADD COLUMN без NOT NULL безопасен на заполненной таблице.
    """
    return [
        f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS {f.name} {pg_type(f.type)};"
        for f in SCHEMAS[name] if f.nullable
    ]


def ddl() -> str:
    parts = [create_table(t) for t in TABLES]
    alters = [a for t in TABLES for a in add_columns(t)]
    return "\n\n".join([*parts, LOADS, *INDEXES, "\n".join(alters)]) + "\n"


if __name__ == "__main__":
    print(ddl())
