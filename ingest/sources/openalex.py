"""Постраничная воспроизводимая выборка OpenAlex."""
from ingest.normalize import normalize


def select_valid(records, count, domain, harvested_at, excluded=frozenset()):
    rows, rejected = [], []
    for record in records:
        try:
            row = normalize(record, domain, harvested_at)
            if row["doc_id"] in excluded:
                raise ValueError("Исключён по сохранённому аудиту URL (GET 404/410)")
            rows.append(row)
        except ValueError as error:
            rejected.append({"id": record.get("id"), "reason": str(error)})
        if len(rows) == count:
            return rows, rejected
    raise ValueError(f"Недостаточно валидных документов: {len(rows)} / {count}")


FIELDS = (
    "id,title,type,publication_year,publication_date,language,doi,"
    "primary_location,best_oa_location,locations,cited_by_count,authorships,"
    "concepts,abstract_inverted_index"
)


def sample_year(client, domain_filter, year, count, seed, as_of):
    records = []
    page = 1
    while len(records) < count:
        payload = client.get("/works", {
            "filter": f"{domain_filter},publication_year:{year},type:article,"
                      f"to_publication_date:{as_of}",
            "sample": count, "seed": seed, "per_page": 100, "page": page,
            "select": FIELDS,
        })
        batch = payload.get("results") or []
        if not batch:
            raise ValueError(f"Недобор выборки {year}: {len(records)} / {count}")
        records.extend(batch)
        page += 1
    records = records[:count]
    if len({r["id"] for r in records}) != count:
        raise ValueError(f"Повторы doc_id в выборке {year}")
    return records
