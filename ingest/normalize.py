"""Приведение настоящих записей OpenAlex к контракту WORKS."""
import re
from urllib.parse import urlparse


def normalize(record: dict, domain: str, harvested_at: str) -> dict:
    native_id = (record.get("id") or "").rsplit("/", 1)[-1]
    title = (record.get("title") or "").strip()
    year = record.get("publication_year")
    locations = [record.get("primary_location") or {},
                 record.get("best_oa_location") or {}, *(record.get("locations") or [])]
    urls = [record.get("doi"), *[loc.get("landing_page_url") for loc in locations]]
    url = next((u for u in urls if u and urlparse(u).scheme in {"https", "http"}
                and urlparse(u).netloc), None)
    if not re.fullmatch(r"W\d+", native_id) or not title or not url or not isinstance(year, int):
        raise ValueError(f"Недостаточные обязательные данные: {native_id}")
    abstract_index = record.get("abstract_inverted_index") or {}
    positions = sorted((position, word) for word, indexes in abstract_index.items()
                       for position in indexes)
    abstract = " ".join(word for _, word in positions) or None
    authors, institutions, countries = set(), set(), set()
    for authorship in record.get("authorships") or []:
        author = (authorship.get("author") or {}).get("display_name")
        if author:
            authors.add(author)
        countries.update(c for c in authorship.get("countries") or [] if c)
        for institution in authorship.get("institutions") or []:
            if institution.get("display_name"):
                institutions.add(institution["display_name"])
            if institution.get("country_code"):
                countries.add(institution["country_code"])
    countries = sorted(c.upper() for c in countries if re.fullmatch(r"[A-Za-z]{2}", c))
    doc_type = {"article": "article", "preprint": "preprint", "report": "report"}.get(
        record.get("type"))
    if not doc_type:
        raise ValueError(f"Неподдерживаемый тип документа: {record.get('type')}")
    return {
        "doc_id": f"openalex:{native_id}", "source": "openalex", "doc_type": doc_type,
        "title": title, "abstract": abstract, "year": year,
        "date": record.get("publication_date"), "lang": record.get("language"),
        "doi": record.get("doi"), "url": url, "cited_by": record.get("cited_by_count"),
        "countries": sorted(set(countries)), "institutions": sorted(institutions),
        "authors": sorted(authors),
        "concepts": sorted({c["display_name"] for c in record.get("concepts") or []
                            if c.get("display_name")}),
        "domain": domain, "harvested_at": harvested_at,
    }
