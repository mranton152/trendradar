"""CLI сборки золотого среза; полный корпус собирается отдельной задачей K-03."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import WORKS
from ingest.domain import resolve_concept
from ingest.http import Client
from ingest.sources.openalex import sample_year, select_valid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="artificial-intelligence")
    parser.add_argument("--concept-id", help="Проверенный концепт OpenAlex, например C58053490")
    parser.add_argument("--years", default="2015-2026")
    parser.add_argument("--sample", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", required=True, help="Фиксированная дата среза YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=Path("data/index/golden"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache/golden-openalex"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--exclude-file", type=Path,
                        help="JSON со списком doc_id, исключённых по аудиту URL")
    args = parser.parse_args()
    excluded = (set(json.loads(args.exclude_file.read_text(encoding="utf-8")))
                if args.exclude_file else set())
    start, end = map(int, args.years.split("-"))
    as_of = date.fromisoformat(args.as_of)
    if start > end or end > as_of.year or args.sample < end - start + 1:
        parser.error("Неверные годы или слишком маленькая выборка")
    client = Client(args.cache, offline=args.offline)
    query = args.domain.replace("-", " ")
    concept = resolve_concept(client, query, args.concept_id)
    domain_filter = "concepts.id:" + concept["id"].rsplit("/", 1)[-1]
    config = {"domain": args.domain, "years": args.years, "sample": args.sample,
              "seed": args.seed, "as_of": args.as_of, "filter": domain_filter}
    # Время сбора фиксируется рядом с кэшем, чтобы офлайн-повтор был идентичным.
    run_key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    stamp_file = args.cache / f"run-{run_key}.json"
    if stamp_file.exists():
        harvested_at = json.loads(stamp_file.read_text())["harvested_at"]
    else:
        if args.offline:
            raise FileNotFoundError("Нет метаданных исходного прогона")
        harvested_at = datetime.now(UTC).isoformat()
        args.cache.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(json.dumps({"harvested_at": harvested_at}), encoding="utf-8")
    rows, rejected = [], []
    for index, year in enumerate(range(start, end + 1)):
        count = args.sample // (end - start + 1) + (index < args.sample % (end - start + 1))
        records = sample_year(client, domain_filter, year, count + 100, args.seed, args.as_of)
        selected, skipped = select_valid(records, count, args.domain, harvested_at, excluded)
        rejected.extend(skipped)
        for row in selected:
            if row["year"] != year or (row["date"] and row["date"] > args.as_of):
                raise ValueError("Источник вернул документ вне временного среза")
            rows.append(row)
        print(f"{year}: {count}; всего {len(rows)}", flush=True)
    if len(rows) != args.sample or len({r["doc_id"] for r in rows}) != args.sample:
        raise ValueError("Неполный срез или дубликаты")
    rows.sort(key=lambda r: (r["year"], r["doc_id"]))
    table = pa.Table.from_pylist(rows, schema=WORKS)
    args.output.mkdir(parents=True, exist_ok=True)
    temp = args.output / "works.parquet.tmp"
    pq.write_table(table, temp, compression="zstd")
    if temp.stat().st_size > 50_000_000:
        temp.unlink()
        raise ValueError("Снапшот превышает 50 МБ")
    file = args.output / "works.parquet"
    temp.replace(file)
    manifest = {
        **config, "source": "OpenAlex", "concept_name": concept["display_name"],
        "harvested_at": harvested_at, "n_works": len(rows),
        "counts_by_year": dict(sorted(Counter(r["year"] for r in rows).items())),
        "with_abstract": sum(bool(r["abstract"]) for r in rows),
        "with_doi": sum(bool(r["doi"]) for r in rows),
        "with_countries": sum(bool(r["countries"]) for r in rows),
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "bytes": file.stat().st_size,
        "rejected": rejected,
        "sampling_pool_extra_per_year": 100,
        "excluded_doc_ids": sorted(excluded),
        "sampling": "equal allocation by publication year; article; seed fixed",
        "limitations": ["Not a representative frequency estimate of the full corpus",
                        "2026 is partial through as_of", "Abstract may be missing",
                        "Seed alone does not freeze changing OpenAlex data; retain cache"],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
