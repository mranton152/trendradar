import pytest

from semantic.terms import extract_terms


def test_counts_documents_not_occurrences_and_preserves_contract():
    rows = [
        {"doc_id": "a", "title": "Neural networks neural networks"},
        {"doc_id": "b", "title": "Neural networks"},
        {"doc_id": "c", "title": "Quantum computing"},
    ]
    candidates, links, diagnostics = extract_terms(rows, "ai", 2)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate == {
        "cand_id": candidate["cand_id"],
        "kind": "term",
        "label": "neural networks",
        "aliases": [],
        "top_terms": ["neural networks"],
        "emb_row": None,
        "n_docs": 2,
        "domain": "ai",
    }
    assert links == [
        {"cand_id": candidate["cand_id"], "doc_id": doc, "weight": 1.0} for doc in ["a", "b"]
    ]
    assert diagnostics["n_candidates"] == 1
    assert extract_terms(list(reversed(rows)), "ai", 2) == (candidates, links, diagnostics)
    assert extract_terms(rows, "other", 2)[0][0]["cand_id"] != candidate["cand_id"]


def test_full_corpus_threshold_and_title_only_extraction():
    rows = [
        {
            "doc_id": str(i),
            "title": "Gene editing",
            "year": 2000 + i,
            "abstract": "quantum computing",
        }
        for i in range(20)
    ]
    assert [c["label"] for c in extract_terms(rows, "bio")[0]] == ["gene editing"]
    assert extract_terms(rows[:-1], "bio")[0] == []


def test_invalid_inputs_and_duplicate_documents_fail_explicitly():
    with pytest.raises(ValueError):
        extract_terms([], "ai", 0)
    with pytest.raises(ValueError):
        extract_terms([{"doc_id": "a", "title": ""}] * 2, "ai")


def test_filter_rejections_are_diagnosed():
    candidates, links, diagnostics = extract_terms(
        [{"doc_id": "a", "title": "covid-19 pandemic"}], "ai", 1
    )
    assert candidates == links == []
    assert diagnostics["rejected_by_reason"]
