"""Emergence Score = взвешенная сумма перцентильных рангов × штраф за зрелость.

Веса подлежат калибровке на бэктесте (см. validation/). Менять их вручную
«на глаз» нельзя: любое изменение обязано улучшать Precision@15 на срезе 2021.
"""
import math

from core.components import pct_rank

ВЕРСИЯ_МЕТОДОЛОГИИ = "1.0"

ВЕСА = {"novelty": 0.20, "growth": 0.32, "accel": 0.23, "burst": 0.15, "diffusion": 0.10}
ШТРАФ_ЗА_ЗРЕЛОСТЬ = 0.5


def emergence_scores(rows: list[dict]) -> list[dict]:
    """Каждой строке добавляет es, parts и maturity_pct. Сортирует по убыванию es."""
    nov = pct_rank([-r["c"]["age"] for r in rows])
    gro = pct_rank([r["c"]["growth"] for r in rows])
    acc = pct_rank([r["c"]["accel"] for r in rows])
    bur = pct_rank([math.log(r["c"]["burst"] + 0.01) for r in rows])
    dif = pct_rank([float(r.get("countries", 0)) for r in rows])
    mat = pct_rank([r["c"]["maturity"] for r in rows])

    for i, r in enumerate(rows):
        части = {"novelty": nov[i], "growth": gro[i], "accel": acc[i],
                 "burst": bur[i], "diffusion": dif[i]}
        сырой = sum(ВЕСА[k] * v for k, v in части.items())
        # уже мейнстрим -> не зарождающийся тренд
        r["parts"] = {k: round(v, 3) for k, v in части.items()}
        r["maturity_pct"] = round(mat[i], 3)
        r["es"] = round(сырой * (1.0 - ШТРАФ_ЗА_ЗРЕЛОСТЬ * mat[i]), 4)

    rows.sort(key=lambda r: r["es"], reverse=True)
    return rows


def стадия(comp: dict, maturity_pct: float) -> str:
    """Зарождение -> ранний рост -> масштабирование, по форме кривой."""
    if maturity_pct >= 0.90:
        return "scaling"
    if comp["age"] <= 3:
        return "emerging"
    if comp["age"] <= 6:
        return "early_growth"
    return "scaling"


def уверенность(comp: dict, n_countries: int) -> str:
    """Честный флаг вместо ложной точности: когда данных мало, так и пишем.

    Подозрение на тёзку опускает потолок до medium даже при обилии данных:
    разделение жизней термина по форме ряда — эвристика, и мы не имеем права
    выдавать её результат за высокую уверенность.
    """
    if comp["counts_recent"] >= 200 and n_countries >= 15:
        высокая = not comp.get("homonym_suspected")
        return "high" if высокая else "medium"
    if comp["counts_recent"] >= 50 and n_countries >= 8:
        return "medium"
    return "low"
