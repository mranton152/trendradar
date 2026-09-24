"""K-14: воспроизводимые новостные признаки наблюдённого корпуса, без сети."""
import argparse
import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import FEATURES
from ingest.trust import DATASET_RULES, RULES, classify, normalize_host

_EVENT = re.compile(r'\b(?:funding|raises|raised|series|seed|stealth|pilot|launch(?:es|ed)?)\b',
                    re.IGNORECASE)
_NEWS_SOURCES = {'rss', 'gnews', 'hackernews'}
_NEWS_TYPES = {'news', 'blog', 'press_release', 'aggregator'}


def month_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        raise ValueError('as_of должен быть YYYY-MM')
    parsed = datetime.strptime(value, '%Y-%m')
    number = parsed.year * 12 + parsed.month - 1
    if number < 12 + 23:
        raise ValueError('Нет полного календарного окна 24 месяца')
    return number


def news_features(cand_docs, works, *, as_of, company_mentions=None, publisher_urls=None):
    """Считать признаки по уникальным связям; company_mentions — внешняя разметка.

    Нет разметки/даты/первичного URL — null, не ноль. as_of включает весь месяц.
    Результат содержит только связанные cand_id; CLI отдельно учитывает пустые.
    """
    end = month_number(as_of)
    documents = {}
    for row in works:
        if not row.get('doc_id') or row['doc_id'] in documents:
            raise ValueError('WORKS требует уникальные непустые doc_id')
        documents[row['doc_id']] = row
    publisher_urls = publisher_urls or {}
    if publisher_urls:
        # origins использует fingerprint; загружаем валидатор после инициализации модуля.
        from ingest.origins import public_url
    for doc_id, url in publisher_urls.items():
        row = documents.get(doc_id)
        if row is None or (row.get('source') not in {'gnews', 'hackernews'}
                           and row.get('source_type') != 'aggregator'):
            raise ValueError('Исходная ссылка требует известный документ агрегатора')
        public_url(url)
        if classify(url).source_type == 'aggregator':
            raise ValueError('Агрегатор не является подтверждённым издателем')
    groups = defaultdict(set)
    for link in cand_docs:
        if not link.get('cand_id') or link.get('doc_id') not in documents:
            raise ValueError('Неизвестный doc_id или пустой cand_id')
        groups[link['cand_id']].add(link['doc_id'])
    result = {}
    for cand_id, ids in groups.items():
        counts = [0] * 24
        first = None
        selected = []
        undated = False
        for doc_id in sorted(ids):
            row = documents[doc_id]
            if (row.get('source') not in _NEWS_SOURCES
                    and row.get('source_type') not in _NEWS_TYPES):
                continue
            date = row.get('date')
            if date is None:
                undated = True
                continue
            try:
                parsed = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError('Некорректная дата новости: ' + doc_id) from error
            month = parsed.year * 12 + parsed.month - 1
            if month > end:
                continue
            first = min(first, month) if first is not None else month
            if month >= end - 23:
                counts[month - (end - 23)] += 1
                selected.append(row)
        hosts = defaultdict(set)
        unresolved = False
        for row in selected:
            if row['doc_id'] in publisher_urls:
                url = publisher_urls[row['doc_id']]
                hosts[normalize_host(url)].add(classify(url).trust_level)
                continue
            host = normalize_host(row.get('url'))
            if (not host or row.get('source_type') == 'aggregator'
                    or row.get('source') in {'gnews', 'hackernews'}):
                unresolved = True
            else:
                hosts[host].add(row.get('trust_level'))
        known_trust = all(levels <= {'trusted', 'indicator'} for levels in hosts.values())
        share = (sum(levels == {'trusted'} for levels in hosts.values()) / len(hosts)
                 if hosts and known_trust and not unresolved else None)
        company_count = None
        if company_mentions is not None and all(r['doc_id'] in company_mentions for r in selected):
            companies = set()
            for row in selected:
                names = company_mentions[row['doc_id']]
                if not isinstance(names, (list, tuple, set)) or any(
                        not isinstance(name, str) or not name.strip() for name in names):
                    raise ValueError('Ожидается список подтверждённых компаний для документа')
                companies.update(' '.join(name.casefold().split()) for name in names)
            company_count = len(companies)
        first_month = f'{first // 12:04d}-{first % 12 + 1:02d}' if first is not None else None
        result[cand_id] = {
            'news_mentions_24m': sum(counts), 'news_mentions_by_month': counts,
            'news_first_month': first_month,
            'n_domains': len(hosts) if not unresolved else None,
            'trusted_share': share, 'n_companies': company_count,
            'funding_mentions': sum(bool(_EVENT.search(
                row['title'].rsplit(' - ', 1)[0] if row.get('source') == 'gnews'
                else row['title'])) for row in selected),
            'langs': sorted({row['lang'] for row in selected if row.get('lang')}),
        }
        if undated:
            # Неизвестная дата не позволяет утверждать полноту окна или первого месяца.
            result[cand_id] = dict.fromkeys(result[cand_id])
    return result


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_publisher_urls(path, works, hashes):
    """Принять явную внешнюю разметку, связанную с конкретным индексом.

    SHA связывает разметку с данными, но не удостоверяет истинность публикации.
    Проверка страницы выполняется до передачи этого файла, не в features CLI.
    """
    path = Path(path)
    if path.stat().st_size > 16_000_000:
        raise ValueError('Файл доказательств превышает лимит 16 MB')
    evidence = json.loads(path.read_text(encoding='utf8'))
    if (not isinstance(evidence, dict)
            or evidence.get('format') != 'reviewed-publisher-links-v1'
            or evidence.get('corpus_sha256') != hashes['works']
            or evidence.get('cand_docs_sha256') != hashes['cand_docs']):
        raise ValueError('Формат или SHA файла доказательств не совпадает с индексом')
    records = evidence.get('documents')
    if not isinstance(records, list) or len(records) > len(works):
        raise ValueError('Некорректный список доказательств')
    documents = {row['doc_id']: row for row in works}
    urls = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('doc_id'), str):
            raise ValueError('Некорректная запись доказательства')
        doc_id = record['doc_id']
        row = documents.get(doc_id)
        if (row is None or doc_id in urls or record.get('aggregator_url') != row['url']
                or record.get('verification') != 'publisher_title_match'
                or not isinstance(record.get('original_url'), str)
                or not isinstance(record.get('page_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', record['page_sha256'])):
            raise ValueError('Доказательство не соответствует документу или проверке страницы')
        urls[doc_id] = record['original_url']
    return urls


def build_features(index, output, *, as_of, source_evidence=None):
    month_number(as_of)
    index, output = Path(index), Path(output)
    if output.exists():
        raise FileExistsError('Результат уже существует')
    meta = json.loads((index / 'meta.json').read_text(encoding='utf8'))
    if meta.get('corpus_scope') != 'live':
        raise ValueError('Эта CLI предназначена для live-индекса')
    limits = {'works': 200_000, 'candidates': 200_000, 'cand_docs': 2_000_000}
    tables, hashes = {}, {}
    for name, limit in limits.items():
        path = index / (name + '.parquet')
        if pq.read_metadata(path).num_rows > limit:
            raise ValueError('Индекс превышает лимит памяти live-этапа')
        tables[name] = pq.read_table(path).to_pylist()
        hashes[name] = fingerprint(path)
    works, candidates, links = (tables[name] for name in limits)
    if (meta.get('n_works') != len(works) or meta.get('corpus_sha256') != hashes['works']
            or meta.get('n_candidates') != len(candidates) or meta.get('n_links') != len(links)):
        raise ValueError('Индекс не соответствует meta: SHA/count')
    candidate_ids = {c['cand_id'] for c in candidates}
    if len(candidate_ids) != len(candidates) or any(
            link['cand_id'] not in candidate_ids for link in links):
        raise ValueError('Повтор или неизвестный cand_id')
    pairs = {(link['cand_id'], link['doc_id']) for link in links}
    if len(pairs) != len(links):
        raise ValueError('Повтор связи в индексе')
    counts = Counter(link['cand_id'] for link in links)
    if any(c['n_docs'] != counts[c['cand_id']] for c in candidates):
        raise ValueError('n_docs не совпадает с числом связей')
    if any(row['domain'] != meta['domain'] for row in works + candidates):
        raise ValueError('Домен индекса не совпадает с документами/кандидатами')
    publisher_urls = (load_publisher_urls(source_evidence, works, hashes)
                      if source_evidence is not None else None)
    values = news_features(links, works, as_of=as_of, publisher_urls=publisher_urls)
    rows = [{**values.get(c['cand_id'], {}), 'cand_id': c['cand_id'], 'label': c['label'],
             'domain': c['domain'], 'as_of': as_of} for c in candidates]
    table = pa.Table.from_pylist(rows, schema=FEATURES)
    table.validate(full=True)
    audit = {'method': 'observed-news-24-calendar-months-v1', 'as_of': as_of,
             'n_candidates': len(rows), 'source_hashes': hashes,
             'source_index': str(index.resolve()),
             'source_ingest_status': meta.get('live_ingest', {}).get('status'),
             'null_counts': {name: table[name].null_count for name in table.column_names},
             'limitations': ['Наблюдаемый корпус, не полный интернет',
                             'Компании без подтверждённой разметки неизвестны',
                             'Агрегаторы не считаются оригинальными сайтами',
                             'События определены словами, не проверкой сделки',
                             'Доверенность — доля уникальных прямых хостов'],
             'source_coverage': meta.get('live_ingest', {}).get('sources', {})}
    if source_evidence is not None:
        audit.update(
            source_evidence_sha256=fingerprint(source_evidence),
            n_reviewed_publisher_urls=len(publisher_urls),
            source_trust_rules_sha256=hashlib.sha256(json.dumps(
                {'rules': RULES, 'dataset_rules': DATASET_RULES}, sort_keys=True,
                ensure_ascii=False).encode('utf8')).hexdigest(),
            publisher_policy='explicit-reviewed-links-v1',
        )
        audit['limitations'].append('Даты остаются датами WORKS; разметка ссылок внешняя')
    stage = output.with_name(output.name + '.building-' + uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    pq.write_table(table, stage / 'features.parquet', compression='zstd')
    audit['features_sha256'] = fingerprint(stage / 'features.parquet')
    (stage / 'meta.json').write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf8')
    stage.rename(output)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--source-evidence', type=Path,
                        help='Проверенная внешняя разметка исходных ссылок с SHA индекса')
    args = parser.parse_args()
    meta = build_features(args.index, args.output, as_of=args.as_of,
                          source_evidence=args.source_evidence)
    print(json.dumps({'n_candidates': meta['n_candidates'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
