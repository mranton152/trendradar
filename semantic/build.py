"""Сборка контрактного индекса: документы → кластеры/термины → файлы."""
import argparse
import hashlib
import json
import platform
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, CANDIDATES
from semantic.cluster import assign_clusters, cluster_candidates, reduce_embeddings
from semantic.embed import MODEL, REVISION, atomic_json, encode_resumable
from semantic.filter import technology_reason
from semantic.terms import extract_terms


def cluster_technology_reason(rows):
    # Не склеиваем top_terms: их порядок отражает веса, а не исходные фразы.
    if any(technology_reason(row["title"]) is None for row in rows):
        return None
    return "нет технологических маркеров в исходных заголовках кластера"


def validate_full_manifest(path, corpus_hash, n_docs, domain, as_of):
    meta = json.loads(Path(path).read_text(encoding="utf-8"))
    config = meta.get("config", {})
    if (meta.get("status") != "complete" or meta.get("sha256") != corpus_hash
            or meta.get("n_works") != n_docs or config.get("domain") != domain
            or not str(config.get("as_of", "")).startswith(f"{as_of}-")):
        raise ValueError("Корпус не соответствует manifest завершённого сбора")


def validate_index(candidates, links, embeddings, doc_ids):
    ids = {c["cand_id"] for c in candidates}
    if len(ids) != len(candidates):
        raise ValueError("Повтор cand_id")
    if any(link["doc_id"] not in doc_ids for link in links):
        raise ValueError("Неизвестный doc_id")
    if any(link["cand_id"] not in ids for link in links):
        raise ValueError("Неизвестный cand_id")
    pairs = {(link["cand_id"], link["doc_id"]) for link in links}
    if len(pairs) != len(links):
        raise ValueError("Повтор связи")
    counts = Counter(link["cand_id"] for link in links)
    if any(c["n_docs"] != counts[c["cand_id"]] for c in candidates):
        raise ValueError("n_docs не совпадает с числом связей")
    emb_rows = [c["emb_row"] for c in candidates if c["kind"] == "cluster"]
    if sorted(emb_rows) != list(range(len(emb_rows))):
        raise ValueError("Некорректный emb_row")
    if any(c["emb_row"] is not None for c in candidates if c["kind"] == "term"):
        raise ValueError("У термина emb_row должен быть null")
    if embeddings.shape != (len(emb_rows), 1024) or embeddings.dtype != np.float32:
        raise ValueError("Некорректный массив embeddings.npy")
    if not np.isfinite(embeddings).all() or not np.allclose(
            np.linalg.norm(embeddings, axis=1), 1, atol=1e-5):
        raise ValueError("Эмбеддинги не нормированы")


def sample_provenance(works, corpus_hash, n_docs, domain, as_of):
    path = Path(works).with_name('manifest.json')
    if not path.exists():
        return None
    meta = json.loads(path.read_text(encoding='utf-8'))
    if meta.get('corpus_scope') != 'sample':
        return None
    if (meta.get('status') != 'complete' or meta.get('sha256') != corpus_hash
            or meta.get('n_works') != n_docs or meta.get('config', {}).get('domain') != domain
            or meta.get('config', {}).get('as_of') != as_of):
        raise ValueError('Sample manifest does not match the input corpus')
    return meta


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--works", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--scope", required=True, choices=["sample", "full", "live"])
    parser.add_argument("--as-of", type=int, required=True)
    parser.add_argument("--min-docs", type=int, default=20)
    parser.add_argument("--min-cluster-size", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--terms-only", action="store_true")
    parser.add_argument("--max-documents", type=int, default=200000)
    args = parser.parse_args()
    if args.scope == 'live':
        args.terms_only = True
        args.min_docs = 3
    if args.output.exists():
        parser.error("Каталог результата уже существует; задайте новый --output")
    if args.scope == "full":
        source_meta = args.works.parent / "manifest.json"
        if not source_meta.exists() or json.loads(source_meta.read_text(encoding="utf-8")).get(
                "status") != "complete":
            parser.error("Для full нужен manifest завершённого полного сбора")
    n_docs = pq.read_metadata(args.works).num_rows
    if n_docs < 1 or n_docs > args.max_documents:
        parser.error("Число документов вне лимита памяти; увеличьте --max-documents осознанно")
    columns = ["doc_id", "title", "abstract", "domain", "year"]
    if args.scope == 'live':
        columns.append('source')
    rows = pq.read_table(args.works, columns=columns).to_pylist()
    if len({r["doc_id"] for r in rows}) != len(rows):
        parser.error("Корпус содержит повторяющиеся doc_id")
    if any(r["domain"] != args.domain or r["year"] > args.as_of for r in rows):
        parser.error("Домен или год корпуса не соответствует параметрам")
    corpus_hash = fingerprint(args.works)
    live_meta = None
    if args.scope == 'live':
        live_meta = json.loads(args.works.with_name('meta.json').read_text(encoding='utf-8'))
        if (live_meta.get('domain') != args.domain or live_meta.get('n_docs') != n_docs
                or live_meta.get('corpus_sha256') != corpus_hash):
            parser.error('Live meta не соответствует корпусу: домен, число строк или SHA256')
    provenance = (sample_provenance(args.works, corpus_hash, n_docs, args.domain, args.as_of)
                  if args.scope == 'sample' else None)
    if args.scope == "full":
        validate_full_manifest(args.works.parent / "manifest.json", corpus_hash,
                               len(rows), args.domain, args.as_of)
    if args.scope == 'live':
        from semantic.live import extract_live
        candidates, links, terms_meta = extract_live(rows, args.domain)
    else:
        candidates, links, terms_meta = extract_terms(rows, args.domain, args.min_docs)
    centers = np.empty((0, 1024), dtype=np.float32)
    comparison, rejected_clusters, embedding_meta = [], [], {}
    if not args.terms_only:
        document_vectors, embedding_meta = encode_resumable(
            rows, args.cache / corpus_hash, corpus_hash, batch_size=args.batch_size,
            device=args.device, cache_folder=str(args.model_cache) if args.model_cache else None)
        reduced_file = args.cache / corpus_hash / "reduced.npy"
        if reduced_file.exists():
            reduced = np.load(reduced_file)
            if reduced.shape != (len(rows), 5):
                raise ValueError("Несовпадение UMAP-кэша")
        else:
            reduced = reduce_embeddings(document_vectors)
            temp = reduced_file.with_suffix(".tmp")
            with temp.open("wb") as stream:
                np.save(stream, reduced)
            temp.replace(reduced_file)
        selected_labels = None
        for size in sorted({10, 25, 50, args.min_cluster_size}):
            labels = assign_clusters(reduced, size)
            sizes = Counter(int(x) for x in labels if x >= 0)
            comparison.append({"min_cluster_size": size, "n_clusters": len(sizes),
                               "noise_fraction": float(np.mean(labels == -1)),
                               "cluster_sizes": sorted(sizes.values())})
            if size == args.min_cluster_size:
                selected_labels = labels
        clusters, cluster_links, vectors = cluster_candidates(
            rows, document_vectors, selected_labels, args.domain)
        kept_ids, kept_vectors = set(), []
        rows_by_id = {row["doc_id"]: row for row in rows}
        docs_by_cluster = {}
        for link in cluster_links:
            docs_by_cluster.setdefault(link["cand_id"], []).append(rows_by_id[link["doc_id"]])
        for cluster in clusters:
            reason = cluster_technology_reason(docs_by_cluster[cluster["cand_id"]])
            if reason:
                rejected_clusters.append({"label": cluster["label"], "reason": reason,
                                          "n_docs": cluster["n_docs"]})
                continue
            kept_vectors.append(vectors[cluster["emb_row"]])
            cluster["emb_row"] = len(kept_vectors) - 1
            candidates.append(cluster)
            kept_ids.add(cluster["cand_id"])
        centers = np.asarray(kept_vectors, dtype=np.float32).reshape(-1, 1024)
        links.extend(link for link in cluster_links if link["cand_id"] in kept_ids)
    validate_index(candidates, links, centers, {r["doc_id"] for r in rows})
    packages = {}
    for package in ["numpy", "pyarrow", "sentence-transformers", "torch", "umap-learn", "hdbscan"]:
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            pass
    meta = {"domain": args.domain, "domain_query": args.domain.replace("-", " "),
            "as_of": args.as_of, "built_at": datetime.now(UTC).isoformat(),
            "n_works": len(rows), "n_candidates": len(candidates), "n_links": len(links),
            "embedding_model": MODEL, "embedding_revision": REVISION,
            "methodology_version": "1.0", "corpus_scope": args.scope,
            "corpus_sha256": corpus_hash, "stages": {"semantic": "terms-only" if args.terms_only
                                                     else "terms-and-clusters"},
            "embedding_run": embedding_meta, "min_cluster_size": args.min_cluster_size,
            "terms": terms_meta, "cluster_comparison": comparison,
            "rejected_clusters": rejected_clusters, "packages": packages,
            "python": platform.python_version(),
            "filter_method": "lexical-heuristic-v3" if args.scope == 'live'
                             else "lexical-heuristic-v2"}
    if provenance:
        meta['sample_manifest'] = provenance
        meta['cluster_membership_scope'] = 'sample_only'
        stats_path = args.works.with_name('corpus_stats.json')
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding='utf-8'))
            if (stats.get('source_sha256') != provenance.get('source_sha256')
                    or stats.get('n_works') != provenance.get('source_n_works')):
                raise ValueError('Corpus statistics do not match sample provenance')
            meta['full_corpus_statistics'] = stats
    if live_meta:
        meta['domain_query'] = live_meta['domain_query']
        meta['live_ingest'] = live_meta
        meta['n_sources_polled'] = live_meta['n_sources_polled']
    stage = args.output.with_name(args.output.name + ".building-" + uuid.uuid4().hex[:8])
    stage.mkdir(parents=True)
    try:
        pq.write_table(pa.Table.from_pylist(candidates, schema=CANDIDATES),
                       stage / "candidates.parquet", compression="zstd")
        pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                       stage / "cand_docs.parquet", compression="zstd")
        np.save(stage / "embeddings.npy", centers)
        atomic_json(stage / "meta.json", meta)
        # Корпус рядом с индексом нужен потребителям и офлайн-проверкам.
        shutil.copyfile(args.works, stage / "works.parquet")
        stage.rename(args.output)
    except Exception:
        # Незавершённый stage остаётся для диагностики; старый индекс не затрагивается.
        raise
    print(f"Индекс: {args.output}; кандидатов {len(candidates)}, связей {len(links)}", flush=True)


if __name__ == "__main__":
    main()
