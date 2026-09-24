"""Явные исходные ссылки агрегаторов; отдельный артефакт, без повышения trust WORKS."""
import argparse
import asyncio
import hashlib
import ipaddress
import json
import re
import time
import uuid
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pyarrow.parquet as pq

from ingest.features import fingerprint
from ingest.news_transport import NewsClient
from ingest.trust import normalize_host


class BlockedOrigin(ValueError):
    """Служебная страница/ограничение Google не является исходной статьёй."""


def public_url(value):
    host = normalize_host(value)
    if not host or urlsplit(value).scheme not in {'http', 'https'}:
        raise ValueError('Нужен публичный HTTP(S) URL')
    if '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('Локальный адрес не является источником')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Локальный адрес не является источником')
    if host in {'news.google.com', 'www.google.com', 'google.com',
                'consent.google.com', 'accounts.google.com'}:
        raise BlockedOrigin('Служебная страница Google вместо исходного URL')
    return value


def decode_response(body):
    """Читаем только Fbv4je/garturlres; произвольная ссылка в HTML не считается ответом."""
    found = set()
    for line in body.decode('utf8').splitlines():
        if not line.lstrip().startswith('['):
            continue
        try:
            records = json.loads(line)
            for record in records:
                if (isinstance(record, list) and len(record) > 2
                        and record[:2] == ['wrb.fr', 'Fbv4je']):
                    value = json.loads(record[2])
                    if isinstance(value, list) and len(value) > 1 and value[0] == 'garturlres':
                        found.add(public_url(value[1]))
        except (json.JSONDecodeError, TypeError, IndexError) as error:
            raise ValueError('Некорректный ответ разрешения ссылки') from error
    if len(found) != 1:
        raise ValueError('Однозначный исходный URL не найден')
    return found.pop()


class Parameters(HTMLParser):
    def __init__(self, article_id):
        super().__init__()
        self.article_id = article_id
        self.values = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if (attrs.get('data-n-a-id') == self.article_id
                and attrs.get('data-n-a-ts', '').isdigit() and attrs.get('data-n-a-sg')):
            self.values.add((int(attrs['data-n-a-ts']), attrs['data-n-a-sg']))


async def resolve_google(client, url):
    parts = urlsplit(url)
    match = re.fullmatch(r'/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)', parts.path)
    if parts.scheme != 'https' or parts.netloc != 'news.google.com' or not match:
        raise ValueError('Ожидается ссылка статьи Google News')
    article_id = match[1]
    parser = Parameters(article_id)
    try:
        body = await client.get('https://news.google.com/articles/' + article_id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {301, 302, 303, 307, 308}:
            return public_url(error.response.headers.get('Location'))
        raise
    parser.feed(body.decode('utf8'))
    if len(parser.values) != 1:
        raise ValueError('Параметры перехода отсутствуют или неоднозначны')
    timestamp, signature = parser.values.pop()
    # Публичный протокол страницы перехода. При изменении формата завершаемся ошибкой,
    # не угадываем URL и не обходим CAPTCHA/лимиты. Источник протокола в README_ORIGINS.md.
    context = [['X', 'X', ['X', 'X'], None, None, 1, 1, 'US:en', None, 1,
                None, None, None, None, None, 0, 1],
               'X', 'X', 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0]
    request = ['garturlreq', context, article_id, timestamp, signature]
    envelope = [[['Fbv4je', json.dumps(request), None, 'generic']]]
    body = await client.post('https://news.google.com/_/DotsSplashUi/data/batchexecute',
                             params={'rpcids': 'Fbv4je'}, data={'f.req': json.dumps(envelope)})
    return decode_response(body)


def hn_targets(cache):
    """Извлекаем объявленные ссылки из ограниченного каталога сырых ответов Algolia."""
    result = {}
    total = 0
    for path in sorted(Path(cache).glob('*.bin')):
        size = path.stat().st_size
        total += size
        if total > 100_000_000:
            raise ValueError('Каталог кэша превышает лимит; нужен кэш текущего live-сбора')
        if size > 10_000_000:
            continue
        try:
            payload = json.loads(path.read_bytes())
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for hit in payload.get('hits', []):
            if not isinstance(hit, dict) or not str(hit.get('objectID', '')).isdigit():
                continue
            try:
                target = public_url(hit.get('url'))
            except (ValueError, TypeError):
                continue
            key = ('https://news.ycombinator.com/item?id=' + str(hit['objectID']),
                   hit.get('title'))
            result.setdefault(key, set()).add(target)
    return {key: next(iter(values)) for key, values in result.items() if len(values) == 1}


async def build_origins(index, raw_cache, cache, output, *, budget=180, offline=False):
    if budget <= 0:
        raise ValueError('Бюджет должен быть положительным')
    index, cache, output = Path(index), Path(cache), Path(output)
    if output.exists():
        raise FileExistsError('Результат уже существует')
    start = time.monotonic()
    meta = json.loads((index / 'meta.json').read_text(encoding='utf8'))
    if meta.get('corpus_scope') != 'live':
        raise ValueError('Нужен live-индекс')
    if pq.read_metadata(index / 'works.parquet').num_rows > 200_000:
        raise ValueError('Нужен live-индекс')
    if pq.read_metadata(index / 'cand_docs.parquet').num_rows > 2_000_000:
        raise ValueError('Превышен лимит числа связей')
    rows = pq.read_table(index / 'works.parquet').to_pylist()
    if len({r['doc_id'] for r in rows}) != len(rows):
        raise ValueError('Повтор doc_id в WORKS')
    corpus_hash = fingerprint(index / 'works.parquet')
    if corpus_hash != meta.get('corpus_sha256') or len(rows) != meta.get('n_works'):
        raise ValueError('SHA/count корпуса не соответствует meta')
    selected = set(pq.read_table(index / 'cand_docs.parquet',
                                columns=['doc_id'])['doc_id'].to_pylist())
    if pq.read_metadata(index / 'cand_docs.parquet').num_rows != meta.get('n_links'):
        raise ValueError('Число связей не соответствует meta')
    if not selected <= {row['doc_id'] for row in rows}:
        raise ValueError('Неизвестные doc_id в связях')
    rows = [r for r in rows if r['doc_id'] in selected and r['source'] in {'gnews', 'hackernews'}]
    if len(rows) > 500:
        raise ValueError('Разрешение за один запуск ограничено 500 связанными документами')
    targets = hn_targets(raw_cache)
    cache.mkdir(parents=True, exist_ok=True)
    results = {row['doc_id']: {'doc_id': row['doc_id'], 'aggregator_url': row['url'],
                              'original_url': None, 'article_fetched': False,
                              'status': 'timeout'} for row in rows}
    semaphore = asyncio.Semaphore(3)
    google_stopped = asyncio.Event()
    async with httpx.AsyncClient(headers={'User-Agent': 'TrendRadar/0.1'}) as http:
        client = NewsClient(http, cache, deadline=start + budget, attempts=2, offline=offline,
                            follow_redirects=False)

        async def one(row):
            record = results[row['doc_id']]
            record['status'] = 'unresolved'
            try:
                async with semaphore:
                    if row['source'] == 'hackernews':
                        target = targets.get((row['url'], row['title']))
                        if not target:
                            return
                        record['method'] = 'algolia_outbound_link'
                    else:
                        name = hashlib.sha256(row['url'].encode()).hexdigest() + '.origin.json'
                        file = cache / name
                        if file.exists():
                            saved = json.loads(file.read_text(encoding='utf8'))
                            if saved['aggregator_url'] != row['url']:
                                raise ValueError('Кэш ссылки не соответствует документу')
                            target = public_url(saved['original_url'])
                        else:
                            if google_stopped.is_set():
                                raise BlockedOrigin('Разрешение Google остановлено после ошибки')
                            target = await resolve_google(client, row['url'])
                            temp = file.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                            temp.write_text(json.dumps({'aggregator_url': row['url'],
                                                        'original_url': target}), encoding='utf8')
                            temp.replace(file)
                        record['method'] = 'google_article_link_response'
                    record.update(original_url=target, status='resolved')
            except asyncio.CancelledError:
                record['status'] = 'timeout'
                raise
            except (httpx.HTTPError, TimeoutError, ValueError, OSError, KeyError) as error:
                record.update(status='error', error=type(error).__name__)
                if row['source'] == 'gnews':
                    google_stopped.set()

        tasks = [asyncio.create_task(one(row)) for row in rows]
        if tasks:
            _, pending = await asyncio.wait(
                tasks, timeout=max(0, start + budget - time.monotonic()))
            for task in pending:
                task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(
                        outcome, asyncio.CancelledError):
                    raise outcome
    ordered = sorted(results.values(), key=lambda r: r['doc_id'])
    report = {'corpus_sha256': corpus_hash,
              'cand_docs_sha256': fingerprint(index / 'cand_docs.parquet'),
              'elapsed_s': time.monotonic() - start, 'offline': offline,
              'counts': dict(Counter(r['status'] for r in ordered)), 'documents': ordered,
              'meaning': 'Ссылка сообщена агрегатором; доступность/текст статьи не проверены. '
                         'WORKS и trust_level не изменены.'}
    stage = output.with_name(output.name + '.building-' + uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    (stage / 'origins.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['index', 'raw-cache', 'cache', 'output']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--budget', type=float, default=180)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    report = asyncio.run(build_origins(args.index, args.raw_cache, args.cache, args.output,
                                       budget=args.budget, offline=args.offline))
    print(json.dumps({'counts': report['counts'], 'elapsed_s': report['elapsed_s']}))


if __name__ == '__main__':
    main()
