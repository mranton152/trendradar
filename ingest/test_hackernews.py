"""HN остаётся индикатором, даже если обсуждается доверенное издание."""
import asyncio
import json

import pyarrow as pa
import pytest

from contracts.schemas import WORKS
from ingest.normalize import from_hackernews
from ingest.sources.hackernews import collect


def test_hn_contract_and_identity():
    record = {'objectID': '123', 'title': 'Robotics pilot',
              'url': 'https://nature.com/example', 'created_at': '2026-09-18T12:00:00Z',
              'points': 150}
    row = from_hackernews(record, 'robotics', '2026-09-19')
    assert row['url'] == 'https://news.ycombinator.com/item?id=123'
    assert row['source_type'] == 'aggregator'
    assert row['trust_level'] == 'indicator'
    assert row['cited_by'] is None
    assert row['year'] == 2026
    assert pa.Table.from_pylist([row], schema=WORKS).num_rows == 1
    assert from_hackernews(dict(record, points=200), 'robotics', '2026-09-19')[
        'doc_id'] == row['doc_id']


@pytest.mark.parametrize('patch', [{'created_at': None}, {'title': ''}, {'objectID': '../a'}])
def test_bad_hn_record_rejected(patch):
    record = {'objectID': '123', 'title': 'Robot', 'created_at': '2026-09-18T12:00:00Z'}
    with pytest.raises(ValueError):
        from_hackernews(dict(record, **patch), 'robotics', '2026-09-19')


def test_collect_pages_and_skip_invalid():
    class Client:
        async def get(self, url, params):
            assert params['tags'] == 'story'
            page = params['page']
            return json.dumps({'nbPages': 2, 'hits': [
                {'objectID': str(page + 1), 'title': 'Robot',
                 'created_at': '2026-09-18T12:00:00Z'}, {'title': 'Invalid'},
            ]}).encode()
    rows = asyncio.run(collect(Client(), 'robot', 'robotics', '2026-09-19', pages=3))
    assert len(rows) == 2
    assert len({r['doc_id'] for r in rows}) == 2
