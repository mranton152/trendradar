#!/usr/bin/env python3
"""
Spike: детектор зарождающихся трендов (weak signals) на данных OpenAlex.

Цель спайка - до получения ТЗ проверить, что предложенная методология
работает на реальных данных и даёт осмысленный ТОП-15 без ручного отбора.

Пайплайн:
  1. resolve_domain  - произвольный текст направления -> концепт OpenAlex
  2. harvest         - несмещённая выборка работ по годам (sample+seed)
  3. candidates      - добыча терминов-кандидатов (n-граммы из заголовков)
  4. series          - точный годовой ряд по каждому кандидату (group_by, 1 запрос)
  5. score           - Emergence Score из интерпретируемых компонент
  6. backtest        - режим "срез прошлого": считаем на данных до CUTOFF и
                       смотрим, что термины сделали ПОСЛЕ (проверка предсказательной силы)

Зависимостей нет: только стандартная библиотека.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

API = "https://api.openalex.org"
MAILTO = os.environ.get("OPENALEX_MAILTO", "flesha98@gmail.com")
UA = f"lct-trendradar/0.1 (mailto:{MAILTO})"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache")
CURRENT_YEAR = 2026
CURRENT_MONTH = 9  # для поправки на неполный текущий год


# --------------------------------------------------------------------------- http

def _cache_path(url: str) -> str:
    import hashlib
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{h}.json")


def get(path: str, params: dict, retries: int = 4) -> dict:
    params = dict(params)
    params["mailto"] = MAILTO
    url = f"{API}{path}?" + urllib.parse.urlencode(params, safe=':,|"')
    cp = _cache_path(url)
    if os.path.exists(cp):
        with open(cp) as f:
            return json.load(f)
    delay = 1.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cp, "w") as f:
                json.dump(data, f)
            return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            code = getattr(e, "code", None)
            if code == 404:
                return {}
            if attempt == retries - 1:
                sys.stderr.write(f"[warn] give up {url[:120]}: {e}\n")
                return {}
            time.sleep(delay)
            delay *= 2
    return {}


# ------------------------------------------------------------------- 1. домен

def resolve_domain(text: str) -> dict:
    """Свободный ввод пользователя -> концепт OpenAlex (фильтр по предметной области)."""
    d = get("/concepts", {"search": text, "per-page": 5})
    results = d.get("results") or []
    if not results:
        return {"filter": f'title_and_abstract.search:"{text}"', "name": text, "id": None}
    top = results[0]
    return {
        "filter": f"concepts.id:{top['id'].rsplit('/', 1)[-1]}",
        "name": top["display_name"],
        "id": top["id"],
        "works_count": top.get("works_count"),
        "alternatives": [r["display_name"] for r in results[1:4]],
    }


# ------------------------------------------------------------------ 2. выборка

def harvest(domain_filter: str, y_from: int, y_to: int, per_year: int) -> dict:
    """Несмещённая выборка заголовков по годам (sample+seed => воспроизводимо)."""
    out = {}
    for year in range(y_from, y_to + 1):
        titles, page, seen = [], 1, 0
        while seen < per_year:
            batch = min(200, per_year - seen)
            d = get("/works", {
                "filter": f"{domain_filter},publication_year:{year},type:article",
                "sample": per_year, "seed": "42",
                "per-page": batch, "page": page,
                "select": "id,title,publication_year,cited_by_count",
            })
            res = d.get("results") or []
            if not res:
                break
            titles.extend(r["title"] for r in res if r.get("title"))
            seen += len(res)
            page += 1
            if len(res) < batch:
                break
        out[year] = titles
        sys.stderr.write(f"[harvest] {year}: {len(titles)} works\n")
    return out


# --------------------------------------------------------------- 3. кандидаты

STOP = set("""a an the of for and or in on to with by from using based via as at is are was were be been
this that these those we our their its it his her they he she you your not no non can could may might
new novel study studies research analysis approach method methods model models system systems
paper article review survey towards toward use uses used case cases results result data
between during under over about into through than then them us all any each more most other others
such which who whom whose what when where why how have has had do does did but if than so
one two three first second third high low large small good better best big
application applications framework technique techniques design development evaluation performance
comparison comparative effect effects impact role state art review overview introduction chapter
""".split())

TOKEN_RE = re.compile(r"[a-z][a-z0-9\-\+]{1,}")


def ngrams(title: str, n_min: int = 2, n_max: int = 4):
    toks = TOKEN_RE.findall(title.lower())
    for n in range(n_min, n_max + 1):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in STOP or g[-1] in STOP:
                continue
            if sum(1 for t in g if t in STOP) > (n - 2):
                continue
            if all(len(t) <= 2 for t in g):
                continue
            yield " ".join(g)


def candidates(titles_by_year: dict, cutoff: int, recent_window: int, top_k: int,
               min_recent: int) -> list:
    """Кандидаты = n-граммы, частые в ПОСЛЕДНЕМ окне и редкие раньше."""
    recent, old = Counter(), Counter()
    for year, titles in titles_by_year.items():
        if year > cutoff:
            continue
        bucket = recent if year > cutoff - recent_window else old
        for t in titles:
            for g in set(ngrams(t)):
                bucket[g] += 1

    scored = []
    for g, c in recent.items():
        if c < min_recent:
            continue
        o = old.get(g, 0)
        # отношение свежей плотности к исторической (сглаженное)
        lift = (c + 1) / (o + 1)
        scored.append((g, c, o, lift))
    scored.sort(key=lambda x: (x[3] * math.log1p(x[1])), reverse=True)

    # снятие вложенных дублей: "large language" vs "large language model"
    kept, seen_long = [], []
    for g, c, o, lift in scored:
        if any(g != s and g in s for s in seen_long):
            continue
        kept.append({"term": g, "recent": c, "old": o, "lift": round(lift, 2)})
        seen_long.append(g)
        if len(kept) >= top_k:
            break
    return kept


# ------------------------------------------------------- 4. точные годовые ряды

def year_series(term: str, domain_filter: str) -> dict:
    """Точная гистограмма по годам одним запросом (не выборка - полный корпус)."""
    d = get("/works", {
        "filter": f'{domain_filter},title_and_abstract.search:"{term}",type:article',
        "group_by": "publication_year",
    })
    out = {}
    for g in d.get("group_by") or []:
        try:
            y = int(g["key"])
        except (ValueError, TypeError):
            continue
        if 1950 <= y <= CURRENT_YEAR:
            out[y] = g["count"]
    return out


def country_spread(term: str, domain_filter: str, y_from: int, y_to: int) -> int:
    """Сколько стран публикует по термину в окне - прокси распространения (diffusion)."""
    d = get("/works", {
        "filter": f'{domain_filter},title_and_abstract.search:"{term}",type:article,'
                  f"publication_year:{y_from}-{y_to}",
        "group_by": "authorships.institutions.country_code",
        "per-page": 200,
    })
    return len([g for g in (d.get("group_by") or []) if g.get("count", 0) >= 2])


def domain_totals(domain_filter: str) -> dict:
    d = get("/works", {"filter": domain_filter, "group_by": "publication_year"})
    out = {}
    for g in d.get("group_by") or []:
        try:
            y = int(g["key"])
        except (ValueError, TypeError):
            continue
        if 1950 <= y <= CURRENT_YEAR:
            out[y] = g["count"]
    return out


# ---------------------------------------------------------------- 5. скоринг

def peer_normalizer(all_counts: list, years: list) -> dict:
    """Знаменатель = суммарная активность пула кандидатов за год.

    Нормировка на полный корпус домена даёт ложное падение последнего года:
    OpenAlex индексирует метаданные быстрее, чем абстракты, поэтому
    search-по-тексту отстаёт от общего счётчика работ. Peer-нормировка
    использует тот же способ подсчёта в числителе и знаменателе,
    поэтому годовой перекос сокращается.
    """
    return {y: max(1.0, sum(float(c.get(y, 0)) for c in all_counts)) for y in years}


def _ols_slope(xs, ys) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def components(counts: dict, norm: dict, cutoff: int, window: int = 5,
               first_year_min: int = 5) -> dict:
    """Интерпретируемые компоненты. Каждая объяснима аналитику в UI."""
    years = list(range(cutoff - window + 1, cutoff + 1))

    # доля на миллион публикаций домена - убирает общий рост науки
    freq = [float(counts.get(y, 0)) / norm.get(y, 1.0) * 1e6 for y in years]

    logf = [math.log(f + 1.0) for f in freq]

    # N: новизна.
    # "Первый год упоминания" в чистом виде не работает: в большом корпусе почти
    # у любого термина найдутся единичные срабатывания 20-летней давности
    # (омонимы, ошибки метаданных, OCR). Поэтому считаем ДВЕ величины:
    #   first_mention - первый год, когда счётчик перестал быть единичным (для отчёта);
    #   takeoff_year  - год выхода на 10% собственного пика (для скоринга).
    hist = {y: c for y, c in counts.items() if y <= cutoff}
    peak = max(hist.values()) if hist else 0
    first_mention, takeoff = None, None
    for y in sorted(hist):
        if first_mention is None and hist[y] >= first_year_min:
            first_mention = y
        if takeoff is None and hist[y] >= max(first_year_min * 2, 0.10 * peak):
            takeoff = y
    first_year = takeoff or first_mention
    age = (cutoff - first_year) if first_year else 99

    # G: рост - наклон log-частоты
    growth = _ols_slope(years, logf)

    # A: ускорение - разница наклонов второй и первой половины окна
    half = max(2, window // 2)
    accel = _ols_slope(years[-half:], logf[-half:]) - _ols_slope(years[:half], logf[:half])

    # B: burst - во сколько раз последний год превысил ожидание по базовой линии
    base = sum(freq[:-1]) / max(1, len(freq) - 1)
    burst = (freq[-1] + 0.1) / (base + 0.1)

    # M: зрелость - высокая абсолютная частота = это уже мейнстрим, а не слабый сигнал
    maturity = freq[-1]

    total_recent = sum(counts.get(y, 0) for y in years)
    active_years = sum(1 for f in freq if f > 0)
    last_share = (freq[-1] / sum(freq)) if sum(freq) > 0 else 1.0

    return {
        "first_year": first_year, "first_mention": first_mention,
        "takeoff_year": takeoff, "age": age,
        "growth": growth, "accel": accel, "burst": burst,
        "maturity": maturity, "freq_last": freq[-1],
        "freq_series": [round(f, 1) for f in freq],
        "counts_recent": int(total_recent),
        "active_years": active_years, "last_year_share": round(last_share, 3),
        "years": years,
    }


def pct_rank(values: list) -> list:
    """Перцентильный ранг - устойчив к выбросам, компоненты становятся сопоставимы."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    n = max(1, len(values) - 1)
    for rank, i in enumerate(order):
        out[i] = rank / n
    return out


WEIGHTS = {"novelty": 0.20, "growth": 0.32, "accel": 0.23, "burst": 0.15, "diffusion": 0.10}

# Жёсткие отсечения: тренд не может быть "зарождающимся", если он старый,
# уже стал мейнстримом или под ним слишком мало данных.
MAX_AGE = 8           # лет с года взлёта (takeoff)
MIN_EVIDENCE = 20     # публикаций в окне
MAX_MATURITY_PCT = 0.90  # верхний дециль по частоте = уже мейнстрим
MIN_COUNTRIES = 5        # тренд, которым занимается одна лаборатория, - ещё не тренд
MIN_ACTIVE_YEARS = 3     # нужен устойчивый рост, а не всплеск одного года
MAX_LAST_YEAR_SHARE = 0.80  # >80% активности в одном году = разовый вброс данных


def emergence_scores(rows: list) -> list:
    """ES = взвешенная сумма перцентильных рангов x штраф за зрелость."""
    nov = pct_rank([-r["c"]["age"] for r in rows])
    gro = pct_rank([r["c"]["growth"] for r in rows])
    acc = pct_rank([r["c"]["accel"] for r in rows])
    bur = pct_rank([math.log(r["c"]["burst"] + 0.01) for r in rows])
    dif = pct_rank([r.get("countries", 0) for r in rows])
    mat = pct_rank([r["c"]["maturity"] for r in rows])

    for i, r in enumerate(rows):
        parts = {"novelty": nov[i], "growth": gro[i], "accel": acc[i],
                 "burst": bur[i], "diffusion": dif[i]}
        raw = sum(WEIGHTS[k] * v for k, v in parts.items())
        # уже мейнстрим -> не зарождающийся тренд: мягкий штраф
        penalty = 1.0 - 0.5 * mat[i]
        r["parts"] = {k: round(v, 3) for k, v in parts.items()}
        r["maturity_pct"] = round(mat[i], 3)
        r["es"] = round(raw * penalty, 4)
    rows.sort(key=lambda r: r["es"], reverse=True)
    return rows


# ---------------------------------------------------------------- 6. бэктест

def dedup_terms(rows: list, jaccard: float = 0.6) -> list:
    """Схлопывание вариантов одного термина: остаётся вариант с большим ES.

    Ловит и вложенность ("explainable machine" / "explainable machine learning"),
    и перестановки слов. Полноценная канонизация синонимов - на эмбеддингах,
    здесь достаточно лексической.
    """
    kept = []
    for r in rows:  # rows уже отсортированы по ES убыв.
        toks = set(r["term"].split())
        dup = False
        for k in kept:
            ktoks = set(k["term"].split())
            inter = len(toks & ktoks)
            if inter and (inter / len(toks | ktoks) >= jaccard
                          or toks <= ktoks or ktoks <= toks):
                k.setdefault("aliases", []).append(r["term"])
                dup = True
                break
        if not dup:
            kept.append(r)
    return kept


def backtest(rows: list, cutoff: int) -> list:
    """Что термин сделал ПОСЛЕ момента обнаружения - честная проверка."""
    for r in rows:
        counts = r["counts"]
        before = counts.get(cutoff, 0)
        after = max((counts.get(y, 0) for y in range(cutoff + 1, CURRENT_YEAR + 1)), default=0)
        r["backtest"] = {
            "at_cutoff": before,
            "peak_after": after,
            "growth_x": round((after + 1) / (before + 1), 1),
        }
    return rows


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="artificial intelligence")
    ap.add_argument("--cutoff", type=int, default=CURRENT_YEAR,
                    help="год среза; поставь прошлое для бэктеста, напр. 2021")
    ap.add_argument("--years-back", type=int, default=8)
    ap.add_argument("--per-year", type=int, default=600)
    ap.add_argument("--candidates", type=int, default=120)
    ap.add_argument("--min-recent", type=int, default=4)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    dom = resolve_domain(args.domain)
    sys.stderr.write(f"[domain] '{args.domain}' -> {dom['name']} ({dom['filter']}), "
                     f"works={dom.get('works_count')}\n")

    y_from = args.cutoff - args.years_back + 1
    titles = harvest(dom["filter"], y_from, args.cutoff, args.per_year)

    cands = candidates(titles, args.cutoff, recent_window=3,
                       top_k=args.candidates, min_recent=args.min_recent)
    dom_words = set(TOKEN_RE.findall((args.domain + " " + dom["name"]).lower()))
    cands = [c for c in cands
             if not set(c["term"].split()).issubset(dom_words)]
    sys.stderr.write(f"[candidates] {len(cands)} терминов-кандидатов\n")

    # фаза 1: точные ряды по всем кандидатам
    raw = []
    for i, c in enumerate(cands, 1):
        counts = year_series(c["term"], dom["filter"])
        if counts:
            raw.append({"term": c["term"], "counts": counts, "lift": c["lift"]})
        if i % 25 == 0:
            sys.stderr.write(f"[series] {i}/{len(cands)}\n")

    # фаза 2: peer-нормировка по пулу кандидатов
    window_years = list(range(args.cutoff - 6, args.cutoff + 1))
    norm = peer_normalizer([r["counts"] for r in raw], window_years)

    # фаза 3: компоненты + жёсткие отсечения
    rows, rejected = [], Counter()
    for r in raw:
        comp = components(r["counts"], norm, args.cutoff)
        if comp["counts_recent"] < MIN_EVIDENCE:
            rejected["мало данных"] += 1
            continue
        if comp["age"] > MAX_AGE:
            rejected["слишком старый термин"] += 1
            continue
        if comp["active_years"] < MIN_ACTIVE_YEARS:
            rejected["всплеск одного года"] += 1
            continue
        if comp["last_year_share"] > MAX_LAST_YEAR_SHARE:
            rejected["разовый вброс данных"] += 1
            continue
        spread = country_spread(r["term"], dom["filter"], args.cutoff - 2, args.cutoff)
        if spread < MIN_COUNTRIES:
            rejected["нет географического распространения"] += 1
            continue
        r["c"] = comp
        r["countries"] = spread
        rows.append(r)

    rows = emergence_scores(rows)
    rows = dedup_terms(rows)
    before_mat = len(rows)
    rows = [r for r in rows if r["maturity_pct"] < MAX_MATURITY_PCT]
    rejected["уже мейнстрим"] = before_mat - len(rows)
    sys.stderr.write(f"[filter] прошло {len(rows)} из {len(raw)}; "
                     f"отсеяно: {dict(rejected)}\n")
    if args.cutoff < CURRENT_YEAR:
        rows = backtest(rows, args.cutoff)

    print(f"\n{'='*100}")
    print(f"ТОП-{args.top} зарождающихся трендов | направление: {dom['name']} | срез: {args.cutoff}")
    print(f"{'='*100}")
    hdr = f"{'#':>2} {'ES':>6} {'термин':<42} {'взлёт':>6} {'публ':>6} {'стран':>5} {'частота/млн (по годам)':<28}"
    if args.cutoff < CURRENT_YEAR:
        hdr += f" {'после среза':>12}"
    print(hdr)
    print("-" * 100)
    for i, r in enumerate(rows[:args.top], 1):
        line = (f"{i:>2} {r['es']:>6.3f} {r['term'][:42]:<42} "
                f"{str(r['c']['first_year']):>6} {r['c']['counts_recent']:>6} "
                f"{r['countries']:>5} {str(r['c']['freq_series']):<28}")
        if "backtest" in r:
            b = r["backtest"]
            line += f" {b['at_cutoff']:>4}->{b['peak_after']:<5} x{b['growth_x']}"
        print(line)

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"domain": dom, "cutoff": args.cutoff,
                       "weights": WEIGHTS, "rows": rows[:60]}, f, ensure_ascii=False, indent=2)
        sys.stderr.write(f"[out] {args.out}\n")


if __name__ == "__main__":
    main()
