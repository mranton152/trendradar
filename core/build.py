"""Стадия core: кандидаты -> ранжированный ТОП с доказательной базой.

    python -m core.build --domain artificial-intelligence --as-of 2026
    python -m core.build --domain artificial-intelligence --as-of 2021   # бэктест

Режим as_of пронизывает весь расчёт: при срезе в прошлом будущие данные
не должны просачиваться никуда, иначе бэктест врёт в нашу пользу.
"""
import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import TRENDS
from core.components import components
from core.dedup import dedup, mmr
from core.filters import ПОРОГИ, причина_отказа
from core.normalize import peer_normalizer
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, emergence_scores, стадия, уверенность
from core.series import country_spread, top_docs, year_counts


def построить(index_dir: Path, corpus_path: Path, domain: str,
              as_of: int, top: int = 15) -> list[dict]:
    index_dir, corpus_path = Path(index_dir), Path(corpus_path)
    ряды = year_counts(index_dir, corpus_path)
    страны = country_spread(index_dir, corpus_path, as_of - 2, as_of)
    подписи = {r[0]: (r[1], r[2]) for r in duckdb.connect().execute(
        "SELECT cand_id, label, emb_row FROM read_parquet(?)",
        [str(index_dir / "candidates.parquet")]).fetchall()}

    # срез: в режиме бэктеста будущее не должно просачиваться в расчёт
    ряды = {c: {y: n for y, n in s.items() if y <= as_of} for c, s in ряды.items()}
    окно = list(range(as_of - 6, as_of + 1))
    norm = peer_normalizer(list(ряды.values()), окно)

    строки, отказы = [], Counter()
    for cand_id, counts in ряды.items():
        if cand_id not in подписи:
            continue
        comp = components(counts, norm, as_of)
        причина = причина_отказа(comp, страны.get(cand_id, 0))
        if причина:
            отказы[причина] += 1
            continue
        label, emb_row = подписи[cand_id]
        строки.append({"cand_id": cand_id, "label": label, "emb_row": emb_row,
                       "c": comp, "counts": counts,
                       "countries": страны.get(cand_id, 0)})

    строки = emergence_scores(строки)
    строки = dedup(строки)
    до_зрелости = len(строки)
    строки = [r for r in строки if r["maturity_pct"] < ПОРОГИ["MAX_MATURITY_PCT"]]
    отказы["уже мейнстрим"] = до_зрелости - len(строки)

    эмб_путь = index_dir / "embeddings.npy"
    эмб = np.load(эмб_путь) if эмб_путь.exists() else np.zeros((0, 1))
    emb_by_row = {i: эмб[i] for i in range(len(эмб))}
    строки = mmr(строки, emb_by_row, k=top)

    sys.stderr.write(f"[core] прошло {len(строки)} из {len(ряды)}; "
                     f"отсеяно: {dict(отказы)}\n")

    итог = []
    for ранг, r in enumerate(строки, 1):
        c = r["c"]
        итог.append({
            "trend_id": f"t:{domain}:{as_of}:{ранг:02d}",
            "domain": domain, "as_of": as_of, "rank": ранг,
            "cand_id": r["cand_id"], "label": r["label"],
            "aliases": r.get("aliases", []),
            "emergence_score": float(r["es"]),
            "c_novelty": float(r["parts"]["novelty"]),
            "c_growth": float(r["parts"]["growth"]),
            "c_accel": float(r["parts"]["accel"]),
            "c_burst": float(r["parts"]["burst"]),
            "c_diffusion": float(r["parts"]["diffusion"]),
            "maturity_pct": float(r["maturity_pct"]),
            "first_mention": c["first_mention"], "takeoff_year": c["takeoff_year"],
            "years": c["years"], "counts": c["counts_series"],
            "freq_per_million": [float(f) for f in c["freq_series"]],
            "n_docs": c["counts_recent"], "n_countries": r["countries"],
            "n_orgs": None, "n_patents": None,
            "top_doc_ids": top_docs(index_dir, corpus_path, r["cand_id"]),
            "stage": стадия(c, r["maturity_pct"]),
            "confidence": уверенность(c, r["countries"]),
            "methodology_version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        })
    return итог


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--as-of", type=int, default=dt.date.today().year)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    index_dir = Path("data/index") / args.domain
    corpus = Path("data/corpus") / args.domain / "works.parquet"
    if not corpus.exists():
        corpus = index_dir / "works.parquet"
    if not corpus.exists():
        raise SystemExit(f"нет корпуса: ни data/corpus/{args.domain}/, ни {index_dir}")

    строки = построить(index_dir, corpus, args.domain, args.as_of, args.top)
    путь = index_dir / "trends.parquet"
    pq.write_table(pa.Table.from_pylist(строки, schema=TRENDS), путь, compression="zstd")

    meta = index_dir / "meta.json"
    m = json.loads(meta.read_text()) if meta.exists() else {}
    m.setdefault("stages", {})["core"] = dt.date.today().isoformat()
    m["methodology_version"] = ВЕРСИЯ_МЕТОДОЛОГИИ
    meta.write_text(json.dumps(m, ensure_ascii=False, indent=2))

    print(f"{'#':>2} {'ES':>6} {'тренд':<44} {'взлёт':>6} {'публ':>7} {'стран':>5}")
    print("-" * 78)
    for r in строки:
        print(f"{r['rank']:>2} {r['emergence_score']:>6.3f} {r['label'][:44]:<44} "
              f"{str(r['takeoff_year']):>6} {r['n_docs']:>7} {r['n_countries']:>5}")


if __name__ == "__main__":
    main()
