"""Новостные признаки: временные границы, пропуски и происхождение."""
import pytest

from ingest.features import news_features


def work(doc_id, date, **kwargs):
    return {'doc_id': doc_id, 'date': date, 'source': 'rss', 'source_type': 'news',
            'title': 'Acme raises seed funding', 'url': 'https://example.org/article/' + doc_id,
            'trust_level': 'trusted', 'lang': 'en', **kwargs}


def links(*ids):
    return [{'cand_id': 'c1', 'doc_id': doc_id} for doc_id in ids]


def test_calendar_window_and_distinct_documents():
    rows = [work('old', '2024-09-30'), work('first', '2024-10-01'),
            work('last', '2026-09-30'), work('future', '2026-10-01'),
            work('repo', '2026-09-01', source='github', source_type='repo')]
    f = news_features(links('old', 'first', 'last', 'last', 'future', 'repo'), rows,
                      as_of='2026-09')['c1']
    assert f['news_mentions_24m'] == 2
    assert f['news_mentions_by_month'] == [1] + [0] * 22 + [1]
    assert f['news_first_month'] == '2024-09'
    assert f['funding_mentions'] == 2
    assert f['n_domains'] == 1 and f['trusted_share'] == 1.0
    assert f['n_companies'] is None


def test_aggregators_and_unknown_dates_are_not_false_zeroes():
    aggregate = work('a', '2026-09-01', source='gnews', source_type='aggregator',
                     url='https://news.google.com/a', trust_level='indicator')
    f = news_features(links('a'), [aggregate], as_of='2026-09')['c1']
    assert f['news_mentions_24m'] == 1
    assert f['n_domains'] is None and f['trusted_share'] is None
    f = news_features(links('a', 'b'), [aggregate, work('b', None)], as_of='2026-09')['c1']
    assert f['news_mentions_24m'] is None
    assert f['news_mentions_by_month'] is None
    assert f['funding_mentions'] is None


def test_host_share_is_not_document_share_and_events_have_boundaries():
    rows = [work('a', '2026-09-01', title='Seed funding raises the round'),
            work('b', '2026-09-01', title='seedling and pilotage'),
            work('c', '2026-09-01', url='https://other.org/a', trust_level='indicator')]
    f = news_features(links('a', 'b', 'c'), rows, as_of='2026-09')['c1']
    assert f['trusted_share'] == 0.5 and f['n_domains'] == 2
    assert f['funding_mentions'] == 2


def test_publisher_name_is_not_an_event_and_unknown_trust_stays_unknown():
    rows = [work('a', '2026-09-01', title='Encryption report - Seed Funding',
                 source='gnews', source_type='aggregator')]
    assert news_features(links('a'), rows, as_of='2026-09')['c1']['funding_mentions'] == 0
    rows = [work('a', '2026-09-01', trust_level='unknown')]
    features = news_features(links('a'), rows, as_of='2026-09')['c1']
    assert features['n_domains'] == 1 and features['trusted_share'] is None


def test_bad_links_dates_and_duplicate_works_fail():
    with pytest.raises(ValueError):
        news_features(links('missing'), [], as_of='2026-09')
    with pytest.raises(ValueError):
        news_features(links('a'), [work('a', '2026-02-30')], as_of='2026-09')
    with pytest.raises(ValueError):
        news_features(links('a'), [work('a', None), work('a', None)], as_of='2026-09')
    with pytest.raises(ValueError):
        news_features([], [], as_of='2026-13')


def test_company_counts_require_explicit_complete_evidence():
    rows = [work('a', '2026-09-01'), work('b', '2026-09-02')]
    f = news_features(links('a', 'b'), rows, as_of='2026-09',
                      company_mentions={'a': ['Acme'], 'b': ['Acme', 'Beta']})['c1']
    assert f['n_companies'] == 2
    f = news_features(links('a', 'b'), rows, as_of='2026-09',
                      company_mentions={'a': ['Acme']})['c1']
    assert f['n_companies'] is None


def test_reviewed_publishers_change_only_source_features():
    import copy

    rows = [work('a', '2026-09-01', source='gnews', source_type='aggregator',
                 url='https://news.google.com/articles/a', trust_level='indicator'),
            work('b', '2026-09-02', source='hackernews', source_type='aggregator',
                 url='https://news.ycombinator.com/item?id=2', trust_level='indicator')]
    original = copy.deepcopy(rows)
    baseline = news_features(links('a', 'b'), rows, as_of='2026-09')['c1']
    urls = {'a': 'https://techcrunch.com/article', 'b': 'https://prnewswire.com/article'}
    actual = news_features(links('a', 'b'), rows, as_of='2026-09', publisher_urls=urls)['c1']
    assert actual == {**baseline, 'n_domains': 2, 'trusted_share': 0.5}
    assert rows == original
    urls['b'] = 'https://techcrunch.com/another-article'
    actual = news_features(links('a', 'b'), rows, as_of='2026-09', publisher_urls=urls)['c1']
    assert actual['n_domains'] == 1 and actual['trusted_share'] == 1
    urls['b'] = 'https://unlisted-publisher.example/article'
    actual = news_features(links('a', 'b'), rows, as_of='2026-09', publisher_urls=urls)['c1']
    assert actual['n_domains'] == 2 and actual['trusted_share'] is None
    del urls['b']
    actual = news_features(links('a', 'b'), rows, as_of='2026-09', publisher_urls=urls)['c1']
    assert actual['n_domains'] is None and actual['trusted_share'] is None


def test_publisher_evidence_cannot_replace_direct_sources_or_use_service_urls():
    row = work('a', '2026-09-01')
    with pytest.raises(ValueError):
        news_features(links('a'), [row], as_of='2026-09',
                      publisher_urls={'a': 'https://techcrunch.com/a'})
    row.update(source='gnews', source_type='aggregator')
    for urls in ({'missing': 'https://techcrunch.com/a'},
                 {'a': 'https://www.google.com/sorry'},
                 {'a': 'https://news.ycombinator.com/item?id=1'},
                 {'a': 'http://127.0.0.1/a'}):
        with pytest.raises(ValueError):
            news_features(links('a'), [row], as_of='2026-09', publisher_urls=urls)


def test_feature_artifact_matches_contract_and_provenance(tmp_path):
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from contracts.schemas import CAND_DOCS, CANDIDATES, FEATURES, WORKS
    from ingest.features import build_features, fingerprint
    from ingest.normalize import news_record

    index = tmp_path / 'index'
    index.mkdir()
    rows = [news_record('gnews', title, 'https://news.google.com/articles/' + str(i), date,
                        'security', '2026-09-23', source_type='aggregator', trust_level='indicator')
            for i, (title, date) in enumerate([
                ('Acme raises seed funding', '2026-09-01'),
                ('Acme launches encryption software', '2026-08-01')])]
    candidate = {'cand_id': 'c1', 'kind': 'term', 'label': 'Acme', 'aliases': [],
                 'top_terms': ['Acme'], 'emb_row': None, 'n_docs': 2, 'domain': 'security'}
    for name, records, schema in [
            ('works', rows, WORKS), ('candidates', [candidate], CANDIDATES),
            ('cand_docs', links(*(r['doc_id'] for r in rows)), CAND_DOCS)]:
        pq.write_table(pa.Table.from_pylist(records, schema=schema), index / (name + '.parquet'))
    (index / 'meta.json').write_text(json.dumps({
        'corpus_scope': 'live', 'domain': 'security', 'n_works': 2, 'n_candidates': 1,
        'n_links': 2, 'corpus_sha256': fingerprint(index / 'works.parquet'),
        'live_ingest': {'status': 'partial'},
    }))
    output = tmp_path / 'features'
    meta = build_features(index, output, as_of='2026-09')
    table = pq.read_table(output / 'features.parquet')
    assert table.schema.equals(FEATURES)
    row = table.to_pylist()[0]
    assert row['news_mentions_by_month'] == [0] * 22 + [1, 1]
    assert row['funding_mentions'] == 2 and row['pub_counts_by_year'] is None
    assert meta['source_ingest_status'] == 'partial'
    assert meta['features_sha256'] == fingerprint(output / 'features.parquet')
    evidence = {'format': 'reviewed-publisher-links-v1',
                'corpus_sha256': fingerprint(index / 'works.parquet'),
                'cand_docs_sha256': fingerprint(index / 'cand_docs.parquet'),
                'documents': [{'doc_id': r['doc_id'], 'aggregator_url': r['url'],
                               'original_url': 'https://techcrunch.com/' + str(i),
                               'verification': 'publisher_title_match',
                               'page_sha256': 'a' * 64} for i, r in enumerate(rows)]}
    evidence_path = tmp_path / 'evidence.json'
    evidence_path.write_text(json.dumps(evidence))
    enriched = tmp_path / 'enriched'
    enriched_meta = build_features(index, enriched, as_of='2026-09',
                                   source_evidence=evidence_path)
    enriched_row = pq.read_table(enriched / 'features.parquet').to_pylist()[0]
    assert enriched_row == {**row, 'n_domains': 1, 'trusted_share': 1.0}
    assert enriched_meta['source_evidence_sha256'] == fingerprint(evidence_path)
    for changed in ({'corpus_sha256': '0' * 64}, {'cand_docs_sha256': '0' * 64},
                    {'format': 'unreviewed'},
                    {'documents': evidence['documents'] * 2},
                    {'documents': [{**evidence['documents'][0], 'aggregator_url': 'wrong'}]},
                    {'documents': [{**evidence['documents'][0], 'verification': 'resolved'}]},
                    {'documents': [{**evidence['documents'][0], 'page_sha256': '../file'}]}):
        evidence_path.write_text(json.dumps({**evidence, **changed}))
        with pytest.raises(ValueError):
            build_features(index, tmp_path / 'bad-evidence', as_of='2026-09',
                           source_evidence=evidence_path)
        assert not (tmp_path / 'bad-evidence').exists()
    with pytest.raises(FileExistsError):
        build_features(index, output, as_of='2026-09')
    rows[0]['title'] = 'changed'
    pq.write_table(pa.Table.from_pylist(rows, schema=WORKS), index / 'works.parquet')
    with pytest.raises(ValueError, match='SHA/count'):
        build_features(index, tmp_path / 'invalid', as_of='2026-09')
    assert not (tmp_path / 'invalid').exists()
