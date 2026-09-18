"""Полная описательная статистика и воспроизводимая выборка для кластеров."""
import argparse
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import WORKS
from semantic.build import fingerprint, validate_full_manifest
from semantic.embed import atomic_json


def prepare(works, output, domain, as_of, first_year=2022, last_year=2026,
            max_documents=100000, seed=42):
    works, output = Path(works), Path(output)
    if output.exists():
        raise FileExistsError(output)
    if first_year > last_year or last_year > as_of or max_documents < last_year - first_year + 1:
        raise ValueError('Invalid sample years or document budget')
    source = pq.ParquetFile(works)
    if not source.schema_arrow.equals(WORKS, check_metadata=False):
        raise ValueError('WORKS schema mismatch')
    print('Checking full corpus fingerprint', flush=True)
    source_hash = fingerprint(works)
    validate_full_manifest(works.parent / 'manifest.json', source_hash,
                           source.metadata.num_rows, domain, as_of)
    stage = output.with_name(output.name + '.building-' + uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    with duckdb.connect() as db:
        db.execute("SET memory_limit = '2GB'")
        db.execute('SET threads = 2')
        db.execute('SET preserve_insertion_order = false')
        db.execute('SET temp_directory = ?', [str(stage / 'spill')])
        db.read_parquet(str(works)).create_view('works')
        invalid = db.execute('SELECT count(*) FROM works WHERE domain IS DISTINCT FROM ? '
                             'OR year > ? OR doc_id IS NULL OR title IS NULL OR url IS NULL',
                             [domain, as_of]).fetchone()[0]
        if invalid:
            raise ValueError('Invalid domain, year or required values in corpus')
        print('Computing full corpus year and country coverage', flush=True)
        rows = db.execute("SELECT year, count(*) n_works, "
                          "count(*) FILTER (WHERE abstract IS NOT NULL AND trim(abstract) <> '') "
                          "n_abstracts, count(*) FILTER (WHERE doi IS NOT NULL) n_dois "
                          'FROM works GROUP BY year ORDER BY year').fetchall()
        countries = dict(db.execute('SELECT year, count(DISTINCT country) FROM works, '
                                    'UNNEST(countries) AS t(country) '
                                    "WHERE country IS NOT NULL AND country <> '' "
                                    'GROUP BY year').fetchall())
        global_countries = db.execute('SELECT count(DISTINCT country) FROM works, '
                                      'UNNEST(countries) AS t(country) '
                                      "WHERE country IS NOT NULL AND country <> ''").fetchone()[0]
        stats = dict(n_works=source.metadata.num_rows, n_countries=global_countries,
                     source_sha256=source_hash, corpus_scope='full',
                     note='Descriptive corpus coverage; not candidate emergence scores.',
                     years=[dict(year=y, n_works=n, n_abstracts=a, n_dois=d,
                                 n_countries=countries.get(y, 0)) for y, n, a, d in rows])
        atomic_json(stage / 'corpus_stats.json', stats)
        n_years = last_year - first_year + 1
        base, remainder = divmod(max_documents, n_years)
        quotas = {y: base + int(y - first_year < remainder)
                  for y in range(first_year, last_year + 1)}
        db.register('quotas', pa.table({'year': list(quotas), 'quota': list(quotas.values())}))
        print(f'Selecting up to {max_documents} across {first_year}-{last_year}', flush=True)
        db.execute('CREATE TEMP TABLE selected AS SELECT doc_id FROM ('
                   'SELECT doc_id, year, row_number() OVER (PARTITION BY year '
                   "ORDER BY sha256(doc_id || ':' || ?), doc_id) AS rn FROM works "
                   'WHERE year BETWEEN ? AND ?) AS ranked JOIN quotas USING(year) '
                   'WHERE rn <= quota', [str(seed), first_year, last_year])
        reader = db.execute('SELECT w.* FROM works w JOIN selected s USING(doc_id) '
                            'ORDER BY w.year, w.doc_id').fetch_record_batch(8192)
        count = 0
        with pq.ParquetWriter(stage / 'works.parquet', WORKS, compression='zstd') as writer:
            for batch in reader:
                table = pa.Table.from_batches([batch]).cast(WORKS)
                writer.write_table(table)
                count += table.num_rows
        sample_counts = dict(db.execute('SELECT year, count(*) FROM works JOIN selected '
                                        'USING(doc_id) GROUP BY year ORDER BY year').fetchall())
    atomic_json(stage / 'manifest.json', dict(
        status='complete', corpus_scope='sample', n_works=count,
        source_n_works=source.metadata.num_rows,
        source_sha256=source_hash, sha256=fingerprint(stage / 'works.parquet'),
        built_at=datetime.now(UTC).isoformat(), config=dict(domain=domain, as_of=as_of,
        first_year=first_year, last_year=last_year, max_documents=max_documents, seed=seed),
        selection='equal-year-quota-sha256-doc-id-seed-v1', quotas=quotas,
        counts_by_year=sample_counts,
        limitations=['Recent-year sample; not full historical cluster membership.',
                     'Underfilled year quotas are not reassigned.',
                     'Latest year may be incomplete at the corpus cutoff.']))
    stage.rename(output)
    print(f'Prepared {count} sample documents: {output}', flush=True)
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--works', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--domain', required=True)
    p.add_argument('--as-of', required=True, type=int)
    p.add_argument('--first-year', default=2022, type=int)
    p.add_argument('--last-year', default=2026, type=int)
    p.add_argument('--max-documents', default=100000, type=int)
    p.add_argument('--seed', default=42, type=int)
    a = p.parse_args()
    prepare(a.works, a.output, a.domain, a.as_of, a.first_year, a.last_year,
            a.max_documents, a.seed)


if __name__ == '__main__':
    main()
