"""Схлопывание вариантов термина и отбор разнообразного ТОП-15.

Без дедупа список вырождается: в бэктесте четыре слота из пятнадцати ушли на
единственное/множественное число одного и того же термина. Без MMR получаются
пятнадцать оттенков одной темы.
"""
import numpy as np

НЕИЗМЕНЯЕМЫЕ = {"analysis", "bus", "gas", "lens", "series", "bias", "physics",
                "mathematics", "statistics", "genesis", "basis", "corpus"}


def лемма(слово: str) -> str:
    """Грубая нормализация английского множественного числа.

    Полноценный лемматизатор тянет за собой модель и словари; для схлопывания
    'networks'/'network' достаточно трёх правил.
    """
    w = слово.lower()
    if w in НЕИЗМЕНЯЕМЫЕ or len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if w.endswith("ss"):
        return w
    if w.endswith("s"):
        return w[:-1]
    return w


def _токены(label: str) -> set[str]:
    return {лемма(t) for t in label.split()}


def dedup(rows: list[dict], jaccard: float = 0.6) -> list[dict]:
    """rows должны быть отсортированы по es убыв. Побеждает вариант с большим ES."""
    оставленные: list[dict] = []
    for r in rows:
        токены = _токены(r["label"])
        дубль = False
        for k in оставленные:
            k_токены = _токены(k["label"])
            пересечение = len(токены & k_токены)
            if пересечение and (пересечение / len(токены | k_токены) >= jaccard
                                or токены <= k_токены or k_токены <= токены):
                k.setdefault("aliases", []).append(r["label"])
                дубль = True
                break
        if not дубль:
            r.setdefault("aliases", [])
            оставленные.append(r)
    return оставленные


def mmr(rows: list[dict], emb_by_row: dict[int, np.ndarray], k: int,
        lam: float = 0.7) -> list[dict]:
    """Maximal Marginal Relevance: максимизируем ES при штрафе за близость
    к уже отобранному. Кандидаты без эмбеддинга (термины) штрафа не получают.
    """
    отобранные: list[dict] = []
    остаток = list(rows)
    while остаток and len(отобранные) < k:
        лучший, лучшая_оценка = None, -1e9
        for r in остаток:
            v = emb_by_row.get(r.get("emb_row"))
            похожесть = 0.0
            if v is not None and отобранные:
                похожести = [float(v @ emb_by_row[s["emb_row"]])
                             for s in отобранные if s.get("emb_row") in emb_by_row]
                похожесть = max(похожести) if похожести else 0.0
            оценка = lam * r["es"] - (1 - lam) * похожесть
            if оценка > лучшая_оценка:
                лучший, лучшая_оценка = r, оценка
        отобранные.append(лучший)
        остаток.remove(лучший)
    return отобранные
