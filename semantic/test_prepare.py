import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import WORKS
from semantic.prepare import prepare


def corpus(tmp_path):
    rows = []
    for year, size in [(2020, 2), (2022, 5), (2023, 5)]:
        for i in range(size):
            rows.append(dict(doc_id=f'openalex:{year}-{i}', source='openalex',
                             doc_type='article', title='Neural network', year=year,
                             url='https://example.org/paper', domain='ai',
                             harvested_at='2026-09-09', countries=['US', 'GB'] if i == 0 else []))
    path = tmp_path / 'works.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=WORKS), path)
    meta = dict(status='complete', sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                n_works=len(rows), config=dict(domain='ai', as_of='2026-09-09'))
    path.with_name('manifest.json').write_text(json.dumps(meta))
    return path


def test_sample_is_deterministic_and_stats_use_full_corpus(tmp_path):
    source = corpus(tmp_path)
    a, b = tmp_path / 'a', tmp_path / 'b'
    prepare(source, a, 'ai', 2026, 2022, 2023, 6, 42)
    prepare(source, b, 'ai', 2026, 2022, 2023, 6, 42)
    sample = pq.read_table(a / 'works.parquet')
    assert sample.equals(pq.read_table(b / 'works.parquet'))
    assert sample.schema.equals(WORKS)
    assert sample['year'].to_pylist() == [2022] * 3 + [2023] * 3
    report = json.loads((a / 'corpus_stats.json').read_text())
    assert report['n_works'] == 12
    assert report['years'][0]['year'] == 2020
    assert report['years'][0]['n_works'] == 2
    assert report['years'][0]['n_countries'] == 2
    assert report['n_countries'] == 2
    meta = json.loads((a / 'manifest.json').read_text())
    assert meta['corpus_scope'] == 'sample'
    assert meta['source_n_works'] == 12
    assert meta['n_works'] == 6


def test_refuses_false_full_manifest_and_existing_output(tmp_path):
    source = corpus(tmp_path)
    source.with_name('manifest.json').write_text('{}')
    with pytest.raises(ValueError):
        prepare(source, tmp_path / 'out', 'ai', 2026, 2022, 2023, 6, 42)
    assert not (tmp_path / 'out').exists()


def test_underfilled_year_and_invalid_budget(tmp_path):
    source = corpus(tmp_path)
    prepare(source, tmp_path / 'out', 'ai', 2026, 2020, 2021, 10, 42)
    assert pq.read_metadata(tmp_path / 'out/works.parquet').num_rows == 2
    with pytest.raises(FileExistsError):
        prepare(source, tmp_path / 'out', 'ai', 2026, 2020, 2021, 10, 42)
    with pytest.raises(ValueError):
        prepare(source, tmp_path / 'invalid', 'ai', 2026, 2022, 2023, 1, 42)
