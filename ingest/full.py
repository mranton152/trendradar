"""Полный корпус OpenAlex: курсоры, атомарные страницы и докачка."""
import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import WORKS
from ingest.http import Client
from ingest.normalize import normalize
from ingest.sources.openalex import FIELDS


def atomic_json(path, value):
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def finalize(output, state):
    import duckdb

    # DuckDB сбрасывает сортировку на диск; Python держит только один батч.
    paths = [str(output / "pages" / f"{i:09d}.parquet")
             for i in range(state["pages"])]
    temp = output / "works.parquet.tmp"
    count = 0
    counts = {}
    with duckdb.connect() as connection:
        connection.execute("SET memory_limit = '4GB'")
        connection.execute("SET threads = 2")
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("SET temp_directory = ?", [str(output / "duckdb-tmp")])
        with pq.ParquetWriter(temp, WORKS, compression="zstd") as writer:
            if paths:
                reader = connection.execute(
                    "SELECT * EXCLUDE (filename, rn) FROM ("
                    "SELECT *, row_number() OVER (PARTITION BY doc_id ORDER BY filename) rn "
                    "FROM read_parquet(?, filename=true)) WHERE rn = 1 "
                    "ORDER BY year, doc_id", [paths]
                ).fetch_record_batch(8192)
                for batch in reader:
                    table = pa.Table.from_batches([batch]).cast(WORKS)
                    writer.write_table(table)
                    count += table.num_rows
                    for year in table["year"].to_pylist():
                        counts[str(year)] = counts.get(str(year), 0) + 1
    digest = hashlib.sha256()
    with temp.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    temp.replace(output / "works.parquet")
    state.update(status="complete", n_works=count, counts_by_year=counts,
                 duplicates=state["accepted"] - count, sha256=digest.hexdigest())
    atomic_json(output / "manifest.json", state)


def harvest(client, output, domain, years, as_of, max_pages=None, per_page=100,
            concept_id=None):
    output = Path(output)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", domain):
        raise ValueError("Домен должен быть slug")
    if not re.fullmatch(r"\d{4}-\d{4}", years):
        raise ValueError("Годы должны иметь формат YYYY-YYYY")
    start, end = map(int, years.split("-"))
    cutoff = date.fromisoformat(as_of)
    if start > end or end > cutoff.year or not 1 <= per_page <= 100:
        raise ValueError("Неверные годы или размер страницы")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages должен быть положительным")
    if concept_id is not None and not re.fullmatch(r"C\d+", concept_id):
        raise ValueError("concept_id должен иметь формат C123")
    config = {"domain": domain, "years": years, "as_of": as_of, "per_page": per_page,
              "types": ["article", "preprint", "report"], "version": 1,
              "concept_id": concept_id}
    manifest = output / "manifest.json"
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding="utf-8"))
        if state["config"] != config:
            raise ValueError("Изменилась конфигурация; используйте отдельный каталог")
        if state["status"] == "complete":
            if not (output / "works.parquet").exists():
                raise ValueError("Завершённый корпус отсутствует")
            return state
    else:
        if (output / "works.parquet").exists():
            raise ValueError("Корпус без manifest: используйте отдельный каталог")
        query = domain.replace("-", " ")
        if concept_id:
            concept = client.get(f"/concepts/{concept_id}", {})
            if concept["id"].rsplit("/", 1)[-1] != concept_id:
                raise ValueError("Источник вернул другой concept_id")
        else:
            concepts = client.get("/concepts", {"search": query, "per_page": 5})["results"]
            concept = next((c for c in concepts if c["display_name"].lower() == query), None)
        if concept is None:
            raise ValueError(f"Не найден точный концепт: {query}")
        state = {"config": config, "status": "incomplete", "year": start, "cursor": "*", "pages": 0,
                     "accepted": 0, "rejected": 0, "seen": 0, "source": "OpenAlex",
                     "domain_filter": "concepts.id:" + concept["id"].rsplit("/", 1)[-1],
                     "concept_name": concept["display_name"],
                     "harvested_at": datetime.now(UTC).isoformat()}
        output.mkdir(parents=True, exist_ok=True)
        atomic_json(manifest, state)
    pages = output / "pages"
    pages.mkdir(exist_ok=True)
    fetched = 0
    while state["year"] <= end:
        if max_pages is not None and fetched >= max_pages:
            return state
        year, cursor = state["year"], state["cursor"]
        payload = client.get("/works", {
            "filter": f"{state['domain_filter']},publication_year:{year},"
                      f"type:article|preprint|report,to_publication_date:{as_of}",
            "cursor": cursor, "per_page": per_page, "select": FIELDS,
        })
        records = payload["results"]
        next_cursor = payload["meta"]["next_cursor"]
        if next_cursor == cursor or (not records and next_cursor):
            raise ValueError("Источник не продвинул курсор")
        rows, rejected = [], []
        for record in records:
            try:
                row = normalize(record, domain, state["harvested_at"])
                if row["year"] != year or (
                        row["date"] and date.fromisoformat(row["date"]) > cutoff):
                    raise ValueError("Документ вне временного среза")
                # Проверка типов до записи, чтобы одна плохая строка не блокировала страницу.
                pa.Table.from_pylist([row], schema=WORKS)
                rows.append(row)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
                rejected.append({"id": record.get("id") if isinstance(record, dict) else None,
                                 "reason": str(error)})
        page = pages / f"{state['pages']:09d}.parquet"
        temp = page.with_suffix(".parquet.tmp")
        pq.write_table(pa.Table.from_pylist(rows, schema=WORKS), temp, compression="zstd")
        temp.replace(page)
        atomic_json(page.with_suffix(".rejected.json"), rejected)
        # Курсор коммитится после страницы; при сбое та же страница перезаписывается.
        state["pages"] += 1
        state["accepted"] += len(rows)
        state["rejected"] += len(rejected)
        state["seen"] += len(records)
        state["cursor"] = next_cursor or "*"
        if not next_cursor:
            state["year"] += 1
        atomic_json(manifest, state)
        fetched += 1
        print(f"{year}: страниц {state['pages']}, строк {state['accepted']}, "
              f"отброшено {state['rejected']}", flush=True)
    finalize(output, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--years", default="2015-2026")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/cache/full-openalex"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--concept-id", help="Проверенный OpenAlex concept ID, например C58053490")
    args = parser.parse_args()
    try:
        result = harvest(Client(args.cache, offline=args.offline),
                         args.output or Path("data/corpus") / args.domain,
                         args.domain, args.years, args.as_of, args.max_pages,
                         concept_id=args.concept_id)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
