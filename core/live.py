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
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import httpx

from core.components import pct_rank
from core.dedup import dedup
from core.lead import sql_вес
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА, стадия
from core.series import top_docs

ОКНО_МЕС = 24

ПОРОГИ_LIVE = {
    "MAX_AGE_MONTHS": 24,        # старше двух лет в новостях - уже не зарождается
    # Жёсткие пороги отсеивают, мягкие понижают уверенность до low. Замер 27.09
    # на шести живых запросах: Google News отдаёт только свежие статьи, история
    # кандидата в новостях - один-два месяца, у молодых компаний 2-6 упоминаний.
    # Для слабого сигнала это не брак, а определение; прячем только то, что
    # доказанно не сигнал (зрелое, тема запроса, одно издание, одни пресс-релизы).
    "MIN_EVIDENCE": 2,           # жёсткий: единичное упоминание - не сигнал
    "MIN_DOMAINS": 2,            # жёсткий: пишет одно издание - не тренд
    "SOFT_EVIDENCE": 4,          # мягкий: меньше - уверенность low
    "MIN_ACTIVE_MONTHS": 3,      # мягкий: короче история - уверенность low
    "MIN_TRUSTED_SHARE": 0.34,   # ТЗ: индикаторные источники - не единственное основание
    "PLATEAU_AGE_MONTHS": 18,    # плато = давно пишут...
    "PLATEAU_MAX_GROWTH": 0.03,  # ...и не растёт
    "MAX_SCIENCE_10Y": 10_000,   # научных работ в OpenAlex за 10 лет (точная фраза):
                                 # больше - массово изучено. Замер 27.09: выше -
                                 # machine learning 1,37 млн, federated learning 64 тыс.,
                                 # AI agent 26 тыс., digital payments 15 тыс.; ниже -
                                 # physical ai 1 190, instant payments 624, Q-CTRL 22
}

ОПИСАНИЯ_ПОРОГОВ_LIVE = {
    "MAX_AGE_MONTHS": "Возраст: не старше 24 месяцев с месяца взлёта.",
    "MIN_EVIDENCE": "Объём: минимум 2 документа. Единичное упоминание — не сигнал.",
    "MIN_DOMAINS": "Распространение: минимум 2 разных издания. Одно издание — не тренд.",
    "SOFT_EVIDENCE": "Меньше 4 документов — сигнал показывается с низкой уверенностью.",
    "MIN_ACTIVE_MONTHS": "История короче 3 месяцев — сигнал показывается с низкой "
                         "уверенностью: слабый сигнал по определению свежий.",
    "MIN_TRUSTED_SHARE": "Доверенность: минимум треть источников — доверенные. "
                         "Пресс-релизы и блоги — только индикатор (требование ТЗ).",
    "PLATEAU_AGE_MONTHS": "Плато: тема старше 18 месяцев…",
    "PLATEAU_MAX_GROWTH": "…и без роста — это устоявшаяся, а не зарождающаяся.",
    "MAX_SCIENCE_10Y": "Зрелость: не больше 10 000 научных работ за 10 лет. "
                       "Больше — массово изученная область или крупная компания.",
}

# Агрегатор — транспорт, а не источник. Ссылка Google News ведёт на
# news.google.com, а настоящее издание стоит в конце заголовка: «… - Phys.org».
# Без этого все новости кандидата считались одним сайтом с уровнем «индикатор»,
# и живой режим отсекал всё: замер 27.09 — 0 трендов на шести запросах при
# 171-325 разных изданиях в каждом корпусе.
АГРЕГАТОРЫ = {"gnews"}

# Слова новостной хроники на краю подписи: правила извлечения захватывают их
# вместе с именем компании — «Holiday Robotics Raises», «First Pure-Play
# Humanoid Robotics» (замер 27.09, запрос «роботы-гуманоиды»). На 166
# кандидатах семи живых запросов правило отсекает ровно эти два и ни одного
# настоящего названия.
КРАЯ_ЗАГОЛОВКА = {
    "raises", "raised", "raise", "raising", "launches", "launched", "launch", "unveils",
    "unveiled", "announces", "announced", "secures", "secured", "lands", "closes",
    "debuts", "acquires", "acquired", "partners", "expands", "first", "new", "top",
    "best", "pure-play", "largest", "leading", "biggest", "latest", "how", "why", "what",
    "inside", "meet", "says", "said", "gets", "wins", "hits", "nears", "eyes"}


def обрывок_заголовка(label: str) -> bool:
    слова = label.lower().split()
    return len(слова) > 1 and (слова[0] in КРАЯ_ЗАГОЛОВКА or слова[-1] in КРАЯ_ЗАГОЛОВКА)


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


def издание(source: str, title: str, url: str) -> str:
    """Кто опубликовал документ. Для агрегатора — издание из хвоста заголовка."""
    if source in АГРЕГАТОРЫ and " - " in (title or ""):
        return title.rsplit(" - ", 1)[1].strip().lower()
    return urlparse(url).netloc.removeprefix("www.")


def domain_spread(index_dir: str | Path, corpus_path: str | Path) -> dict[str, int]:
    """Сколько разных изданий пишет о кандидате."""
    links = str(Path(index_dir) / "cand_docs.parquet")
    строки = _подключение().execute("""
        SELECT cd.cand_id, w.source, w.title, w.url
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
    """, [links, str(corpus_path)]).fetchall()
    домены: dict[str, set] = defaultdict(set)
    for cand_id, source, title, url in строки:
        домены[cand_id].add(издание(source, title, url))
    return {c: len(d) for c, d in домены.items()}


def trusted_share(index_dir: str | Path, corpus_path: str | Path) -> dict[str, float]:
    """Доля доверенных источников у кандидата. Неизвестный уровень считается за 0.5.

    Документ агрегатора считается неизвестным, а не индикатором: доверенность
    определяется изданием, а агрегатор его только пересылает.
    """
    links = str(Path(index_dir) / "cand_docs.parquet")
    агрегаторы = ", ".join(f"'{a}'" for a in sorted(АГРЕГАТОРЫ))  # константа модуля
    строки = _подключение().execute(f"""
        SELECT cd.cand_id,
               avg(CASE WHEN w.source IN ({агрегаторы}) THEN 0.5
                        WHEN w.trust_level = 'trusted' THEN 1.0
                        WHEN w.trust_level = 'indicator' THEN 0.0 ELSE 0.5 END)
        FROM read_parquet(?) cd JOIN read_parquet(?) w USING (doc_id)
        GROUP BY 1
    """, [links, str(corpus_path)]).fetchall()
    return {c: float(v) for c, v in строки}


# ------------------------------------------------ тема запроса и зрелость

def фразы_запроса(index_dir: str | Path) -> list[str]:
    """Запрос пользователя и его перевод — из meta.json семантической стадии."""
    try:
        meta = json.loads((Path(index_dir) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    live = meta.get("live_ingest") or {}
    if isinstance(live, str):   # старые meta хранили вложенный словарь строкой
        return [meta.get("domain_query") or ""]
    фразы = [meta.get("domain_query") or live.get("domain_query") or ""]
    ответ = (live.get("translation") or {}).get("response") or {}
    фразы += [f for f in ответ.get("phrases", []) if isinstance(f, str)]
    return [f for f in фразы if f]


def _основы(текст: str) -> set[str]:
    return {w[:4] for w in текст.lower().replace("-", " ").split() if len(w) >= 3}


def это_тема_запроса(label: str, фразы: list[str]) -> bool:
    """«quantum sensor» при запросе «квантовые сенсоры» — это сама тема, а не
    сигнал внутри неё. Все слова подписи должны встретиться во фразе запроса."""
    основы = _основы(label)
    return bool(основы) and any(основы <= _основы(ф) for ф in фразы)


def научная_база(labels: list[str], кэш: Path | None = None,
                 год: int | None = None, timeout: float = 8.0) -> dict[str, int | None]:
    """Научных работ в OpenAlex за 10 лет по каждой подписи.

    Один запрос на кандидата, параллельно: на 82 кандидатах — 3,4 с. Результат
    кэшируется рядом с индексом, повторный прогон воспроизводим без сети.
    Отказ источника — None, а не ноль: ноль означал бы «новое», и кандидат
    прошёл бы фильтр зрелости по ошибке сети.
    """
    год = год or dt.date.today().year
    готово: dict[str, int | None] = {}
    if кэш and кэш.exists():
        try:
            готово = json.loads(кэш.read_text(encoding="utf-8"))
        except ValueError:
            готово = {}
    нужно = [x for x in dict.fromkeys(labels) if готово.get(x) is None]
    ключ = os.getenv("OPENALEX_API_KEY")

    def один(label: str) -> tuple[str, int | None]:
        # Точная фраза, а не «все слова где угодно». По словам «video ai» — 34 705
        # работ, фразой — 208; «physical ai» 59 815 против 1 190. Поиск по словам
        # записывал молодые многословные технологии в массово изученные (замер 27.09).
        фраза = '"' + label.replace('"', " ").replace(",", " ") + '"'
        params = {"filter": f"title_and_abstract.search:{фраза},"
                            f"publication_year:{год - 9}-{год}",
                  "per-page": 1, "mailto": "trendradar@example.org"}
        if ключ:
            params["api_key"] = ключ
        try:
            r = httpx.get("https://api.openalex.org/works", params=params, timeout=timeout)
            r.raise_for_status()
            return label, int(r.json()["meta"]["count"])
        except (httpx.HTTPError, KeyError, ValueError):
            return label, None

    if нужно:
        with cf.ThreadPoolExecutor(8) as ex:
            готово.update(ex.map(один, нужно))
        if кэш:
            кэш.write_text(json.dumps(готово, ensure_ascii=False, indent=1), encoding="utf-8")
    return {x: готово.get(x) for x in labels}


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


def причина_отказа_live(comp: dict, n_domains: int, trusted_share: float,
                        наука_10л: int | None = None, тема: bool = False) -> str | None:
    if тема:
        return "это сама тема запроса, а не сигнал внутри неё"
    if comp.get("label") and обрывок_заголовка(comp["label"]):
        return "обрывок новостного заголовка, а не название"
    if наука_10л is not None and наука_10л > ПОРОГИ_LIVE["MAX_SCIENCE_10Y"]:
        return f"массово изучено: {наука_10л:,} научных работ за 10 лет".replace(",", " ")
    if comp["counts_recent"] < ПОРОГИ_LIVE["MIN_EVIDENCE"]:
        return "единичное упоминание"
    if comp["age_months"] > ПОРОГИ_LIVE["MAX_AGE_MONTHS"]:
        return "слишком старый термин"
    if n_domains < ПОРОГИ_LIVE["MIN_DOMAINS"]:
        return "пишут одно-два издания"
    if trusted_share < ПОРОГИ_LIVE["MIN_TRUSTED_SHARE"]:
        return "только индикаторные источники (пресс-релизы, блоги)"
    return None


# ---------------------------------------------------------------- сборка

def построить_live(index_dir: str | Path, corpus_path: str | Path, domain: str,
                   as_of: str | None = None, top: int = 15,
                   зрелость: bool = True) -> tuple[list[dict], list[dict]]:
    """Тренды и отсеянные по живому корпусу. as_of - 'YYYY-MM', по умолчанию текущий.

    зрелость=False отключает запросы к OpenAlex (тесты, работа без сети): тогда
    массово изученное отсеивается только плато, и это видно в отсеянных.
    """
    index_dir, corpus_path = Path(index_dir), Path(corpus_path)
    as_of = as_of or dt.date.today().strftime("%Y-%m")
    ряды = month_counts(index_dir, corpus_path)
    домены = domain_spread(index_dir, corpus_path)
    доверие = trusted_share(index_dir, corpus_path)
    подписи = {r[0]: r[1] for r in duckdb.connect().execute(
        "SELECT cand_id, label FROM read_parquet(?)",
        [str(index_dir / "candidates.parquet")]).fetchall()}

    фразы = фразы_запроса(index_dir)
    наука = (научная_база(list(подписи.values()), кэш=index_dir / "science_10y_phrase.json",
                          год=int(as_of[:4]))
             if зрелость else {})

    месяцы = _месяцы(as_of, ОКНО_МЕС)
    norm = {m: max(1.0, float(sum(c.get(m, 0) for c in ряды.values()))) for m in месяцы}
    as_of_year = int(as_of[:4])

    строки, отсеянные = [], []
    for cand_id, counts in ряды.items():
        if cand_id not in подписи:
            continue
        comp = components_monthly(counts, norm, as_of)
        метка = подписи[cand_id]
        comp["label"] = метка
        причина = причина_отказа_live(comp, домены.get(cand_id, 0), доверие.get(cand_id, 0.5),
                                      наука.get(метка), это_тема_запроса(метка, фразы))
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
        тонкий = (c["counts_recent"] < ПОРОГИ_LIVE["SOFT_EVIDENCE"]
                  or c["active_months"] < ПОРОГИ_LIVE["MIN_ACTIVE_MONTHS"])
        уверенность = ("low" if тонкий
                       else "high" if c["counts_recent"] >= 15 and n_dom >= 8
                       else "medium" if c["counts_recent"] >= 6 and n_dom >= 4 else "low")
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
