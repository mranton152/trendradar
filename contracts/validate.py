#!/usr/bin/env python3
"""Проверка parquet-файла на соответствие контракту.

    python contracts/validate.py data/corpus/ai/works.parquet --schema works

Выход 0 - файл соответствует контракту, можно мержить.
Выход 1 - расхождение, PR не пройдёт CI.
"""
import argparse
import sys

import pyarrow.parquet as pq

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from schemas import SCHEMAS  # noqa: E402


def check(path: str, name: str) -> list:
    expected = SCHEMAS[name]
    actual = pq.read_schema(path)
    problems = []

    exp_fields = {f.name: f for f in expected}
    act_fields = {f.name: f for f in actual}

    for fname, f in exp_fields.items():
        if fname not in act_fields:
            if f.nullable:
                continue   # поле добавлено в контракт позже файла - допустимо, читается как null
            problems.append(f"нет обязательной колонки '{fname}' ({f.type})")
            continue
        if not f.type.equals(act_fields[fname].type):
            problems.append(
                f"колонка '{fname}': ожидался тип {f.type}, найден {act_fields[fname].type}")

    extra = set(act_fields) - set(exp_fields)
    if extra:
        problems.append(
            f"лишние колонки {sorted(extra)} — их нет в контракте. "
            f"Добавление полей идёт через PR в contracts/schemas.py")

    # обязательные поля не должны содержать null
    tbl = pq.read_table(path, columns=[f.name for f in expected if not f.nullable
                                       and f.name in act_fields])
    for col in tbl.column_names:
        n_null = tbl.column(col).null_count
        if n_null:
            problems.append(f"колонка '{col}' обязательная, но содержит {n_null} null")

    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--schema", required=True, choices=sorted(SCHEMAS))
    args = ap.parse_args()

    problems = check(args.path, args.schema)
    if problems:
        print(f"✗ {args.path} не соответствует контракту '{args.schema}':")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    n = pq.read_metadata(args.path).num_rows
    print(f"✓ {args.path} соответствует контракту '{args.schema}' ({n} строк)")


if __name__ == "__main__":
    main()
