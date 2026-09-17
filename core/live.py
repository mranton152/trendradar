"""Живой скоринг: корпус, собранный за минуты по произвольному запросу.

Чем отличается от индексного режима (core/build.py):

- горизонт - два года новостей, а не двадцать лет публикаций. Годовые ряды
  дают две точки, считать по ним нельзя. Здесь ряды МЕСЯЧНЫЕ;
- у новостей нет стран, поэтому распространение меряется числом разных
  доменов-источников: тема, о которой пишет один сайт, - не тренд;
- у новостей есть доверенность. Кандидат, у которого все источники - пресс-релизы
  и блоги, по ТЗ не может попасть в выдачу на этом основании;
- эмбеддингов и кластеров нет: на ноутбуке жюри нет GPU, а бюджет - секунды.

Вход тот же, что у индексного режима: works / candidates / cand_docs по контракту.
Выход - те же TRENDS и REJECTED, с series_granularity = "month".
"""
import datetime as dt
import math
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import duckdb

from core.components import pct_rank
from core.dedup import dedup
from core.lead import sql_вес
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА, стадия
from core.series import top_docs

ОКНО_МЕС = 24

ПОРОГИ_LIVE = {
    "MAX_AGE_MONTHS": 24,        # старше двух лет в новостях - уже не зарождается
    "MIN_EVIDENCE": 8,           # документов в окне; новостей меньше, чем статей
    "MIN_DOMAINS": 3,            # разных источников: один сайт - не тренд
    "MIN_ACTIVE_MONTHS": 3,      # не всплеск одного месяца
    "MAX_LAST_SHARE": 0.80,      # почти всё в последний месяц - вброс
    "MIN_DOMAINS_ДЛЯ_ВСПЛЕСКА": 5,
    "MIN_TRUSTED_SHARE": 0.34,   # ТЗ: индикаторные источники - не единственное основание
    "PLATEAU_AGE_MONTHS": 18,    # плато = давно пишут...
    "PLATEAU_MAX_GROWTH": 0.03,  # ...и не растёт
}

ОПИСАНИЯ_ПОРОГОВ_LIVE = {
    "MAX_AGE_MONTHS": "Возраст: не старше 24 месяцев с месяца взлёта.",
    "MIN_EVIDENCE": "Объём: минимум 8 документов в окне.",
    "MIN_DOMAINS": "География источников: минимум 3 разных сайта. Один сайт — не тренд.",
    "MIN_ACTIVE_MONTHS": "Устойчивость: активность минимум в 3 месяцах.",
    "MAX_LAST_SHARE": "Доля последнего месяца: не выше 80%. Признак вброса.",
    "MIN_DOMAINS_ДЛЯ_ВСПЛЕСКА": "…но при 5+ сайтах это настоящий взрыв, а не вброс.",
    "MIN_TRUSTED_SHARE": "Доверенность: минимум треть источников — доверенные. "
                         "Пресс-релизы и блоги — только индикатор (требование ТЗ).",
    "PLATEAU_AGE_MONTHS": "Плато: тема старше 18 месяцев…",
    "PLATEAU_MAX_GROWTH": "…и без роста — это устоявшаяся, а не зарождающаяся.",
}


# --------------------------------------------------------------- ряды

def _подключение() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def month_counts(index_dir: str | Path, corpus_path: str | Path) -> dict[str, dict[str, int]]:
    """{cand_id: {'YYYY-MM': взвешенное число документов}}. Документы без даты - по году."""
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute(f"""
        SELECT cd.cand_id,
               coalesce(substr(w.date, 1, 7), cast(w.year AS VARCHAR) || '-06') AS m,
               sum({sql_вес()}) AS n
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
        GROUP BY 1, 2
    """, [links, str(corpus_path)]).fetchall()
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for cand_id, m, n in строки:
        out[cand_id][m] = int(round(float(n)))
    return dict(out)


def domain_spread(index_dir: str | Path, corpus_path: str | Path) -> dict[str, int]:
    """Сколько разных сайтов пишет о кандидате."""
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute("""
        SELECT cd.cand_id, w.url FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
    """, [links, str(corpus_path)]).fetchall()
    домены: dict[str, set] = defaultdict(set)
    for cand_id, url in строки:
        домены[cand_id].add(urlparse(url).netloc.removeprefix("www."))
    return {c: len(d) for c, d in домены.items()}


def trusted_share(index_dir: str | Path, corpus_path: str | Path) -> dict[str, float]:
    """Доля доверенных источников у кандидата. Неизвестный уровень считается за 0.5."""
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute("""
        SELECT cd.cand_id,
               avg(CASE w.trust_level
                     WHEN 'trusted' THEN 1.0 WHEN 'indicator' THEN 0.0 ELSE 0.5 END)
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
        GROUP BY 1
    """, [links, str(corpus_path)]).fetchall()
    return {c: float(v) for c, v in строки}


# ---------------------------------------------------------- компоненты

def _месяцы(as_of: str, window: int) -> list[str]:
    y, m = int(as_of[:4]), int(as_of[5:7])
    out = []
    for k in range(window - 1, -1, -1):
        mm = m - k
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _сгладить(xs: list[float], окно: int = 3) -> list[float]:
    """Скользящая сумма: месячные ряды у маленьких тем дырявые (0, 0, 9, 0, 14),
    и наклон логарифма по ним - шум. Три месяца - минимальное окно, которое
    убирает дыры, не съедая перелом."""
    return [sum(xs[max(0, i - окно + 1):i + 1]) for i in range(len(xs))]


def это_плато(comp: dict) -> bool:
    """Мейнстрим по-новостному: пишут давно и ровно. Не «самый частый в пуле» -
    в живом пуле из пяти тем самый частый как раз и есть зарождающийся."""
    return (comp["age_months"] >= ПОРОГИ_LIVE["PLATEAU_AGE_MONTHS"]
            and comp["growth"] <= ПОРОГИ_LIVE["PLATEAU_MAX_GROWTH"])


def _slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = (n - 1) / 2, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den if den else 0.0


def components_monthly(counts: dict[str, int], norm: dict[str, float],
                       as_of: str, window: int = ОКНО_МЕС) -> dict:
    """Те же пять компонент, что и в индексном режиме, но на месяцах."""
    месяцы = _месяцы(as_of, window)
    freq = [counts.get(m, 0) / norm.get(m, 1.0) * 1e6 for m in месяцы]
    logf = [math.log(f + 1.0) for f in _сгладить(freq)]

    история = {m: c for m, c in counts.items() if m <= as_of}
    пик = max(история.values()) if история else 0
    takeoff = next((m for m in sorted(история) if история[m] >= max(3, 0.10 * пик)), None)
    first = next((m for m in sorted(история) if история[m] >= 2), None)
    опорный = takeoff or first
    age_months = (месяцы.index(опорный) if опорный in месяцы
                  else (0 if опорный and опорный > месяцы[-1] else 99))
    age_months = (window - 1 - age_months) if age_months != 99 else 99

    половина = max(2, window // 2)
    growth = _slope(logf)
    accel = _slope(logf[-половина:]) - _slope(logf[:половина])
    база = sum(freq[:-3]) / max(1, len(freq) - 3)
    burst = (sum(freq[-3:]) / 3 + 0.1) / (база + 0.1)
    сумма = sum(freq)
    return {
        "first_mention": int(first[:4]) if first else None,
        "takeoff_year": int(takeoff[:4]) if takeoff else None,
        "takeoff_month": takeoff,
        "age": age_months, "age_months": age_months,
        "growth": growth, "accel": accel, "burst": burst,
        "maturity": sum(freq[-3:]) / 3,
        "freq_series": [round(f, 2) for f in freq],
        "counts_series": [int(counts.get(m, 0)) for m in месяцы],
        "months": месяцы,
        "years": [int(m[:4]) * 100 + int(m[5:7]) for m in месяцы],
        "counts_recent": int(sum(counts.get(m, 0) for m in месяцы)),
        "active_months": sum(1 for f in freq if f > 0),
        "last_share": round(freq[-1] / сумма, 3) if сумма > 0 else 1.0,
        "homonym_suspected": False,
    }


def причина_отказа_live(comp: dict, n_domains: int, trusted_share: float) -> str | None:
    if comp["counts_recent"] < ПОРОГИ_LIVE["MIN_EVIDENCE"]:
        return "мало данных"
    if comp["age_months"] > ПОРОГИ_LIVE["MAX_AGE_MONTHS"]:
        return "слишком старый термин"
    if comp["active_months"] < ПОРОГИ_LIVE["MIN_ACTIVE_MONTHS"]:
        return "всплеск одного месяца"
    if (comp["last_share"] > ПОРОГИ_LIVE["MAX_LAST_SHARE"]
            and n_domains < ПОРОГИ_LIVE["MIN_DOMAINS_ДЛЯ_ВСПЛЕСКА"]):
        return "разовый вброс данных"
    if n_domains < ПОРОГИ_LIVE["MIN_DOMAINS"]:
        return "пишет один-два сайта"
    if trusted_share < ПОРОГИ_LIVE["MIN_TRUSTED_SHARE"]:
        return "только индикаторные источники (пресс-релизы, блоги)"
    return None


# ---------------------------------------------------------------- сборка

def построить_live(index_dir: str | Path, corpus_path: str | Path, domain: str,
                   as_of: str | None = None, top: int = 15) -> tuple[list[dict], list[dict]]:
    """Тренды и отсеянные по живому корпусу. as_of - 'YYYY-MM', по умолчанию текущий."""
    index_dir, corpus_path = Path(index_dir), Path(corpus_path)
    as_of = as_of or dt.date.today().strftime("%Y-%m")
    ряды = month_counts(index_dir, corpus_path)
    домены = domain_spread(index_dir, corpus_path)
    доверие = trusted_share(index_dir, corpus_path)
    подписи = {r[0]: r[1] for r in duckdb.connect().execute(
        "SELECT cand_id, label FROM read_parquet(?)",
        [str(index_dir / "candidates.parquet")]).fetchall()}

    месяцы = _месяцы(as_of, ОКНО_МЕС)
    norm = {m: max(1.0, float(sum(c.get(m, 0) for c in ряды.values()))) for m in месяцы}
    as_of_year = int(as_of[:4])

    строки, отсеянные = [], []
    for cand_id, counts in ряды.items():
        if cand_id not in подписи:
            continue
        comp = components_monthly(counts, norm, as_of)
        причина = причина_отказа_live(comp, домены.get(cand_id, 0), доверие.get(cand_id, 0.5))
        if not причина and это_плато(comp):
            причина = "плато: пишут давно и без роста"
        if причина:
            отсеянные.append({"cand_id": cand_id, "label": подписи[cand_id], "domain": domain,
                              "reason": причина, "n_docs": comp["counts_recent"],
                              "as_of": as_of_year})
            continue
        строки.append({"cand_id": cand_id, "label": подписи[cand_id], "c": comp,
                       "countries": домены.get(cand_id, 0), "emb_row": None})

    if строки:
        nov = pct_rank([-r["c"]["age_months"] for r in строки])
        gro = pct_rank([r["c"]["growth"] for r in строки])
        acc = pct_rank([r["c"]["accel"] for r in строки])
        bur = pct_rank([math.log(r["c"]["burst"] + 0.01) for r in строки])
        dif = pct_rank([float(r["countries"]) for r in строки])
        # Перцентильной зрелости в живом режиме нет намеренно: в пуле из пяти тем
        # самый частый - не мейнстрим, а зарождающийся. Мейнстрим отсеян выше
        # как плато - давно и без роста. maturity_pct оставлен в выдаче как 0.
        for i, r in enumerate(строки):
            части = {"novelty": nov[i], "growth": gro[i], "accel": acc[i],
                     "burst": bur[i], "diffusion": dif[i]}
            r["parts"] = {k: round(v, 3) for k, v in части.items()}
            r["maturity_pct"] = 0.0
            r["es"] = round(sum(ВЕСА[k] * v for k, v in части.items()), 4)
        строки.sort(key=lambda r: r["es"], reverse=True)
        строки = dedup(строки)[:top]

    итог = []
    for ранг, r in enumerate(строки, 1):
        c = r["c"]
        n_dom = r["countries"]
        уверенность = ("high" if c["counts_recent"] >= 40 and n_dom >= 8
                       else "medium" if c["counts_recent"] >= 15 and n_dom >= 4 else "low")
        итог.append({
            "trend_id": f"t:{domain}:{as_of_year}:{ранг:02d}",
            "domain": domain, "as_of": as_of_year, "rank": ранг,
            "cand_id": r["cand_id"], "label": r["label"], "aliases": r.get("aliases", []),
            "emergence_score": float(r["es"]),
            **{f"c_{k}": float(v) for k, v in r["parts"].items()},
            "maturity_pct": float(r["maturity_pct"]),
            "first_mention": c["first_mention"], "takeoff_year": c["takeoff_year"],
            "years": c["years"], "counts": c["counts_series"],
            "freq_per_million": [float(f) for f in c["freq_series"]],
            "n_docs": c["counts_recent"], "n_countries": n_dom,
            "n_orgs": None, "n_patents": None,
            "top_doc_ids": top_docs(index_dir, corpus_path, r["cand_id"]),
            "stage": стадия({"age": c["age_months"] // 12}, r["maturity_pct"]),
            "confidence": уверенность,
            "methodology_version": ВЕРСИЯ_МЕТОДОЛОГИИ,
            "series_granularity": "month",
            "bt_at_cutoff": None, "bt_peak_after": None, "bt_growth_x": None,
        })
    return итог, отсеянные
