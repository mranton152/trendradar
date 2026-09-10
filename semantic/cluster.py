"""Кластеры и c-TF-IDF по фиксированному рецепту брифа."""
import hashlib

import numpy as np


def ctfidf_labels(documents):
    from scipy import sparse
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.preprocessing import normalize

    vectorizer = CountVectorizer(stop_words="english", max_features=50000)
    try:
        counts = vectorizer.fit_transform(documents)
    except ValueError as error:
        if "empty vocabulary" not in str(error):
            raise
        return [[] for _ in documents], sparse.csr_matrix((len(documents), 0))
    average_length = int(np.asarray(counts.sum(axis=1)).mean())
    frequency = np.asarray(counts.sum(axis=0)).ravel()
    idf = np.log1p(average_length / frequency)
    scores = normalize(counts.astype(float), norm="l1", axis=1).multiply(idf).tocsr()
    terms = vectorizer.get_feature_names_out()
    labels = []
    for row in scores:
        order = sorted(zip(row.indices, row.data, strict=True),
                       key=lambda item: (-item[1], terms[item[0]]))
        labels.append([str(terms[index]) for index, score in order[:10] if score > 0])
    return labels, scores


def reduce_embeddings(embeddings):
    import umap

    if len(embeddings) < 8:
        raise ValueError("Для UMAP требуется не менее 8 документов")
    return umap.UMAP(n_neighbors=15, n_components=5, min_dist=0.0,
                     metric="cosine", random_state=42).fit_transform(embeddings)


def assign_clusters(reduced, min_cluster_size=25):
    import hdbscan

    return hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=5,
                           metric="euclidean", cluster_selection_method="eom").fit_predict(reduced)


def cluster_candidates(rows, embeddings, assignments, domain):
    groups = {}
    if embeddings.shape != (len(rows), 1024) or len(assignments) != len(rows):
        raise ValueError("Несовпадение документов, векторов и кластеров")
    for index, label in enumerate(assignments):
        if label >= 0:
            groups.setdefault(int(label), []).append(index)
    ordered = sorted(groups.values(), key=lambda ids: min(rows[i]["doc_id"] for i in ids))
    if not ordered:
        return [], [], np.empty((0, 1024), dtype=np.float32)
    texts = [" ".join(rows[i]["title"] + ". " + (rows[i].get("abstract") or "")
                      for i in indices) for indices in ordered]
    names, _ = ctfidf_labels(texts)
    candidates, links, centers = [], [], []
    for indices, terms in zip(ordered, names, strict=True):
        vector = np.asarray(embeddings[indices].mean(axis=0), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            raise ValueError("Нулевой/нечисловой центроид")
        vector /= norm
        ids = sorted(rows[i]["doc_id"] for i in indices)
        digest = hashlib.sha256((domain + "\n" + "\n".join(ids)).encode()).hexdigest()[:20]
        cand_id = f"c:{domain}:{digest}"
        candidates.append({"cand_id": cand_id, "kind": "cluster", "label": " ".join(terms[:4]),
                           "aliases": [], "top_terms": terms, "emb_row": len(centers),
                           "n_docs": len(ids), "domain": domain})
        centers.append(vector)
        links.extend({"cand_id": cand_id, "doc_id": rows[i]["doc_id"],
                      "weight": float(np.clip(np.dot(embeddings[i], vector), 0, 1))}
                     for i in indices)
    return candidates, links, np.asarray(centers, dtype=np.float32)
