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

from contracts.schemas import REJECTED, TRENDS
from core.components import components
from core.dedup import dedup, mmr
from core.filters import ПОРОГИ, причина_отказа
from core.normalize import peer_normalizer
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, emergence_scores, стадия, уверенность
from core.series import country_spread, top_docs, year_counts


def построить(index_dir: Path, corpus_path: Path, domain: str,
              as_of: int, top: int = 15) -> list[dict]:
    """Только тренды. Отсеянные — через построить_с_отсеянными."""
    return построить_с_отсеянными(index_dir, corpus_path, domain, as_of, top)[0]


def построить_с_отсеянными(index_dir: Path, corpus_path: Path, domain: str,
                          as_of: int, top: int = 15) -> tuple[list[dict], list[dict]]:
    """Тренды и отсеянные кандидаты с причинами.

    ТЗ требует показывать причины исключения зрелых технологий и нерелевантных
    кандидатов. Раньше причины считались в Counter и печатались в stderr -
    теперь каждая сохраняется и уезжает на экран. lynching tree с нулём стран
    должен быть виден: это наш аргумент, а не наш позор.
    """
    index_dir, corpus_path = Path(index_dir), Path(corpus_path)
    полные_ряды = year_counts(index_dir, corpus_path)
    ряды = полные_ряды
    страны = country_spread(index_dir, corpus_path, as_of - 2, as_of)
    подписи = {r[0]: (r[1], r[2]) for r in duckdb.connect().execute(
        "SELECT cand_id, label, emb_row FROM read_parquet(?)",
        [str(index_dir / "candidates.parquet")]).fetchall()}

    # срез: в режиме бэктеста будущее не должно просачиваться в расчёт
    ряды = {c: {y: n for y, n in s.items() if y <= as_of} for c, s in ряды.items()}
    окно = list(range(as_of - 6, as_of + 1))
    norm = peer_normalizer(list(ряды.values()), окно)

    строки, отказы, отсеянные = [], Counter(), []
    for cand_id, counts in ряды.items():
        if cand_id not in подписи:
            continue
        comp = components(counts, norm, as_of)
        причина = причина_отказа(comp, страны.get(cand_id, 0))
        if причина:
            отказы[причина] += 1
            отсеянные.append({"cand_id": cand_id, "label": подписи[cand_id][0],
                              "domain": domain, "reason": причина,
                              "n_docs": comp["counts_recent"], "as_of": as_of})
            continue
        label, emb_row = подписи[cand_id]
        строки.append({"cand_id": cand_id, "label": label, "emb_row": emb_row,
                       "c": comp, "counts": counts,
                       "countries": страны.get(cand_id, 0)})

    строки = emergence_scores(строки)
    строки = dedup(строки)
    зрелые = [r for r in строки if r["maturity_pct"] >= ПОРОГИ["MAX_MATURITY_PCT"]]
    строки = [r for r in строки if r["maturity_pct"] < ПОРОГИ["MAX_MATURITY_PCT"]]
    отказы["уже мейнстрим"] = len(зрелые)
    отсеянные.extend({"cand_id": r["cand_id"], "label": r["label"], "domain": domain,
                      "reason": "уже мейнстрим", "n_docs": r["c"]["counts_recent"],
                      "as_of": as_of} for r in зрелые)

    эмб_путь = index_dir / "embeddings.npy"
    эмб = np.load(эмб_путь) if эмб_путь.exists() else np.zeros((0, 1))
    emb_by_row = {i: эмб[i] for i in range(len(эмб))}
    строки = mmr(строки, emb_by_row, k=top)

    sys.stderr.write(f"[core] прошло {len(строки)} из {len(ряды)}; "
                     f"отсеяно: {dict(отказы)}\n")

    итог = []
    for ранг, r in enumerate(строки, 1):
        c = r["c"]
        # бэктест: что тренд сделал ПОСЛЕ среза. Только для среза в прошлом;
        # берём полные ряды, срезанные будущего не знают.
        бт = _бэктест(полные_ряды.get(r["cand_id"], {}), as_of)
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
            "top_doc_ids": top_docs(index_dir, corpus_path, r["cand_id"],
                                    since=c["takeoff_year"]),
            "stage": стадия(c, r["maturity_pct"]),
            "confidence": уверенность(c, r["countries"]),
            "methodology_version": ВЕРСИЯ_МЕТОДОЛОГИИ,
            **бт,
        })
    return итог, отсеянные


def _бэктест(counts: dict[int, int], as_of: int) -> dict:
    """Что было после среза. При срезе в текущем году будущего нет - все None."""
    текущий = dt.date.today().year
    if as_of >= текущий or not counts:
        return {"bt_at_cutoff": None, "bt_peak_after": None, "bt_growth_x": None}
    на_срезе = int(counts.get(as_of, 0))
    после = max((int(n) for y, n in counts.items() if y > as_of), default=0)
    return {"bt_at_cutoff": на_срезе, "bt_peak_after": после,
            "bt_growth_x": round((после + 1) / (на_срезе + 1), 2)}


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

    строки, отсеянные = построить_с_отсеянными(index_dir, corpus, args.domain,
                                                args.as_of, args.top)
    путь = index_dir / "trends.parquet"
    pq.write_table(pa.Table.from_pylist(строки, schema=TRENDS), путь, compression="zstd")
    pq.write_table(pa.Table.from_pylist(отсеянные, schema=REJECTED),
                   index_dir / "rejected.parquet", compression="zstd")

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
