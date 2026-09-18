"""Ссылочная целостность экспортируемого индекса."""
import json

import numpy as np
import pytest

from semantic.build import cluster_technology_reason, validate_full_manifest, validate_index


def test_sample_provenance_is_bound_to_input_and_retained(tmp_path):
    from semantic.build import sample_provenance
    works = tmp_path / 'works.parquet'
    meta = dict(status='complete', corpus_scope='sample', sha256='samplehash', n_works=5,
                source_sha256='fullhash', source_n_works=100,
                config=dict(domain='ai', as_of=2026), selection='deterministic')
    works.with_name('manifest.json').write_text(json.dumps(meta))
    assert sample_provenance(works, 'samplehash', 5, 'ai', 2026) == meta
    with pytest.raises(ValueError):
        sample_provenance(works, 'wronghash', 5, 'ai', 2026)


def test_dangling_document_is_rejected():
    c = [{"cand_id": "c1", "kind": "term", "emb_row": None, "n_docs": 1}]
    links = [{"cand_id": "c1", "doc_id": "missing"}]
    with pytest.raises(ValueError, match="doc_id"):
        validate_index(c, links, np.empty((0, 1024), dtype=np.float32), {"W1"})


def test_cluster_filter_uses_original_multiword_technology():
    rows = [{"title": "gene editing", "abstract": None}]
    assert cluster_technology_reason(rows) is None


def test_full_scope_requires_matching_manifest_hash(tmp_path):
    manifest = {"status": "complete", "sha256": "original", "n_works": 10,
                "config": {"domain": "ai", "as_of": "2026-09-09"}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        validate_full_manifest(path, "different", 10, "ai", 2026)
    validate_full_manifest(path, "original", 10, "ai", 2026)


def test_wrong_link_count_and_embedding_index_are_rejected():
    c = [{"cand_id": "c1", "kind": "cluster", "emb_row": 1, "n_docs": 1}]
    with pytest.raises(ValueError):
        validate_index(c, [{"cand_id": "c1", "doc_id": "W1"}],
                       np.ones((1, 1024), dtype=np.float32), {"W1"})
    c[0].update(kind="term", emb_row=None, n_docs=2)
    with pytest.raises(ValueError, match="n_docs"):
        validate_index(c, [{"cand_id": "c1", "doc_id": "W1"}],
                       np.empty((0, 1024), dtype=np.float32), {"W1"})
