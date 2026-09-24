"""Живой корпус с общим бюджетом времени и журналом частичных результатов."""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import WORKS
from ingest.news_transport import NewsClient
from ingest.sources import github, gnews, hackernews, huggingface, rss
from ingest.sources.partial import PartialCollectionError
from semantic.terms import ngrams

_QUERY_STOP = frozenset('''the and for with from into via using based new emerging
technology technologies system systems model models platform ai artificial intelligence
development developments advanced local service services market markets'''.split())


def matches_topic(title, phrases):
    """Консервативный лексический отбор RSS, не оценка смысловой релевантности."""
    tokens = set(re.findall(r'\w+', title.casefold()))
    title_sequence = ' ' + ' '.join(re.findall(r'\w+', title.casefold())) + ' '
    for phrase in phrases:
        phrase_sequence = ' '.join(re.findall(r'\w+', phrase.casefold()))
        # Точный предмет запроса сохраняем даже для AI, отсекаемого stop-list.
        if phrase_sequence and (' ' + phrase_sequence + ' ') in title_sequence:
            return True
        terms = {t for t in re.findall(r'\w+', phrase.casefold())
                 if len(t) > 2 and t not in _QUERY_STOP}
        # Два признака одной фразы; одиночный точный термин допускается,
        # только если сам запрос состоит из одного содержательного токена.
        if len(terms) >= 2 and len(terms & tokens) >= 2:
            return True
        if len(terms) == 1 and len(re.findall(r'\w+', phrase)) == 1 and terms <= tokens:
            return True
    return False


def deduplicate(rows):
    urls, titles, result = set(), set(), []
    ranked = sorted(rows, key=lambda r: (
        {'trusted': 0, 'unknown': 1, 'indicator': 2}.get(r.get('trust_level'), 1),
        r.get('source_type') == 'aggregator'))
    for row in ranked:
        parts = urlsplit(row['url'])
        query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query)
                                 if not k.lower().startswith('utm_')
                                 and k not in {'fbclid', 'gclid'}))
        url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ''))
        content_title = row['title']
        if row.get('source') == 'gnews':
            content_title = content_title.rsplit(' - ', 1)[0]
        title = ' '.join(re.findall(r'\w+', content_title.casefold()))
        if url in urls or title in titles:
            continue
        urls.add(url)
        titles.add(title)
        result.append(row)
    return result


async def poll(jobs, budget):
    tasks = {name: asyncio.create_task(job) for name, job in jobs.items()}
    if not tasks:
        return [], {}
    _, pending = await asyncio.wait(tasks.values(), timeout=max(0, budget))
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    rows, statuses = [], {}
    for name, task in tasks.items():
        if task.cancelled():
            statuses[name] = {'status': 'timeout'}
        elif task.exception():
            error = task.exception()
            if isinstance(error, PartialCollectionError):
                rows.extend(error.rows)
                statuses[name] = {'status': 'partial', 'error': error.reason,
                                  'n_docs': len(error.rows)}
            else:
                statuses[name] = {'status': 'error', 'error': type(error).__name__}
        else:
            batch = task.result()
            rows.extend(batch)
            statuses[name] = {'status': 'complete', 'n_docs': len(batch)}
    return rows, statuses


def validate_phrases(payload):
    phrases = payload.get('phrases')
    if not isinstance(phrases, list) or not 1 <= len(phrases) <= 3 or any(
            not isinstance(p, str) or not re.fullmatch(r'[\x20-\x7e]{1,200}', p)
            or not re.search('[A-Za-z]', p) for p in phrases):
        raise ValueError('Ожидаются 1–3 английские поисковые фразы')
    return list(dict.fromkeys(p.strip() for p in phrases))


def news_event_queries(phrase):
    """Дополнение предмета поиска событиями из ТЗ; не перевод и не подтемы."""
    return [phrase + ' startup', phrase + ' funding']


async def translate(query, timeout):
    prompt = ('Return JSON {"phrases": [1 to 3 concise English technology search phrases]}. '
              'Translate the technology topic, preserving its scope. Do not invent subtopics. '
              'Extract only the subject being researched, not the research intent. '
              'Omit requests to find weak signals, promising solutions, trends, news, '
              'developments, or emerging technologies. These are NOT search keywords. '
              'Do not translate weak signals as signals, weaknesses or vulnerabilities. '
              'Prefer ONE literal subject translation; add synonyms only if equivalent. '
              'Example: promising solutions in robotics -> {"phrases": ["robotics"]}. '
              'Example: trends in optical sensors -> {"phrases": ["optical sensors"]}. '
              'User topic: ' + json.dumps(query, ensure_ascii=False))
    audit = {'prompt': prompt, 'model': os.getenv('LLM_MODEL', 'qwen2.5:7b'),
             'backend': os.getenv('LLM_BACKEND', 'ollama')}
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-X', 'utf8', '-m', 'ingest.translate_worker',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(prompt.encode()), timeout)
        if process.returncode:
            raise ValueError('Ошибка провайдера LLM')
        payload = json.loads(stdout)
        audit['response'] = payload
        phrases = validate_phrases(payload)
        audit['status'] = 'complete'
        return phrases, audit
    except (TimeoutError, ValueError) as error:
        audit.update(status='error', error=type(error).__name__)
        return [], audit
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def run(query, output, *, budget=180, cache=Path('data/live-cache'),
              translation=None, offline=False):
    if budget <= 0:
        raise ValueError('budget должен быть положительным')
    output = Path(output)
    if output.exists():
        raise FileExistsError('Результат уже существует; выберите новый output')
    start = time.monotonic()
    deadline = start + budget
    now = datetime.now(UTC).isoformat()
    domain = 'live-' + hashlib.sha256(query.encode()).hexdigest()[:16]
    if translation is None:
        phrases, audit = await translate(query, min(45, budget * 0.3))
    else:
        audit = translation
        phrases = validate_phrases(audit['response'])
    jobs = {}
    async with httpx.AsyncClient(headers={'User-Agent': 'TrendRadar/0.1'}) as http:
        client = NewsClient(http, cache, deadline=deadline, offline=offline)
        for phrase in phrases:
            for name, module in [('hn', hackernews), ('github', github),
                                 ('hf', huggingface), ('gnews-en', gnews)]:
                jobs[name + ':' + phrase] = module.collect(client, phrase, domain, now)
            for event_query in news_event_queries(phrase):
                jobs['gnews-events:' + event_query] = gnews.collect(
                    client, event_query, domain, now)
        jobs['gnews-ru'] = gnews.collect(client, query, domain, now, lang='ru')
        for name in rss.FEEDS:
            jobs['rss:' + name] = rss.collect(client, name, domain, now)
        reserve = min(30, budget * 0.2) if os.getenv('OPENALEX_API_KEY') else 0
        rows, statuses = await poll(jobs, deadline - time.monotonic() - reserve)
        rows = [r for r in rows if r['source'] != 'rss' or matches_topic(r['title'], phrases)]
        rows = deduplicate(rows)
        history = {'status': 'skipped_deadline' if os.getenv('OPENALEX_API_KEY')
                   else 'skipped_no_key'}
        if not offline and os.getenv('OPENALEX_API_KEY') and time.monotonic() < deadline:
            counts = Counter(term for row in rows for term in set(ngrams(row['title'])))
            history = {'status': 'partial', 'queries': {}}
            for phrase, _ in counts.most_common(40):
                try:
                    # Ответ сохраняется без запроса и ключа; ошибки URL не журналируются.
                    response = await asyncio.wait_for(http.get(
                        'https://api.openalex.org/works',
                        params={'search': phrase, 'group_by': 'publication_year',
                                'api_key': os.environ['OPENALEX_API_KEY']}),
                        timeout=max(0.001, deadline - time.monotonic()))
                    response.raise_for_status()
                    payload = response.json()
                    if (not isinstance(payload, dict)
                            or not isinstance(payload.get('group_by'), list)):
                        raise ValueError('Некорректный ответ истории OpenAlex')
                    history['queries'][phrase] = payload['group_by']
                except (TimeoutError, httpx.HTTPError, ValueError):
                    break
            if len(history['queries']) == min(40, len(counts)):
                history['status'] = 'complete'
    stage = output.with_name(output.name + '.building-' + uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=WORKS), stage / 'works.parquet')
    meta = {'domain': domain, 'domain_query': query, 'built_at': now,
            'corpus_scope': 'live_query',
            'offline_replay': offline,
            'corpus_sha256': hashlib.sha256((stage / 'works.parquet').read_bytes()).hexdigest(),
            'status': 'complete' if audit['status'] == 'complete' and all(
                s['status'] == 'complete' for s in statuses.values()) else 'partial',
            'n_sources_polled': len({name if name.startswith('rss:') else
                                     ('gnews' if name.startswith('gnews')
                                      else name.split(':', 1)[0]) for name in statuses}),
            'n_source_queries': len(statuses), 'n_docs': len(rows),
            'elapsed_s': time.monotonic() - start, 'translation': audit,
            'news_query_policy': 'subject_plus_startup_and_funding_v1',
            'sources': statuses, 'openalex_history': history}
    (stage / 'meta.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    stage.rename(output)
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', required=True)
    parser.add_argument('--budget', type=float, default=180)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cache', type=Path, default=Path('data/live-cache'))
    args = parser.parse_args()
    output = args.output or Path('data/live') / hashlib.sha256(args.query.encode()).hexdigest()[:16]
    result = asyncio.run(run(args.query, output, budget=args.budget, cache=args.cache))
    print(json.dumps({k: result[k] for k in ('status', 'n_docs', 'elapsed_s')}))


if __name__ == '__main__':
    main()
