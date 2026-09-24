"""Разрешение ссылок: только явный ответ, без угадывания URL."""
import asyncio
import json

import pytest

from ingest.origins import decode_response, resolve_google


def test_rpc_extracts_only_expected_result():
    body = ")]}'\n\n" + json.dumps([
        ['wrb.fr', 'Fbv4je', json.dumps(['garturlres', 'https://publisher.test/article', 1])],
    ])
    assert decode_response(body.encode()) == 'https://publisher.test/article'
    for url in ['javascript:alert(1)', 'https://user:password@publisher.test/a',
                'https://news.google.com/articles/again',
                'https://www.google.com/sorry/index?continue=article',
                'https://consent.google.com/m']:
        with pytest.raises(ValueError):
            decode_response(json.dumps([
                ['wrb.fr', 'Fbv4je', json.dumps(['garturlres', url, 1])]]).encode())
    with pytest.raises(ValueError):
        decode_response(b'<html>captcha</html>')


def test_resolution_validates_input_and_uses_page_parameters():
    class Client:
        async def get(self, url):
            assert url == 'https://news.google.com/articles/ABC123'
            return b'<div data-n-a-id="ABC123" data-n-a-sg="signature" data-n-a-ts="123"></div>'

        async def post(self, url, *, data, params):
            request = json.loads(json.loads(data['f.req'])[0][0][1])
            assert request[-3:] == ['ABC123', 123, 'signature']
            return json.dumps([['wrb.fr', 'Fbv4je', json.dumps(
                ['garturlres', 'https://publisher.test/article', 1])]]).encode()

    assert asyncio.run(resolve_google(Client(), 'https://news.google.com/rss/articles/ABC123')) == (
        'https://publisher.test/article')
    with pytest.raises(ValueError):
        asyncio.run(resolve_google(Client(), 'https://evil.test/articles/ABC123'))


@pytest.mark.parametrize('limited', [False, True])
def test_deadline_keeps_partial_result_and_does_not_change_index(tmp_path, monkeypatch, limited):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from contracts.schemas import CAND_DOCS, WORKS
    from ingest import origins
    from ingest.features import fingerprint
    from ingest.normalize import news_record

    index, raw = tmp_path / 'index', tmp_path / 'raw'
    index.mkdir()
    raw.mkdir()
    rows = [news_record('gnews', 'Encryption ' + name,
                        'https://news.google.com/articles/' + name, '2026-09-23',
                        'security', '2026-09-23') for name in ['FAST', 'SLOW']]
    pq.write_table(pa.Table.from_pylist(rows, schema=WORKS), index / 'works.parquet')
    pq.write_table(pa.Table.from_pylist([
        {'cand_id': 'c1', 'doc_id': r['doc_id'], 'weight': 1.0} for r in rows],
        schema=CAND_DOCS), index / 'cand_docs.parquet')
    digest = fingerprint(index / 'works.parquet')
    (index / 'meta.json').write_text(json.dumps({
        'corpus_scope': 'live', 'corpus_sha256': digest, 'n_works': 2, 'n_links': 2}))

    calls = []

    async def resolver(client, url):
        calls.append(url)
        if limited:
            raise origins.BlockedOrigin('Источник ограничил запросы')
        if url.endswith('SLOW'):
            await asyncio.sleep(10)
        return 'https://publisher.test/article'

    monkeypatch.setattr(origins, 'resolve_google', resolver)
    result = asyncio.run(origins.build_origins(index, raw, tmp_path / 'cache',
                                              tmp_path / 'output', budget=0.3))
    if limited:
        assert result['counts'] == {'error': 2}
        assert len(calls) == 1
    else:
        assert result['counts'] == {'resolved': 1, 'timeout': 1}
    assert fingerprint(index / 'works.parquet') == digest
    assert all(r['article_fetched'] is False for r in result['documents'])


def test_hn_requires_matching_record_and_ignores_ambiguous_targets(tmp_path):
    from ingest.origins import hn_targets

    (tmp_path / 'one.bin').write_text(json.dumps({'hits': [
        {'objectID': '1', 'title': 'Title', 'url': 'https://first.test/a'},
        {'objectID': '1', 'title': 'Title', 'url': 'https://second.test/a'},
        {'objectID': '2', 'title': 'Other', 'url': 'https://first.test/b'},
    ]}))
    targets = hn_targets(tmp_path)
    assert ('https://news.ycombinator.com/item?id=1', 'Title') not in targets
    assert targets[('https://news.ycombinator.com/item?id=2', 'Other')] == 'https://first.test/b'


def test_google_redirect_is_resolved_without_fetching_publisher(tmp_path):
    import httpx

    from ingest.news_transport import NewsClient

    requests = []

    def handler(request):
        requests.append(str(request.url))
        assert request.url.host == 'news.google.com'
        return httpx.Response(302, headers={'Location': 'https://publisher.test/article'})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = NewsClient(http, tmp_path, follow_redirects=False)
            return await resolve_google(client, 'https://news.google.com/articles/ABC123')

    assert asyncio.run(run()) == 'https://publisher.test/article'
    assert len(requests) == 1
