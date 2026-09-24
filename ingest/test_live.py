"""Живой сбор сохраняет частичный результат и удаляет дубли."""
import asyncio

import pytest

from ingest.live import deduplicate, poll, validate_phrases
from ingest.sources.hackernews import collect


def test_google_news_publisher_does_not_hide_repeated_headline():
    rows = [
        {'title': 'Acme launches cybersecurity tools - Reuters', 'source': 'gnews',
         'url': 'https://news.google.com/a', 'trust_level': 'indicator',
         'source_type': 'aggregator'},
        {'title': 'Acme launches cybersecurity tools - Another Publisher', 'source': 'gnews',
         'url': 'https://news.google.com/b', 'trust_level': 'indicator',
         'source_type': 'aggregator'},
        {'title': 'Acme launches cybersecurity tools', 'source': 'rss',
         'url': 'https://example.com/article', 'trust_level': 'trusted',
         'source_type': 'media'},
    ]
    result = deduplicate(rows)
    assert len(result) == 1
    assert result[0]['source'] == 'rss'


def test_rss_requires_topic_not_generic_word():
    from ingest.live import matches_topic

    phrases = ['Event-Based Vision Sensors for Automotive', 'Hybrid Event Cameras']
    assert not matches_topic('Join our annual technology event', phrases)
    assert not matches_topic('AI model launches with new funding',
                             ['Model compression for edge AI'])
    assert matches_topic('Hybrid event cameras improve automotive vision', phrases)
    assert matches_topic('New cybersecurity pilot announced', ['cybersecurity'])


def test_rss_keeps_exact_ai_topics_without_matching_substrings():
    from ingest.live import matches_topic

    assert matches_topic('New artificial intelligence startup launches',
                         ['artificial intelligence'])
    assert matches_topic('New AI agents secure accounts', ['AI agents'])
    assert matches_topic('New AI tool launches', ['AI'])
    assert not matches_topic('New aid scheme launches', ['AI'])


def test_translation_rejects_russian_phrases():
    with pytest.raises(ValueError):
        validate_phrases({'phrases': ['ИИ агенты']})
    assert validate_phrases({'phrases': ['AI agent identity']}) == ['AI agent identity']


def test_event_search_survives_partial_failure_and_keeps_translation(tmp_path, monkeypatch):
    import pyarrow.parquet as pq

    from ingest import live
    from ingest.normalize import news_record

    async def empty(*args, **kwargs):
        return []

    async def news(client, query, domain, now, **kwargs):
        if query.endswith('funding'):
            raise TimeoutError
        if query.endswith('startup'):
            return [news_record('gnews', 'Acme launches optical sensors',
                                'https://news.google.com/item/1', '2026-09-23', domain, now)]
        return []

    for source in (live.github, live.huggingface, live.hackernews):
        monkeypatch.setattr(source, 'collect', empty)
    monkeypatch.setattr(live.gnews, 'collect', news)
    monkeypatch.setattr(live.rss, 'FEEDS', {})
    audit = {'status': 'complete', 'response': {'phrases': ['optical sensors']}}
    output = tmp_path / 'live'
    meta = asyncio.run(live.run('оптические сенсоры', output, budget=1,
                               translation=audit, offline=True, cache=tmp_path / 'cache'))
    assert meta['status'] == 'partial'
    assert meta['n_sources_polled'] == 4  # Дополнительный запрос — не новый источник.
    assert meta['translation'] == audit
    assert meta['sources']['gnews-events:optical sensors funding']['status'] == 'error'
    assert pq.read_table(output / 'works.parquet')['title'].to_pylist() == [
        'Acme launches optical sensors']


def test_deduplicate_url_and_title():
    rows = [{'url': 'https://example.org/a?utm_source=x', 'title': 'Robot Pilot'},
            {'url': 'https://example.org/a', 'title': 'Different'},
            {'url': 'https://other.org/b', 'title': ' ROBOT   pilot '}]
    assert len(deduplicate(rows)) == 1


def test_deduplicate_keeps_direct_trusted_evidence():
    rows = [{'url': 'https://news.ycombinator.com/item?id=1', 'title': 'Robot Pilot',
             'source_type': 'aggregator', 'trust_level': 'indicator'},
            {'url': 'https://techcrunch.com/robot', 'title': 'Robot Pilot',
             'source_type': 'news', 'trust_level': 'trusted'}]
    assert deduplicate(rows)[0]['trust_level'] == 'trusted'


def test_partial_result_survives_deadline():
    async def fast():
        return [{'title': 'Robot'}]

    async def slow():
        await asyncio.sleep(10)
        return []

    rows, statuses = asyncio.run(poll({'fast': fast(), 'slow': slow()}, 0.03))
    assert len(rows) == 1
    assert statuses['fast']['status'] == 'complete'
    assert statuses['slow']['status'] == 'timeout'


def test_page_survives_next_page_timeout():
    class Client:
        async def get(self, url, params):
            if params['page']:
                await asyncio.sleep(10)
            return (b'{"nbPages":2,"hits":[{"objectID":"1","title":"Robot",'
                    b'"created_at":"2026-01-01T00:00:00Z"}]}')
    rows, statuses = asyncio.run(poll(
        {'hn': collect(Client(), 'robot', 'robotics', '2026-09-19')}, 0.03))
    assert len(rows) == 1
    assert statuses['hn']['status'] == 'partial'
