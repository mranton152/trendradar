# Фаза 0 — Антон: ядро методологии и валидация

> Общие правила и Global Constraints — в [README.md](README.md). Личный бриф — [../../team/PROMPT-anton.md](../../team/PROMPT-anton.md).

**Цель:** превратить прототип из `spikes/openalex_probe.py` в модуль `core/`,
который читает кандидатов от Константина и выдаёт `trends.parquet` — ранжированный
ТОП с доказательной базой, воспроизводимый и покрытый тестами.

**Архитектура:** чистые функции над numpy-массивами плюс тонкий слой DuckDB для
годовых рядов. Ни одного сетевого запроса: вход — parquet, выход — parquet.
Режим `as_of` пронизывает весь конвейер, поэтому бэктест — не отдельный скрипт,
а параметр продукта.

**Стек:** duckdb, pyarrow, numpy.

---

## Task A-01: Годовые ряды кандидатов

**Файлы:**
- Создать: `core/series.py`
- Тест: `core/test_series.py`

**Интерфейсы:**
- Отдаёт: `year_counts(index_dir, corpus_path) -> dict[str, dict[int, int]]` — `{cand_id: {год: число_документов}}`
- Отдаёт: `country_spread(index_dir, corpus_path, y_from, y_to) -> dict[str, int]`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_series.py
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, WORKS
from core.series import country_spread, year_counts


def _корпус(tmp_path):
    works = [
        {"doc_id": "d1", "source": "openalex", "doc_type": "article", "title": "a",
         "abstract": None, "year": 2020, "date": None, "lang": "en", "doi": None,
         "url": "u", "cited_by": 0, "countries": ["RU", "US"], "institutions": [],
         "authors": [], "concepts": [], "domain": "d", "harvested_at": "2026-09-09"},
        {"doc_id": "d2", "source": "openalex", "doc_type": "article", "title": "b",
         "abstract": None, "year": 2021, "date": None, "lang": "en", "doi": None,
         "url": "u", "cited_by": 0, "countries": ["US"], "institutions": [],
         "authors": [], "concepts": [], "domain": "d", "harvested_at": "2026-09-09"},
        {"doc_id": "d3", "source": "openalex", "doc_type": "article", "title": "c",
         "abstract": None, "year": 2021, "date": None, "lang": "en", "doi": None,
         "url": "u", "cited_by": 0, "countries": ["CN"], "institutions": [],
         "authors": [], "concepts": [], "domain": "d", "harvested_at": "2026-09-09"},
    ]
    links = [{"cand_id": "c1", "doc_id": "d1", "weight": 1.0},
             {"cand_id": "c1", "doc_id": "d2", "weight": 1.0},
             {"cand_id": "c2", "doc_id": "d3", "weight": 1.0}]
    pq.write_table(pa.Table.from_pylist(works, schema=WORKS), tmp_path / "works.parquet")
    pq.write_table(pa.Table.from_pylist(links, schema=CAND_DOCS),
                   tmp_path / "cand_docs.parquet")
    return tmp_path / "works.parquet"


def test_годовые_ряды_считаются_по_связям(tmp_path):
    корпус = _корпус(tmp_path)
    ряды = year_counts(tmp_path, корпус)
    assert ряды["c1"] == {2020: 1, 2021: 1}
    assert ряды["c2"] == {2021: 1}


def test_страны_считаются_уникально_в_окне(tmp_path):
    корпус = _корпус(tmp_path)
    страны = country_spread(tmp_path, корпус, 2020, 2021)
    assert страны["c1"] == 2      # RU, US — US не задваивается
    assert страны["c2"] == 1
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_series.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.series'`

- [ ] **Шаг 3: реализация**

```python
# core/series.py
"""Годовая динамика кандидатов.

Считается SQL-джойном по parquet: DuckDB делает это на порядок быстрее, чем
питон в цикле, и не требует поднимать сервер БД.
"""
from collections import defaultdict
from pathlib import Path

import duckdb


def year_counts(index_dir: str | Path, corpus_path: str | Path) -> dict[str, dict[int, int]]:
    """{cand_id: {год: сколько документов}}"""
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT cd.cand_id, w.year, count(*) AS n
        FROM '{links}' cd JOIN '{corpus_path}' w USING (doc_id)
        GROUP BY 1, 2
    """).fetchall()
    out: dict[str, dict[int, int]] = defaultdict(dict)
    for cand_id, year, n in строки:
        out[cand_id][int(year)] = int(n)
    return dict(out)


def country_spread(index_dir: str | Path, corpus_path: str | Path,
                   y_from: int, y_to: int) -> dict[str, int]:
    """Сколько разных стран публикует по кандидату в окне.

    Прокси распространения: тема, которой занимается одна лаборатория,
    ещё не тренд, каким бы быстрым ни был её рост.
    """
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT cd.cand_id, count(DISTINCT c) AS n
        FROM '{links}' cd
        JOIN '{corpus_path}' w USING (doc_id),
             unnest(w.countries) AS t(c)
        WHERE w.year BETWEEN {y_from} AND {y_to}
        GROUP BY 1
    """).fetchall()
    return {cand_id: int(n) for cand_id, n in строки}


def top_docs(index_dir: str | Path, corpus_path: str | Path,
             cand_id: str, limit: int = 20) -> list[str]:
    """Документы кандидата для RAG и ссылок: свежие и цитируемые вперёд."""
    links = Path(index_dir) / "cand_docs.parquet"
    строки = duckdb.sql(f"""
        SELECT w.doc_id
        FROM '{links}' cd JOIN '{corpus_path}' w USING (doc_id)
        WHERE cd.cand_id = '{cand_id}'
        ORDER BY w.year DESC, w.cited_by DESC NULLS LAST
        LIMIT {limit}
    """).fetchall()
    return [r[0] for r in строки]
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_series.py -v`
Ожидаемо: 2 passed

- [ ] **Шаг 5: коммит**

```bash
git add core/series.py core/test_series.py
git commit -m "Годовые ряды и география кандидатов через DuckDB"
```

---

## Task A-02: Peer-нормировка

Абсолютные счётчики нельзя сравнивать между годами — наука растёт сама по себе.
Но нормировка на весь корпус даёт систематическую ошибку: OpenAlex индексирует
метаданные быстрее абстрактов, и последний год ложно проседает **у всех терминов
сразу**. На это уже наступили в спайке. Лечение: знаменатель считается тем же
способом, что и числитель.

**Файлы:**
- Создать: `core/normalize.py`
- Тест: `core/test_normalize.py`

**Интерфейсы:**
- Отдаёт: `peer_normalizer(all_counts: list[dict[int, int]], years: list[int]) -> dict[int, float]`
- Отдаёт: `frequencies(counts: dict[int, int], norm: dict[int, float], years: list[int]) -> list[float]`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_normalize.py
from core.normalize import frequencies, peer_normalizer


def test_знаменатель_это_сумма_активности_пула():
    все = [{2020: 10, 2021: 20}, {2020: 30, 2021: 0}]
    assert peer_normalizer(все, [2020, 2021]) == {2020: 40.0, 2021: 20.0}


def test_пустой_год_не_делит_на_ноль():
    assert peer_normalizer([{2020: 0}], [2020, 2021]) == {2020: 1.0, 2021: 1.0}


def test_частота_на_миллион():
    norm = {2020: 100.0, 2021: 200.0}
    assert frequencies({2020: 1, 2021: 1}, norm, [2020, 2021]) == [10000.0, 5000.0]
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_normalize.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.normalize'`

- [ ] **Шаг 3: реализация**

```python
# core/normalize.py
"""Peer-нормировка частот.

Нормировка на полный корпус домена даёт ложное падение последнего года:
метаданные индексируются быстрее абстрактов, поэтому поиск по тексту отстаёт
от общего счётчика работ. Peer-нормировка использует один и тот же способ
подсчёта в числителе и в знаменателе, и годовой перекос сокращается.
"""


def peer_normalizer(all_counts: list[dict[int, int]], years: list[int]) -> dict[int, float]:
    """Знаменатель = суммарная активность пула кандидатов за год."""
    return {y: max(1.0, float(sum(c.get(y, 0) for c in all_counts))) for y in years}


def frequencies(counts: dict[int, int], norm: dict[int, float],
                years: list[int]) -> list[float]:
    """Доля кандидата в активности пула, на миллион. Убирает общий рост науки."""
    return [float(counts.get(y, 0)) / norm.get(y, 1.0) * 1e6 for y in years]
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_normalize.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 5: коммит**

```bash
git add core/normalize.py core/test_normalize.py
git commit -m "Peer-нормировка: лечение артефакта лага индексации абстрактов"
```

---

## Task A-03: Компоненты Emergence Score

**Файлы:**
- Создать: `core/components.py`
- Тест: `core/test_components.py`

**Интерфейсы:**
- Отдаёт: `components(counts: dict[int, int], norm: dict[int, float], as_of: int, window: int = 5) -> dict`
  с ключами `first_mention, takeoff_year, age, growth, accel, burst, maturity, freq_series, counts_recent, active_years, last_year_share, years`
- Отдаёт: `pct_rank(values: list[float]) -> list[float]`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_components.py
from core.components import components, pct_rank


def test_год_взлёта_а_не_первого_упоминания():
    """Единичные срабатывания 20-летней давности не должны считаться началом.

    В корпусе из 34 млн работ почти у любого термина найдутся омонимы и ошибки
    метаданных. Взлёт = выход на 10% собственного пика.
    """
    counts = {2005: 1, 2006: 2, 2019: 40, 2020: 120, 2021: 300}
    norm = dict.fromkeys(range(2017, 2022), 1000.0)
    c = components(counts, norm, as_of=2021)
    assert c["takeoff_year"] == 2019
    assert c["age"] == 2


def test_растущий_ряд_даёт_положительный_рост():
    counts = {2017: 10, 2018: 20, 2019: 40, 2020: 80, 2021: 160}
    norm = dict.fromkeys(range(2017, 2022), 1000.0)
    assert components(counts, norm, as_of=2021)["growth"] > 0


def test_ускорение_отличает_разгон_от_ровного_роста():
    norm = dict.fromkeys(range(2017, 2022), 1000.0)
    ровный = {2017: 10, 2018: 20, 2019: 40, 2020: 80, 2021: 160}
    разгон = {2017: 10, 2018: 11, 2019: 13, 2020: 60, 2021: 300}
    assert (components(разгон, norm, 2021)["accel"]
            > components(ровный, norm, 2021)["accel"])


def test_разовый_вброс_виден_по_доле_последнего_года():
    counts = {2021: 1314}
    norm = dict.fromkeys(range(2017, 2022), 1000.0)
    assert components(counts, norm, 2021)["last_year_share"] == 1.0


def test_перцентильный_ранг_устойчив_к_выбросу():
    assert pct_rank([1.0, 2.0, 3.0, 1000.0]) == [0.0, 1 / 3, 2 / 3, 1.0]
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_components.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.components'`

- [ ] **Шаг 3: реализация**

Логика перенесена из `spikes/openalex_probe.py:249-318`, она проверена на данных.

```python
# core/components.py
"""Интерпретируемые компоненты Emergence Score.

Каждая компонента объяснима аналитику без ML-образования и показывается в UI:
пользователь видит не «0.803», а «в топ-10% по ускорению».

Опора — рамка Rotolo, Hicks & Martin (2015) «What is an emerging technology?»:
radical novelty (N), fast growth (G), coherence, prominent impact, uncertainty.
Ускорение (A), всплеск (B) и распространение (D) — наша операционализация.
"""
import math

from core.normalize import frequencies

ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ = 5   # ниже — статистический шум и ошибки метаданных
ДОЛЯ_ПИКА_ДЛЯ_ВЗЛЁТА = 0.10


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den


def pct_rank(values: list[float]) -> list[float]:
    """Перцентильный ранг.

    Распределения тяжёлохвостые: z-score и min-max разъезжаются от одного выброса,
    перцентиль устойчив и интерпретируем.
    """
    порядок = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    n = max(1, len(values) - 1)
    for ранг, i in enumerate(порядок):
        out[i] = ранг / n
    return out


def components(counts: dict[int, int], norm: dict[int, float],
               as_of: int, window: int = 5) -> dict:
    years = list(range(as_of - window + 1, as_of + 1))
    freq = frequencies(counts, norm, years)
    logf = [math.log(f + 1.0) for f in freq]

    # N — новизна. Первый год упоминания в чистом виде не работает: у любого
    # термина найдутся единичные срабатывания 20-летней давности.
    история = {y: c for y, c in counts.items() if y <= as_of}
    пик = max(история.values()) if история else 0
    first_mention = takeoff = None
    for y in sorted(история):
        if first_mention is None and история[y] >= ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ:
            first_mention = y
        if takeoff is None and история[y] >= max(ПОРОГ_ПЕРВОГО_УПОМИНАНИЯ * 2,
                                                 ДОЛЯ_ПИКА_ДЛЯ_ВЗЛЁТА * пик):
            takeoff = y
    опорный = takeoff or first_mention
    age = (as_of - опорный) if опорный else 99

    growth = _ols_slope(years, logf)

    # A — ускорение: разница наклонов второй и первой половины окна.
    # Именно оно отличает зарождающийся тренд от равномерно растущей области.
    половина = max(2, window // 2)
    accel = (_ols_slope(years[-половина:], logf[-половина:])
             - _ols_slope(years[:половина], logf[:половина]))

    # B — всплеск: упрощённый Kleinberg (2002)
    база = sum(freq[:-1]) / max(1, len(freq) - 1)
    burst = (freq[-1] + 0.1) / (база + 0.1)

    сумма = sum(freq)
    return {
        "first_mention": first_mention,
        "takeoff_year": takeoff,
        "age": age,
        "growth": growth,
        "accel": accel,
        "burst": burst,
        # зрелость: высокая доля в домене = мейнстрим, а не слабый сигнал
        "maturity": freq[-1],
        "freq_series": [round(f, 2) for f in freq],
        "counts_recent": int(sum(counts.get(y, 0) for y in years)),
        "active_years": sum(1 for f in freq if f > 0),
        "last_year_share": round(freq[-1] / сумма, 3) if сумма > 0 else 1.0,
        "years": years,
        "counts_series": [int(counts.get(y, 0)) for y in years],
    }
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_components.py -v`
Ожидаемо: 5 passed

- [ ] **Шаг 5: коммит**

```bash
git add core/components.py core/test_components.py
git commit -m "Компоненты Emergence Score: новизна, рост, ускорение, всплеск"
```

---

## Task A-04: Структурные фильтры

Каждый порог найден эмпирически и ловит конкретный класс мусора. Без них первое
место в ТОП-15 по ИИ занимал термин `lynching tree`: 1314 «публикаций» 2026 года,
ноль стран, ноль в предыдущие годы — пакетная заливка метаданных.

**Файлы:**
- Создать: `core/filters.py`
- Тест: `core/test_filters.py`

**Интерфейсы:**
- Отдаёт: `ПОРОГИ` (dict), `причина_отказа(comp: dict, n_countries: int) -> str | None`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_filters.py
from core.filters import причина_отказа

ХОРОШИЙ = {"counts_recent": 500, "age": 3, "active_years": 5, "last_year_share": 0.35}


def test_нормальный_кандидат_проходит():
    assert причина_отказа(ХОРОШИЙ, n_countries=40) is None


def test_пакетная_заливка_отсекается():
    заливка = {**ХОРОШИЙ, "last_year_share": 1.0, "active_years": 1}
    assert причина_отказа(заливка, n_countries=0) is not None


def test_одна_лаборатория_ещё_не_тренд():
    assert причина_отказа(ХОРОШИЙ, n_countries=2) == "нет географического распространения"


def test_давно_известная_тема_отсекается():
    assert причина_отказа({**ХОРОШИЙ, "age": 20}, 40) == "слишком старый термин"


def test_мало_доказательств():
    assert причина_отказа({**ХОРОШИЙ, "counts_recent": 3}, 40) == "мало данных"
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_filters.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.filters'`

- [ ] **Шаг 3: реализация**

```python
# core/filters.py
"""Структурные фильтры — антифрод сигналов.

Пороги найдены эмпирически, каждый ловил конкретный мусор в реальных прогонах.
Порядок проверок — от дешёвых к дорогим.
"""

ПОРОГИ = {
    "MAX_AGE": 8,               # лет с года взлёта: старше — не зарождающийся
    "MIN_EVIDENCE": 20,         # документов в окне: меньше — статистический шум
    "MIN_COUNTRIES": 5,         # тема одной лаборатории ещё не тренд
    "MIN_ACTIVE_YEARS": 3,      # нужен устойчивый рост, а не всплеск одного года
    "MAX_LAST_YEAR_SHARE": 0.80,  # >80% активности в одном году = вброс данных
    "MAX_MATURITY_PCT": 0.90,   # верхний дециль по частоте = уже мейнстрим
}


def причина_отказа(comp: dict, n_countries: int) -> str | None:
    """Возвращает текст причины или None, если кандидат прошёл.

    Причины копим и печатаем сводкой: по ним видно, что именно отсеивается,
    и это же идёт на слайд «как мы боремся с ложными сигналами».
    """
    if comp["counts_recent"] < ПОРОГИ["MIN_EVIDENCE"]:
        return "мало данных"
    if comp["age"] > ПОРОГИ["MAX_AGE"]:
        return "слишком старый термин"
    if comp["active_years"] < ПОРОГИ["MIN_ACTIVE_YEARS"]:
        return "всплеск одного года"
    if comp["last_year_share"] > ПОРОГИ["MAX_LAST_YEAR_SHARE"]:
        return "разовый вброс данных"
    if n_countries < ПОРОГИ["MIN_COUNTRIES"]:
        return "нет географического распространения"
    return None
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_filters.py -v`
Ожидаемо: 5 passed

- [ ] **Шаг 5: коммит**

```bash
git add core/filters.py core/test_filters.py
git commit -m "Структурные фильтры против артефактов данных"
```

---

## Task A-05: Дедупликация с лемматизацией и MMR

В бэктесте `generative adversarial network` и `...networks` заняли два места
из пятнадцати, а `convolutional neural network(s)` — ещё два. Жаккар по токенам
даёт 0.5 при пороге 0.6, вложенности тоже нет. Четыре слота из пятнадцати
потеряны на дублях — это чинится лемматизацией.

**Файлы:**
- Создать: `core/dedup.py`
- Тест: `core/test_dedup.py`

**Интерфейсы:**
- Отдаёт: `лемма(слово: str) -> str`, `dedup(rows: list[dict], jaccard: float = 0.6) -> list[dict]`, `mmr(rows, emb_by_row, k, lam=0.7) -> list[dict]`
- Ожидает в `rows`: ключи `label`, `es`, опционально `emb_row`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_dedup.py
import numpy as np

from core.dedup import dedup, лемма, mmr


def test_множественное_число_схлопывается_в_единственное():
    assert лемма("networks") == "network"
    assert лемма("studies") == "study"
    assert лемма("analysis") == "analysis"     # не 'analysi'
    assert лемма("bus") == "bus"


def test_дубли_по_числу_схлопываются():
    rows = [{"label": "generative adversarial networks", "es": 0.56},
            {"label": "generative adversarial network", "es": 0.51},
            {"label": "federated learning", "es": 0.40}]
    итог = dedup(rows)
    assert len(итог) == 2
    assert итог[0]["label"] == "generative adversarial networks"
    assert "generative adversarial network" in итог[0]["aliases"]


def test_вложенные_варианты_схлопываются():
    rows = [{"label": "explainable machine learning", "es": 0.80},
            {"label": "explainable machine", "es": 0.47}]
    assert len(dedup(rows)) == 1


def test_mmr_не_берёт_две_близкие_темы_подряд():
    emb = {0: np.array([1.0, 0.0]), 1: np.array([0.99, 0.14]),
           2: np.array([0.0, 1.0])}
    rows = [{"label": "a", "es": 0.9, "emb_row": 0},
            {"label": "b", "es": 0.85, "emb_row": 1},
            {"label": "c", "es": 0.5, "emb_row": 2}]
    assert [r["label"] for r in mmr(rows, emb, k=2)] == ["a", "c"]
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_dedup.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.dedup'`

- [ ] **Шаг 3: реализация**

```python
# core/dedup.py
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
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_dedup.py -v`
Ожидаемо: 4 passed

- [ ] **Шаг 5: коммит**

```bash
git add core/dedup.py core/test_dedup.py
git commit -m "Дедуп с лемматизацией: чинит потерю слотов на формах числа"
```

---

## Task A-06: Emergence Score и сборка trends.parquet

**Файлы:**
- Создать: `core/score.py`, `core/build.py`
- Тест: `core/test_score.py`

**Интерфейсы:**
- Отдаёт: `ВЕСА`, `ВЕРСИЯ_МЕТОДОЛОГИИ`, `emergence_scores(rows: list[dict]) -> list[dict]` (добавляет `es`, `parts`, `maturity_pct`, сортирует по убыванию), `стадия(comp, maturity_pct) -> str`, `уверенность(comp, n_countries) -> str`
- CLI: `python -m core.build --domain artificial-intelligence --as-of 2026 [--top 15]`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_score.py
from core.score import emergence_scores, стадия, уверенность


def _строка(age, growth, accel, burst, maturity, countries):
    return {"label": f"t{age}{growth}", "countries": countries,
            "c": {"age": age, "growth": growth, "accel": accel,
                  "burst": burst, "maturity": maturity}}


def test_молодой_и_растущий_обгоняет_старый_и_ровный():
    rows = emergence_scores([
        _строка(2, 1.5, 0.9, 5.0, 10.0, 40),     # молодой, разгоняется
        _строка(8, 0.1, 0.0, 1.0, 900.0, 40),    # старый мейнстрим
    ])
    assert rows[0]["c"]["age"] == 2
    assert rows[0]["es"] > rows[1]["es"]


def test_штраф_за_зрелость_понижает_мейнстрим():
    rows = emergence_scores([
        _строка(3, 1.0, 0.5, 2.0, 1.0, 30),
        _строка(3, 1.0, 0.5, 2.0, 5000.0, 30),
    ])
    зрелый = next(r for r in rows if r["c"]["maturity"] == 5000.0)
    молодой = next(r for r in rows if r["c"]["maturity"] == 1.0)
    assert молодой["es"] > зрелый["es"]


def test_стадия_выводится_из_возраста_и_зрелости():
    assert стадия({"age": 2}, 0.3) == "emerging"
    assert стадия({"age": 5}, 0.3) == "early_growth"
    assert стадия({"age": 5}, 0.95) == "scaling"


def test_мало_данных_значит_низкая_уверенность():
    assert уверенность({"counts_recent": 30}, 6) == "low"
    assert уверенность({"counts_recent": 500}, 40) == "high"
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_score.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.score'`

- [ ] **Шаг 3: реализация score.py**

```python
# core/score.py
"""Emergence Score = взвешенная сумма перцентильных рангов × штраф за зрелость.

Веса подлежат калибровке на бэктесте (см. validation/). Менять их вручную
«на глаз» нельзя: любое изменение обязано улучшать Precision@15 на срезе 2021.
"""
import math

ВЕРСИЯ_МЕТОДОЛОГИИ = "1.0"

ВЕСА = {"novelty": 0.20, "growth": 0.32, "accel": 0.23, "burst": 0.15, "diffusion": 0.10}
ШТРАФ_ЗА_ЗРЕЛОСТЬ = 0.5

from core.components import pct_rank  # noqa: E402


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
    """Честный флаг вместо ложной точности: когда данных мало, так и пишем."""
    if comp["counts_recent"] >= 200 and n_countries >= 15:
        return "high"
    if comp["counts_recent"] >= 50 and n_countries >= 8:
        return "medium"
    return "low"
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_score.py -v`
Ожидаемо: 4 passed

- [ ] **Шаг 5: сборка trends.parquet**

```python
# core/build.py
"""Стадия core: кандидаты -> ранжированный ТОП с доказательной базой.

    python -m core.build --domain artificial-intelligence --as-of 2026
    python -m core.build --domain artificial-intelligence --as-of 2021   # бэктест
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
    ряды = year_counts(index_dir, corpus_path)
    страны = country_spread(index_dir, corpus_path, as_of - 2, as_of)
    подписи = {r[0]: (r[1], r[2]) for r in duckdb.sql(
        f"SELECT cand_id, label, emb_row FROM '{index_dir}/candidates.parquet'"
    ).fetchall()}

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

    sys.stderr.write(f"[core] прошло {len(строки)} из {len(ряды)}; отсеяно: {dict(отказы)}\n")

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
```

- [ ] **Шаг 6: прогон и валидация контракта**

```bash
uv run python -m core.build --domain golden --as-of 2026
uv run python contracts/validate.py data/index/golden/trends.parquet --schema trends
```
Ожидаемо: 15 строк, все проходят контракт.

- [ ] **Шаг 7: коммит**

```bash
git add core/score.py core/build.py core/test_score.py data/index/golden/trends.parquet
git commit -m "Emergence Score и сборка trends.parquet"
```

---

## Task A-07: Кандидаты v2 — главная задача недели

Сейчас система находит `explainable machine learning` и `fraud detection` —
мейнстрим и прикладные применения. Это то, что отделяет «среднее решение»
от победителя, и это твой личный критерий готовности.

**Файлы:**
- Изменить: `core/build.py` (взвешивание источников по лагу сигнала)
- Создать: `core/lead.py`
- Тест: `core/test_lead.py`

**Интерфейсы:**
- Отдаёт: `вес_источника(doc_type: str) -> float`, `лаг_препринтов(counts_preprint, counts_article) -> int | None`

- [ ] **Шаг 1: падающий тест**

```python
# core/test_lead.py
from core.lead import вес_источника, лаг_препринтов


def test_опережающие_источники_весят_больше():
    assert вес_источника("preprint") > вес_источника("article")
    assert вес_источника("model") > вес_источника("article")
    assert вес_источника("patent") < вес_источника("preprint")


def test_фора_препринтов_измеряется_годом_взлёта():
    препринты = {2019: 12, 2020: 80, 2021: 200}
    статьи = {2020: 11, 2021: 90, 2022: 210}
    assert лаг_препринтов(препринты, статьи) == 1


def test_нет_данных_нет_лага():
    assert лаг_препринтов({}, {2021: 50}) is None
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest core/test_lead.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'core.lead'`

- [ ] **Шаг 3: реализация**

```python
# core/lead.py
"""Опережающие и запаздывающие источники.

Измерено на данных: медианная фора препринтов над журнальными статьями —
1 год. Тренд, видный только в запаздывающих источниках, уже не зарождающийся;
видный только в опережающих — гипотеза с высокой неопределённостью.
Нужный заказчику сигнал живёт на пересечении.
"""
ВЕСА_ИСТОЧНИКОВ = {
    "model": 1.6,      # HuggingFace: архитектура появляется раньше публикации
    "repo": 1.5,
    "preprint": 1.4,   # измеренная фора: медиана 1 год
    "article": 1.0,
    "patent": 0.9,     # запаздывающий, но признак коммерциализации
    "report": 0.8,
}

ПОРОГ_ВЗЛЁТА = 10
ДОЛЯ_ПИКА = 0.10


def вес_источника(doc_type: str) -> float:
    return ВЕСА_ИСТОЧНИКОВ.get(doc_type, 1.0)


def _взлёт(counts: dict[int, int]) -> int | None:
    if not counts:
        return None
    пик = max(counts.values())
    for y in sorted(counts):
        if counts[y] >= max(ПОРОГ_ВЗЛЁТА, ДОЛЯ_ПИКА * пик):
            return y
    return None


def лаг_препринтов(counts_preprint: dict[int, int],
                   counts_article: dict[int, int]) -> int | None:
    """На сколько лет препринты опередили журналы по году взлёта."""
    p, a = _взлёт(counts_preprint), _взлёт(counts_article)
    return (a - p) if (p is not None and a is not None) else None
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest core/test_lead.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 5: включить веса в годовые ряды**

В `core/series.py` заменить `count(*)` на взвешенную сумму:

```python
    строки = duckdb.sql(f"""
        SELECT cd.cand_id, w.year,
               sum(CASE w.doc_type
                     WHEN 'model'    THEN 1.6 WHEN 'repo'    THEN 1.5
                     WHEN 'preprint' THEN 1.4 WHEN 'patent'  THEN 0.9
                     WHEN 'report'   THEN 0.8 ELSE 1.0 END) AS n
        FROM '{links}' cd JOIN '{corpus_path}' w USING (doc_id)
        GROUP BY 1, 2
    """).fetchall()
```

и в `year_counts` округлять: `out[cand_id][int(year)] = int(round(n))`.

- [ ] **Шаг 6: проверить на бэктесте**

```bash
uv run python -m core.build --domain artificial-intelligence --as-of 2021 --top 15
```

Критерий готовности: в ТОП-15 появились `transformer`, `self-supervised learning`
или `diffusion model` — то, что метод обязан был найти в 2021 и не находил.
Если нет — проблема в кандидатах, писать Константину, а не крутить веса.

- [ ] **Шаг 7: коммит**

```bash
git add core/lead.py core/test_lead.py core/series.py
git commit -m "Взвешивание источников по лагу сигнала: препринты вперёд журналов"
```

---

## Task A-08: Отчёт валидации

Без валидации методология — набор коэффициентов. Эталонный список собирается
**до** прогонов, чтобы не было соблазна подогнать: это вопрос честности метода,
и жюри такое считывает.

**Файлы:**
- Создать: `validation/reference.py`, `validation/metrics.py`, `validation/baselines.py`, `validation/report.py`
- Тест: `validation/test_metrics.py`

**Интерфейсы:**
- Отдаёт: `ЭТАЛОН_ИИ_2021` (list[str]), `precision_at_k(найденные, эталон, k) -> float`, `lead_time(trend, counts) -> int | None`, `рост_после_среза(counts, as_of, до_года) -> float`

- [ ] **Шаг 1: эталонный список — сначала, до кода**

```python
# validation/reference.py
"""Эталон: технологии, про которые в 2021 было ясно, что они выстрелят.

Список собран ДО прогонов детектора и не меняется по их результатам.
Подгонять эталон под выдачу — то же самое, что подсматривать ответ.
"""
ЭТАЛОН_ИИ_2021 = [
    "transformer", "vision transformer", "diffusion model",
    "self-supervised learning", "contrastive learning", "foundation model",
    "large language model", "prompt", "retrieval augmented generation",
    "mixture of experts", "state space model", "neural radiance field",
    "graph neural network", "federated learning", "physics-informed neural network",
    "vision-language model", "low-rank adaptation", "vector database",
]

# Заведомо НЕ зарождающиеся в 2021 — если они в топе, метод ловит мейнстрим
АНТИЭТАЛОН_ИИ_2021 = [
    "convolutional neural network", "random forest", "support vector machine",
    "deep learning", "machine learning", "internet of things", "covid-19 pandemic",
]
```

- [ ] **Шаг 2: падающий тест на метрики**

```python
# validation/test_metrics.py
from validation.metrics import precision_at_k, рост_после_среза


def test_precision_считает_совпадения_по_вхождению_подстроки():
    найдено = ["vision transformer", "fraud detection", "diffusion models"]
    эталон = ["transformer", "diffusion model"]
    assert precision_at_k(найдено, эталон, k=3) == 2 / 3


def test_рост_после_среза():
    counts = {2021: 100, 2022: 200, 2023: 300}
    assert рост_после_среза(counts, as_of=2021, до_года=2023) == 3.0


def test_нулевой_срез_не_ломает_деление():
    assert рост_после_среза({2022: 50}, as_of=2021, до_года=2023) > 1.0
```

- [ ] **Шаг 3: убедиться, что падает**

Запустить: `uv run pytest validation/test_metrics.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'validation.metrics'`

- [ ] **Шаг 4: реализация метрик**

```python
# validation/metrics.py
"""Метрики честности метода."""


def _нормализовать(s: str) -> str:
    return s.lower().replace("-", " ").rstrip("s")


def precision_at_k(найденные: list[str], эталон: list[str], k: int = 15) -> float:
    """Доля позиций топ-k, попавших в эталон.

    Сравнение по вхождению подстроки: 'vision transformer' засчитывается
    эталонному 'transformer', потому что это тот же тренд.
    """
    верхушка = [_нормализовать(x) for x in найденные[:k]]
    эт = [_нормализовать(x) for x in эталон]
    попаданий = sum(1 for t in верхушка if any(e in t or t in e for e in эт))
    return попаданий / max(1, len(верхушка))


def рост_после_среза(counts: dict[int, int], as_of: int, до_года: int) -> float:
    """Во сколько раз пик после среза превысил уровень на срезе."""
    на_срезе = counts.get(as_of, 0)
    после = max((counts.get(y, 0) for y in range(as_of + 1, до_года + 1)), default=0)
    return round((после + 1) / (на_срезе + 1), 2)


def lead_time(takeoff_year: int | None, counts: dict[int, int]) -> int | None:
    """За сколько лет до пика тренд был обнаружен."""
    if not takeoff_year or not counts:
        return None
    год_пика = max(counts, key=lambda y: counts[y])
    return год_пика - takeoff_year
```

- [ ] **Шаг 5: тесты зелёные**

Запустить: `uv run pytest validation/test_metrics.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 6: baseline и отчёт**

```python
# validation/baselines.py
"""Базовые методы. Без сравнения непонятно, что даёт наша модель."""


def топ_по_абсолютному_приросту(ряды: dict[str, dict[int, int]], as_of: int,
                                k: int = 15) -> list[str]:
    """«Наивный рост»: во сколько документов вырос за 3 года."""
    прирост = {c: s.get(as_of, 0) - s.get(as_of - 3, 0) for c, s in ряды.items()}
    return sorted(прирост, key=lambda c: прирост[c], reverse=True)[:k]


def топ_по_cagr(ряды: dict[str, dict[int, int]], as_of: int, k: int = 15) -> list[str]:
    """«Наивный процент»: среднегодовой темп роста за 3 года."""
    def cagr(s: dict[int, int]) -> float:
        было, стало = s.get(as_of - 3, 0), s.get(as_of, 0)
        if было < 5:
            return 0.0
        return (стало / было) ** (1 / 3) - 1
    return sorted(ряды, key=lambda c: cagr(ряды[c]), reverse=True)[:k]
```

```python
# validation/report.py
"""Отчёт валидации: validation/REPORT.md + JSON для /api/v1/methodology.

    python -m validation.report --domain artificial-intelligence --as-of 2021
"""
import argparse
import json
from pathlib import Path

import duckdb

from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА
from core.filters import ПОРОГИ
from core.series import year_counts
from validation.metrics import lead_time, precision_at_k, рост_после_среза
from validation.reference import АНТИЭТАЛОН_ИИ_2021, ЭТАЛОН_ИИ_2021


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--as-of", type=int, default=2021)
    ap.add_argument("--до-года", type=int, default=2026)
    args = ap.parse_args()

    index_dir = Path("data/index") / args.domain
    corpus = Path("data/corpus") / args.domain / "works.parquet"
    if not corpus.exists():
        corpus = index_dir / "works.parquet"

    тренды = duckdb.sql(f"""
        SELECT rank, label, takeoff_year, cand_id FROM '{index_dir}/trends.parquet'
        WHERE as_of = {args.as_of} ORDER BY rank
    """).fetchall()
    ряды = year_counts(index_dir, corpus)

    метки = [t[1] for t in тренды]
    p15 = precision_at_k(метки, ЭТАЛОН_ИИ_2021, k=15)
    мейнстрим = precision_at_k(метки, АНТИЭТАЛОН_ИИ_2021, k=15)
    выросли = [(t[1], рост_после_среза(ряды.get(t[3], {}), args.as_of, args.до_года))
               for t in тренды]
    доля_выросших = sum(1 for _, x in выросли if x > 1.2) / max(1, len(выросли))
    лаги = [lead_time(t[2], ряды.get(t[3], {})) for t in тренды]
    лаги = [x for x in лаги if x is not None]

    итог = {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ, "as_of": args.as_of,
        "weights": ВЕСА, "filters": ПОРОГИ,
        "precision_at_15": round(p15, 3),
        "доля_мейнстрима_в_топе": round(мейнстрим, 3),
        "доля_выросших_после_среза": round(доля_выросших, 3),
        "медианный_lead_time": sorted(лаги)[len(лаги) // 2] if лаги else None,
    }
    Path("validation/report.json").write_text(json.dumps(итог, ensure_ascii=False, indent=2))

    строки = "\n".join(
        f"| {t[0]} | {t[1]} | {t[2]} | x{р} |" for t, (_, р) in zip(тренды, выросли, strict=True))
    Path("validation/REPORT.md").write_text(f"""# Отчёт валидации

Срез `as_of = {args.as_of}`, проверка по данным до {args.до_года}.

| Метрика | Значение | Смысл |
|---|---|---|
| Precision@15 по эталону | {p15:.0%} | доля топа, попавшая в список заведомо выстреливших технологий |
| Доля мейнстрима в топе | {мейнстрим:.0%} | **чем меньше, тем лучше**: это уже известные темы |
| Выросли после среза | {доля_выросших:.0%} | доля трендов, чья публикационная активность выросла |
| Медианный lead time | {итог['медианный_lead_time']} лет | за сколько лет до пика тренд обнаружен |

## ТОП-{len(тренды)} на срезе {args.as_of}

| # | Тренд | Год взлёта | Рост после среза |
|---|---|---|---|
{строки}

Веса: `{ВЕСА}`
Пороги фильтров: `{ПОРОГИ}`
""", encoding="utf-8")
    print(json.dumps(итог, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 7: прогнать и посмотреть честные цифры**

```bash
uv run python -m core.build --domain artificial-intelligence --as-of 2021
uv run python -m validation.report --domain artificial-intelligence --as-of 2021
cat validation/REPORT.md
```

«Доля мейнстрима в топе» — та метрика, которую хочется спрятать. Не прячем:
слайд «что метод не умеет» работает на защите лучше идеальной картинки.

- [ ] **Шаг 8: коммит**

```bash
git add validation/
git commit -m "Отчёт валидации: Precision@15, lead time, доля мейнстрима"
```
