"""Живой сбор сохраняет частичный результат и удаляет дубли."""
import asyncio

import pytest

from ingest.live import deduplicate, poll, validate_phrases
from ingest.sources.hackernews import collect


def test_translation_rejects_russian_phrases():
    with pytest.raises(ValueError):
        validate_phrases({'phrases': ['ИИ агенты']})
    assert validate_phrases({'phrases': ['AI agent identity']}) == ['AI agent identity']


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
