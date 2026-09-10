"""Численная корректность c-TF-IDF и центроидов."""
import numpy as np

from semantic.cluster import assign_clusters, cluster_candidates, ctfidf_labels, reduce_embeddings


def test_ctfidf_uses_total_term_frequency_not_document_frequency():
    labels, scores = ctfidf_labels(["laser laser optics", "quantum optics optics"])
    expected = np.array([[2 / 3 * np.log(2.5), 1 / 3 * np.log(2), 0],
                         [0, 2 / 3 * np.log(2), 1 / 3 * np.log(4)]])
    np.testing.assert_allclose(scores.toarray(), expected)
    assert labels[0][0] == "laser"
    # Одинаковые веса optics/quantum: детерминированный алфавитный порядок.
    assert labels[1][:2] == ["optics", "quantum"]


def test_noise_excluded_and_centroid_indices_align():
    rows = [{"doc_id": f"openalex:W{i}", "title": "quantum optics", "abstract": None}
            for i in range(3)]
    emb = np.zeros((3, 1024), dtype=np.float32)
    emb[0, 0] = emb[1, 1] = emb[2, 2] = 1
    candidates, links, centers = cluster_candidates(rows, emb, np.array([7, 7, -1]), "ai")
    assert len(candidates) == 1 and candidates[0]["emb_row"] == 0
    assert candidates[0]["n_docs"] == 2 and len(links) == 2
    assert {link["doc_id"] for link in links} == {"openalex:W0", "openalex:W1"}
    assert centers.shape == (1, 1024) and centers.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(centers, axis=1), 1)
    np.testing.assert_allclose(centers[0, :2], [2 ** -.5, 2 ** -.5])


def test_real_umap_hdbscan_separates_two_well_separated_groups():
    rng = np.random.default_rng(42)
    vectors = rng.normal(0, 0.001, (60, 1024)).astype(np.float32)
    vectors[:30, 0] += 1
    vectors[30:, 1] += 1
    vectors /= np.linalg.norm(vectors, axis=1)[:, None]
    reduced = reduce_embeddings(vectors)
    assert reduced.shape == (60, 5) and np.isfinite(reduced).all()
    labels = assign_clusters(reduced, 10)
    assert len(set(labels[:30])) == 1
    assert len(set(labels[30:])) == 1
    assert labels[0] >= 0 and labels[30] >= 0 and labels[0] != labels[30]
