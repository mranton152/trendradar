#!/usr/bin/env python3
"""Спайк: на сколько лет препринты опережают журнальные статьи.

Проверяем гипотезу для архитектуры: слабые сигналы надо ловить в препринтах
и коде, а рецензируемые журналы использовать как подтверждающий (запаздывающий)
источник. Год взлёта = первый год, где счётчик достиг 10% своего пика.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openalex_probe import get

TERMS = ["diffusion model", "vision transformer", "large language model",
         "self-supervised learning", "foundation model", "retrieval augmented generation",
         "mixture of experts", "state space model", "graph neural network",
         "federated learning", "neural radiance field", "chain of thought"]


def series(term, typ):
    d = get("/works", {"filter": f'title_and_abstract.search:"{term}",type:{typ}',
                       "group_by": "publication_year"})
    out = {}
    for g in d.get("group_by") or []:
        try:
            y = int(g["key"])
        except (ValueError, TypeError):
            continue
        if 2005 <= y <= 2026:
            out[y] = g["count"]
    return out


def takeoff(counts):
    if not counts:
        return None
    peak = max(counts.values())
    for y in sorted(counts):
        if counts[y] >= max(10, 0.10 * peak):
            return y
    return None


print(f"{'термин':<34}{'препринт':>9}{'статья':>8}{'фора,лет':>10}{'препр.пик':>11}{'ст.пик':>9}")
print("-" * 82)
leads = []
for t in TERMS:
    p, a = series(t, "preprint"), series(t, "article")
    tp, ta = takeoff(p), takeoff(a)
    lead = (ta - tp) if (tp and ta) else None
    if lead is not None:
        leads.append(lead)
    print(f"{t:<34}{str(tp):>9}{str(ta):>8}{str(lead):>10}"
          f"{max(p.values()) if p else 0:>11}{max(a.values()) if a else 0:>9}")
if leads:
    print("-" * 82)
    print(f"медианная фора препринтов: {sorted(leads)[len(leads)//2]} г.  "
          f"(среднее {sum(leads)/len(leads):.1f})")
