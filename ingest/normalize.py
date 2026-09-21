"""Приведение настоящих записей OpenAlex к контракту WORKS."""
import re
from datetime import datetime
from hashlib import sha1
from urllib.parse import urlparse

from ingest.trust import classify, normalize_host


def news_record(source, title, url, date, domain, harvested_at, *, lang=None,
                doc_type='article', source_type=None, trust_level=None, abstract=None):
    """Общий WORKS для новостей; дата обязательна, популярность не есть цитирование."""
    if not isinstance(title, str) or not title.strip() or not normalize_host(url):
        raise ValueError('Нет заголовка или корректного URL')
    if urlparse(url).scheme not in {'http', 'https'}:
        raise ValueError('Нужен абсолютный HTTP(S) URL')
    try:
        published = datetime.fromisoformat(date.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError('Нет корректной даты публикации') from error
    trust = classify(url)
    return {
        'doc_id': source + ':' + sha1(url.encode()).hexdigest()[:16],
        'source': source, 'doc_type': doc_type, 'title': title.strip(),
        'abstract': abstract, 'year': published.year, 'date': published.isoformat(),
        'lang': lang, 'doi': None, 'url': url, 'cited_by': None,
        'countries': [], 'institutions': [], 'authors': [], 'concepts': [],
        'domain': domain, 'harvested_at': harvested_at,
        'source_type': source_type or trust.source_type,
        'trust_level': trust_level or trust.trust_level,
        'summary_ru': None, 'summary_model': None,
    }


def from_hackernews(record, domain, harvested_at):
    """Ссылка на обсуждение сохраняет происхождение индикатора HN."""
    native_id = str(record.get('objectID', ''))
    if not re.fullmatch(r'\d+', native_id):
        raise ValueError('Некорректный ID Hacker News')
    return news_record('hackernews', record.get('title'),
                       'https://news.ycombinator.com/item?id=' + native_id,
                       record.get('created_at'), domain, harvested_at,
                       lang='en', source_type='aggregator', trust_level='indicator')


def from_github(record, domain, harvested_at):
    return news_record('github', record.get('full_name'), record.get('html_url'),
                       record.get('created_at'), domain, harvested_at,
                       doc_type='repo', source_type='repo', abstract=record.get('description'))


def from_huggingface(record, domain, harvested_at):
    native_id = record.get('id', '')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)?',
                        native_id):
        raise ValueError('Некорректный ID модели')
    return news_record('hf', native_id, 'https://huggingface.co/' + native_id,
                       record.get('createdAt'), domain, harvested_at,
                       doc_type='model', source_type='model')


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
