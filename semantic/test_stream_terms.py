import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from contracts.schemas import CAND_DOCS, CANDIDATES, WORKS
from semantic.terms import extract_terms

spec = importlib.util.spec_from_file_location(
    "stream_terms", Path(__file__).with_name("stream_terms.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def corpus(tmp_path, titles):
    rows = [
        {"doc_id": str(i), "title": title, "domain": "ai", "year": 2026}
        for i, title in enumerate(titles)
    ]
    path = tmp_path / "works.parquet"
    for row in rows:
        row.update(
            source="openalex",
            doc_type="article",
            url="https://example.org",
            harvested_at="2026-09-09",
        )
    schema = WORKS
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    manifest = {
        "status": "complete",
        "config": {"domain": "ai", "as_of": "2026-09-09"},
        "n_works": len(rows),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return rows, path


@pytest.mark.parametrize(
    "titles",
    [
        [],
        ["medical disease", "plain subject"],
        [
            "neural networks neural networks",
            "neural networks",
            "quantum computing",
            "quantum computing",
            "learning neural",
            "neural networks for learning",
        ],
    ],
)
def test_equivalence(tmp_path, titles):
    rows, path = corpus(tmp_path, titles)
    output = tmp_path / "out"
    meta = module.export_terms(path, output, "ai", min_docs=2, batch_size=1)
    expected, links, _ = extract_terms(rows, "ai", min_docs=2)
    actual = pq.read_table(output / "candidates.parquet")
    actual_links = pq.read_table(output / "cand_docs.parquet")
    assert actual.schema == CANDIDATES
    assert actual_links.schema == CAND_DOCS
    assert actual.to_pylist() == expected
    assert actual_links.to_pylist() == links
    emb = np.load(output / "embeddings.npy")
    assert emb.shape == (0, 1024) and emb.dtype == np.float32
    assert meta["corpus_scope"] == "full"
    assert meta["n_works"] == len(rows)
    assert not (output / "works.parquet").exists()


@pytest.mark.parametrize("change", ["domain", "status", "sha256", "n_works"])
def test_bad_manifest(tmp_path, change):
    _, path = corpus(tmp_path, ["neural networks"])
    mp = tmp_path / "manifest.json"
    manifest = json.loads(mp.read_text())
    if change == "domain":
        manifest["config"]["domain"] = "other"
    else:
        manifest[change] = {"status": "partial", "sha256": "bad", "n_works": 9}[change]
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.export_terms(path, tmp_path / "out", "ai")
    assert not (tmp_path / "out").exists()


def test_wrong_row_domain(tmp_path):
    _, path = corpus(tmp_path, ["neural networks"])
    table = pq.read_table(path).set_column(
        WORKS.get_field_index("domain"), WORKS.field("domain"), pa.array(["wrong"])
    )
    pq.write_table(table, path)
    mp = tmp_path / "manifest.json"
    manifest = json.loads(mp.read_text())
    manifest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="domain"):
        module.export_terms(path, tmp_path / "out", "ai")
    assert not (tmp_path / "out").exists()


def test_streaming_batches(tmp_path, monkeypatch):
    _, path = corpus(tmp_path, ["neural networks"] * 7)
    original = module.pq.ParquetFile
    sizes = []

    class Guard:
        def __init__(self, source):
            self.inner = original(source)
            self.metadata = self.inner.metadata
            self.schema_arrow = self.inner.schema_arrow

        def iter_batches(self, **kwargs):
            assert kwargs["batch_size"] == 2
            for batch in self.inner.iter_batches(**kwargs):
                sizes.append(batch.num_rows)
                yield batch

        def close(self):
            self.inner.close()

    monkeypatch.setattr(module.pq, "ParquetFile", Guard)
    module.export_terms(path, tmp_path / "out", "ai", batch_size=2)
    assert sizes == [2, 2, 2, 1] * 2


def test_duplicate_doc_ids(tmp_path):
    _, path = corpus(tmp_path, ["neural networks"] * 2)
    table = pq.read_table(path).set_column(
        0, WORKS.field("doc_id"), pa.array(["same", "same"])
    )
    pq.write_table(table, path)
    mp = tmp_path / "manifest.json"
    manifest = json.loads(mp.read_text())
    manifest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    mp.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="doc_id"):
        module.export_terms(path, tmp_path / "out", "ai", batch_size=1)
    assert not (tmp_path / "out").exists()

