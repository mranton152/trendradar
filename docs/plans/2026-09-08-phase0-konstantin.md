# Фаза 0 — Константин: данные и семантика

> Общие правила и Global Constraints — в [README.md](README.md). Личный бриф — [../../team/PROMPT-konstantin.md](../../team/PROMPT-konstantin.md).

**Цель:** превратить открытые источники в корпус документов и набор кандидатов
в тренды с эмбеддингами, в формате, который сразу читают Антон и Михаил.

**Архитектура:** две стадии-CLI. `ingest` ходит по сети и пишет
`works.parquet`; `semantic` читает его, считает эмбеддинги на RTX 3070,
кластеризует и пишет `candidates.parquet` + `cand_docs.parquet` + `embeddings.npy`.
Обе стадии идемпотентны: повторный запуск не начинает с нуля.

**Стек:** httpx, pyarrow, duckdb, sentence-transformers, umap-learn, hdbscan, scikit-learn.

---

## Task K-01: HTTP-слой с кэшем на диск

Всё общение с источниками идёт через него. Кэш нужен не для скорости, а потому что
полный прогон корпуса — часы сети, и он обязан переживать обрыв.

**Файлы:**
- Создать: `ingest/http.py`
- Тест: `ingest/test_http.py`

**Интерфейсы:**
- Отдаёт: `CachedClient(base_url, *, mailto=None, cache_dir="data/cache", timeout=60.0, max_retries=4)` с методом `get_json(path: str, params: dict | None) -> dict`

- [ ] **Шаг 1: падающий тест**

```python
# ingest/test_http.py
import json
import httpx
from ingest.http import CachedClient


def test_кэш_отдаёт_ответ_не_трогая_сеть(tmp_path):
    client = CachedClient("https://api.example.com", cache_dir=tmp_path)
    cp = client._cache_path("/works", {"filter": "x"})
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"results": [1, 2]}))

    def взрыв(request):
        raise AssertionError("при попадании в кэш сеть вызываться не должна")

    client._client = httpx.Client(transport=httpx.MockTransport(взрыв))
    assert client.get_json("/works", {"filter": "x"}) == {"results": [1, 2]}


def test_ответ_сохраняется_в_кэш(tmp_path):
    client = CachedClient("https://api.example.com", cache_dir=tmp_path)
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    assert client.get_json("/works", {"filter": "y"}) == {"ok": True}
    assert client._cache_path("/works", {"filter": "y"}).exists()
```

- [ ] **Шаг 2: убедиться, что тест падает**

Запустить: `uv run pytest ingest/test_http.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'ingest.http'`

- [ ] **Шаг 3: реализация**

```python
# ingest/http.py
"""Единая точка выхода в сеть: кэш на диск, ретраи с экспоненциальной паузой."""
import hashlib
import json
import time
from pathlib import Path

import httpx


class CachedClient:
    """HTTP-клиент, который каждый ответ кладёт на диск и больше не перезапрашивает.

    Кэш нужен не ради скорости: полный прогон корпуса идёт часами, и он обязан
    переживать обрыв связи и перезапуск без потери сделанной работы.
    """

    def __init__(self, base_url: str, *, mailto: str | None = None,
                 cache_dir: str | Path = "data/cache",
                 timeout: float = 60.0, max_retries: int = 4):
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto
        self.cache_dir = Path(cache_dir)
        self.max_retries = max_retries
        ua = f"trendradar/0.1 (+mailto:{mailto})" if mailto else "trendradar/0.1"
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": ua, "Accept": "application/json"})

    def _cache_path(self, path: str, params: dict) -> Path:
        key = json.dumps([path, sorted(params.items())], sort_keys=True, ensure_ascii=False)
        h = hashlib.sha1(key.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    def get_json(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        if self.mailto:
            params.setdefault("mailto", self.mailto)   # polite pool у OpenAlex
        cp = self._cache_path(path, params)
        if cp.exists():
            return json.loads(cp.read_text())
        data = self._fetch(path, params)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def _fetch(self, path: str, params: dict) -> dict:
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                r = self._client.get(f"{self.base_url}{path}", params=params)
                if r.status_code == 404:
                    return {}
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, json.JSONDecodeError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        return {}
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest ingest/test_http.py -v`
Ожидаемо: 2 passed

- [ ] **Шаг 5: коммит**

```bash
git add ingest/http.py ingest/test_http.py
git commit -m "Коннекторы: HTTP-слой с кэшем на диск и ретраями"
```

---

## Task K-02: Нормализация OpenAlex → схема WORKS

**Файлы:**
- Создать: `ingest/normalize.py`
- Тест: `ingest/test_normalize.py`

**Интерфейсы:**
- Потребляет: `contracts.schemas.WORKS`
- Отдаёт: `from_openalex(rec: dict, domain: str, harvested_at: str) -> dict` — строка под схему `WORKS`; `reconstruct_abstract(inv: dict | None) -> str | None`

- [ ] **Шаг 1: падающий тест**

OpenAlex отдаёт абстракт не текстом, а инвертированным индексом `{слово: [позиции]}` —
его надо собрать обратно.

```python
# ingest/test_normalize.py
from ingest.normalize import from_openalex, reconstruct_abstract

СЫРОЙ = {
    "id": "https://openalex.org/W123",
    "title": "Physics-informed neural networks",
    "abstract_inverted_index": {"We": [0], "solve": [1], "PDEs": [2]},
    "publication_year": 2022,
    "publication_date": "2022-04-01",
    "language": "en",
    "doi": "https://doi.org/10.1/abc",
    "primary_location": {"landing_page_url": "https://example.org/w123"},
    "cited_by_count": 42,
    "authorships": [
        {"author": {"display_name": "A. Ivanov"},
         "institutions": [{"display_name": "MSU", "country_code": "RU"}]},
        {"author": {"display_name": "B. Smith"},
         "institutions": [{"display_name": "MIT", "country_code": "US"},
                          {"display_name": "MIT", "country_code": "US"}]},
    ],
    "concepts": [{"display_name": "Neural network"}],
}


def test_абстракт_собирается_из_инвертированного_индекса():
    assert reconstruct_abstract({"b": [1], "a": [0]}) == "a b"
    assert reconstruct_abstract(None) is None


def test_запись_openalex_ложится_в_схему_works():
    row = from_openalex(СЫРОЙ, domain="artificial-intelligence",
                        harvested_at="2026-09-09")
    assert row["doc_id"] == "openalex:W123"
    assert row["source"] == "openalex"
    assert row["doc_type"] == "article"
    assert row["abstract"] == "We solve PDEs"
    assert row["year"] == 2022
    assert row["doi"] == "10.1/abc"           # префикс doi.org снят
    assert row["url"] == "https://example.org/w123"
    assert sorted(row["countries"]) == ["RU", "US"]   # без дублей
    assert row["institutions"] == ["MSU", "MIT"]      # тоже без дублей
    assert row["domain"] == "artificial-intelligence"


def test_битая_запись_без_названия_не_ломает_нормализацию():
    assert from_openalex({"id": "https://openalex.org/W9"}, "d", "2026-09-09") is None
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest ingest/test_normalize.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'ingest.normalize'`

- [ ] **Шаг 3: реализация**

```python
# ingest/normalize.py
"""Приведение записей любого источника к схеме WORKS.

Правило: если у записи нет названия или года — она бесполезна для анализа
динамики, возвращаем None и пропускаем. Молча терять данные нельзя,
поэтому harvest считает пропуски и печатает их количество.
"""


def reconstruct_abstract(inv: dict | None) -> str | None:
    """OpenAlex хранит абстракт как {слово: [позиции]}. Собираем обратно в текст."""
    if not inv:
        return None
    pairs = [(pos, word) for word, positions in inv.items() for pos in positions]
    pairs.sort()
    return " ".join(word for _, word in pairs) or None


def _уникальные(значения) -> list:
    """Сохраняем порядок появления и выкидываем дубли и пустые."""
    видели, out = set(), []
    for v in значения:
        if v and v not in видели:
            видели.add(v)
            out.append(v)
    return out


def from_openalex(rec: dict, domain: str, harvested_at: str) -> dict | None:
    title = rec.get("title") or rec.get("display_name")
    year = rec.get("publication_year")
    native_id = (rec.get("id") or "").rsplit("/", 1)[-1]
    if not (title and year and native_id):
        return None

    authorships = rec.get("authorships") or []
    institutions = [i for a in authorships for i in (a.get("institutions") or [])]

    doi = rec.get("doi") or None
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    url = ((rec.get("primary_location") or {}).get("landing_page_url")
           or f"https://openalex.org/{native_id}")

    typ = rec.get("type") or "article"
    doc_type = {"article": "article", "preprint": "preprint",
                "review": "article", "book-chapter": "article"}.get(typ, "article")

    return {
        "doc_id": f"openalex:{native_id}",
        "source": "openalex",
        "doc_type": doc_type,
        "title": title,
        "abstract": reconstruct_abstract(rec.get("abstract_inverted_index")),
        "year": int(year),
        "date": rec.get("publication_date"),
        "lang": rec.get("language"),
        "doi": doi,
        "url": url,
        "cited_by": rec.get("cited_by_count"),
        "countries": _уникальные(i.get("country_code") for i in institutions),
        "institutions": _уникальные(i.get("display_name") for i in institutions),
        "authors": _уникальные((a.get("author") or {}).get("display_name")
                               for a in authorships),
        "concepts": _уникальные(c.get("display_name")
                                for c in (rec.get("concepts") or [])),
        "domain": domain,
        "harvested_at": harvested_at,
    }
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest ingest/test_normalize.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 5: коммит**

```bash
git add ingest/normalize.py ingest/test_normalize.py
git commit -m "Нормализация записей OpenAlex в схему WORKS"
```

---

## Task K-03: Запись works.parquet и золотой снапшот

**Это критический путь.** Пока файла нет, Антон и Михаил работают вхолостую.
Сделать в первый день и написать в чат.

**Файлы:**
- Создать: `ingest/writer.py`, `ingest/sources/openalex.py`, `ingest/harvest.py`
- Тест: `ingest/test_writer.py`

**Интерфейсы:**
- Отдаёт: `write_works(rows: list[dict], path: str | Path) -> int` — пишет parquet по схеме `WORKS`, возвращает число строк
- Отдаёт: `OpenAlexSource(client).iter_works(domain_filter: str, y_from: int, y_to: int) -> Iterator[dict]`
- CLI: `python -m ingest.harvest --domain "artificial intelligence" --years 2015-2026 [--limit N]`

- [ ] **Шаг 1: падающий тест**

```python
# ingest/test_writer.py
import pyarrow.parquet as pq
import pytest

from contracts.schemas import WORKS
from ingest.writer import write_works

СТРОКА = {
    "doc_id": "openalex:W1", "source": "openalex", "doc_type": "article",
    "title": "T", "abstract": None, "year": 2024, "date": None, "lang": "en",
    "doi": None, "url": "https://example.org/1", "cited_by": 0,
    "countries": ["RU"], "institutions": [], "authors": [], "concepts": [],
    "domain": "d", "harvested_at": "2026-09-09",
}


def test_parquet_пишется_ровно_по_схеме(tmp_path):
    p = tmp_path / "works.parquet"
    assert write_works([СТРОКА], p) == 1
    assert pq.read_schema(p).equals(WORKS)


def test_дубли_doc_id_схлопываются(tmp_path):
    p = tmp_path / "works.parquet"
    assert write_works([СТРОКА, dict(СТРОКА)], p) == 1


def test_строка_без_обязательного_поля_отвергается(tmp_path):
    плохая = dict(СТРОКА)
    плохая["url"] = None
    with pytest.raises(ValueError, match="url"):
        write_works([плохая], tmp_path / "w.parquet")
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest ingest/test_writer.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'ingest.writer'`

- [ ] **Шаг 3: реализация writer**

```python
# ingest/writer.py
"""Запись корпуса в parquet строго по контракту."""
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import WORKS

ОБЯЗАТЕЛЬНЫЕ = [f.name for f in WORKS if not f.nullable]


def write_works(rows: list[dict], path: str | Path) -> int:
    """Схлопывает дубли по doc_id, проверяет обязательные поля, пишет parquet."""
    по_id = {}
    for r in rows:
        for поле in ОБЯЗАТЕЛЬНЫЕ:
            if r.get(поле) in (None, ""):
                raise ValueError(f"строка {r.get('doc_id')}: пустое обязательное поле '{поле}'")
        по_id[r["doc_id"]] = r

    итог = sorted(по_id.values(), key=lambda r: (r["year"], r["doc_id"]))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(итог, schema=WORKS), path, compression="zstd")
    return len(итог)
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest ingest/test_writer.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 5: источник OpenAlex**

`cursor`-пагинация, а не `page`: OpenAlex не отдаёт больше 10 000 записей через `page`.

```python
# ingest/sources/openalex.py
"""Коннектор OpenAlex — основной источник.

34,5 млн работ по концепту AI, CC0, ключ не нужен (только mailto для polite pool).
Пагинация курсором: через page отдаётся максимум 10 000 записей.
"""
from collections.abc import Iterator

from ingest.http import CachedClient

ПОЛЯ = ("id,title,publication_year,publication_date,language,doi,type,"
        "cited_by_count,primary_location,authorships,concepts,abstract_inverted_index")


class OpenAlexSource:
    def __init__(self, client: CachedClient | None = None, mailto: str = "flesha98@gmail.com"):
        self.client = client or CachedClient("https://api.openalex.org", mailto=mailto)

    def resolve_concept(self, text: str) -> dict:
        """Свободный текст пользователя -> концепт OpenAlex."""
        d = self.client.get_json("/concepts", {"search": text, "per-page": 5})
        results = d.get("results") or []
        if not results:
            return {"filter": f'title_and_abstract.search:"{text}"', "name": text}
        top = results[0]
        return {
            "filter": f"concepts.id:{top['id'].rsplit('/', 1)[-1]}",
            "name": top["display_name"],
            "works_count": top.get("works_count"),
        }

    def iter_works(self, domain_filter: str, y_from: int, y_to: int,
                   limit: int | None = None) -> Iterator[dict]:
        """Все работы домена за годы. Идём по годам, внутри года — курсором."""
        отдано = 0
        for year in range(y_from, y_to + 1):
            cursor = "*"
            while cursor:
                d = self.client.get_json("/works", {
                    "filter": f"{domain_filter},publication_year:{year}",
                    "per-page": 200, "cursor": cursor, "select": ПОЛЯ,
                })
                results = d.get("results") or []
                if not results:
                    break
                for rec in results:
                    yield rec
                    отдано += 1
                    if limit and отдано >= limit:
                        return
                cursor = (d.get("meta") or {}).get("next_cursor")
```

- [ ] **Шаг 6: CLI harvest**

```python
# ingest/harvest.py
"""CLI сбора корпуса.

    python -m ingest.harvest --domain "artificial intelligence" --years 2015-2026
    python -m ingest.harvest --domain "artificial intelligence" --limit 5000 --out data/index/golden
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from ingest.normalize import from_openalex
from ingest.sources.openalex import OpenAlexSource
from ingest.writer import write_works


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--years", default="2015-2026")
    ap.add_argument("--limit", type=int, default=None, help="для золотого снапшота")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    y_from, y_to = (int(x) for x in args.years.split("-"))
    src = OpenAlexSource()
    concept = src.resolve_concept(args.domain)
    домен = slug(args.domain)
    сегодня = dt.date.today().isoformat()
    sys.stderr.write(f"[домен] {args.domain} -> {concept['name']} ({concept['filter']})\n")

    строки, пропущено = [], 0
    for rec in src.iter_works(concept["filter"], y_from, y_to, limit=args.limit):
        row = from_openalex(rec, домен, сегодня)
        if row:
            строки.append(row)
        else:
            пропущено += 1
        if len(строки) % 5000 == 0 and строки:
            sys.stderr.write(f"[сбор] {len(строки)} записей\n")

    out_dir = Path(args.out) if args.out else Path("data/corpus") / домен
    n = write_works(строки, out_dir / "works.parquet")
    (out_dir / "meta.json").write_text(json.dumps({
        "domain": домен, "domain_query": args.domain, "concept": concept["name"],
        "years": [y_from, y_to], "built_at": сегодня,
        "n_works": n, "skipped": пропущено,
        "stages": {"ingest": сегодня},
    }, ensure_ascii=False, indent=2))
    sys.stderr.write(f"[готово] {n} записей в {out_dir}, пропущено битых: {пропущено}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 7: собрать золотой снапшот**

```bash
uv run python -m ingest.harvest --domain "artificial intelligence" \
    --years 2015-2026 --limit 5000 --out data/index/golden
uv run python contracts/validate.py data/index/golden/works.parquet --schema works
du -h data/index/golden/works.parquet
```
Ожидаемо: `✓ ... соответствует контракту 'works' (5000 строк)`, файл меньше 50 МБ.
Если больше — уменьшить `--limit`, снапшот не должен раздувать репозиторий.

- [ ] **Шаг 8: коммит и сообщение в чат**

```bash
git add ingest/ data/index/golden/
git commit -m "Коннектор OpenAlex, CLI сбора корпуса, золотой снапшот"
```

После мержа написать в чат: «золотой снапшот в main, 5000 документов, можно работать».
Антон и Михаил до этого момента заблокированы.

---

## Task K-04: Полный корпус по домену ИИ

Половина решения задачи. Прототип находит уже популярные темы именно потому,
что смотрит на выборку: слабый сигнал — это 10–100 работ в год из миллионов,
в выборке 2500 заголовков его физически нет.

**Файлы:**
- Изменить: `ingest/harvest.py` (докачка)

- [ ] **Шаг 1: докачка вместо прогона с нуля**

Прогон идёт часами и обязан переживать обрыв. Добавить в `main()` перед сбором:

```python
    существующие = set()
    parquet = out_dir / "works.parquet"
    if parquet.exists() and not args.limit:
        import duckdb
        существующие = {r[0] for r in duckdb.sql(
            f"SELECT doc_id FROM '{parquet}'").fetchall()}
        sys.stderr.write(f"[докачка] уже собрано {len(существующие)} записей\n")
        строки = duckdb.sql(f"SELECT * FROM '{parquet}'").df().to_dict("records")
```

и в цикле пропускать уже собранное:

```python
        if f"openalex:{(rec.get('id') or '').rsplit('/', 1)[-1]}" in существующие:
            continue
```

- [ ] **Шаг 2: запустить полный прогон на ночь**

```bash
nohup uv run python -m ingest.harvest --domain "artificial intelligence" \
    --years 2015-2026 > harvest.log 2>&1 &
tail -f harvest.log
```

- [ ] **Шаг 3: проверить результат утром**

```bash
uv run python contracts/validate.py \
    data/corpus/artificial-intelligence/works.parquet --schema works
uv run python -c "
import duckdb
print(duckdb.sql(\"\"\"SELECT year, count(*) FROM
  'data/corpus/artificial-intelligence/works.parquet'
  GROUP BY year ORDER BY year\"\"\"))"
```
Ожидаемо: сотни тысяч строк, по годам плавный рост без провалов.
Провал в 2026 — нормально, год неполный.

- [ ] **Шаг 4: выложить в Releases и закоммитить докачку**

```bash
gh release create corpus-artificial-intelligence \
  data/corpus/artificial-intelligence/works.parquet \
  --title "Корпус: ИИ, 2015-2026" --notes "Собран $(date +%F)"
git add ingest/harvest.py
git commit -m "Докачка корпуса: повторный запуск продолжает с места обрыва"
```

---

## Task K-05: Эмбеддинги

**Файлы:**
- Создать: `semantic/embed.py`
- Тест: `semantic/test_embed.py`

**Интерфейсы:**
- Отдаёт: `build_texts(works: list[dict]) -> list[str]`, `embed_texts(texts, model_name, device, batch_size) -> np.ndarray` формы `(N, 1024)`, `float32`, L2-нормированные

- [ ] **Шаг 1: падающий тест**

Тест не грузит модель — проверяет подготовку текстов и формат результата.

```python
# semantic/test_embed.py
import numpy as np

from semantic.embed import build_texts, нормализовать


def test_текст_склеивается_из_названия_и_абстракта():
    works = [{"title": "PINN", "abstract": "Мы решаем PDE"},
             {"title": "GAN", "abstract": None}]
    assert build_texts(works) == ["passage: PINN. Мы решаем PDE", "passage: GAN"]


def test_эмбеддинги_нормируются_в_единицу():
    v = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
    n = нормализовать(v)
    assert n.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(n, axis=1), [1.0, 1.0], atol=1e-6)
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest semantic/test_embed.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'semantic.embed'`

- [ ] **Шаг 3: реализация**

```python
# semantic/embed.py
"""Эмбеддинги документов.

Модель зафиксирована: intfloat/multilingual-e5-large. Русский и английский
в одном пространстве — аналитик банка пишет запрос по-русски, корпус английский.
e5 требует префиксы: документы кодируются как "passage: ...", запросы как "query: ...".
Без префикса качество заметно падает — это не косметика.
"""
import numpy as np

МОДЕЛЬ = "intfloat/multilingual-e5-large"
РАЗМЕРНОСТЬ = 1024


def build_texts(works: list[dict]) -> list[str]:
    out = []
    for w in works:
        текст = w["title"]
        if w.get("abstract"):
            текст = f"{текст}. {w['abstract']}"
        out.append("passage: " + текст[:2000])
    return out


def нормализовать(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32)
    длины = np.linalg.norm(v, axis=1, keepdims=True)
    длины[длины == 0] = 1.0
    return (v / длины).astype(np.float32)


def embed_texts(texts: list[str], *, model_name: str = МОДЕЛЬ,
                device: str = "cuda", batch_size: int = 64) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_name, device=device)
    v = m.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                 convert_to_numpy=True, show_progress_bar=True)
    return нормализовать(v)
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest semantic/test_embed.py -v`
Ожидаемо: 2 passed

- [ ] **Шаг 5: замерить скорость на 3070**

```bash
uv run python -c "
import time, duckdb
from semantic.embed import build_texts, embed_texts
works = duckdb.sql(\"SELECT title, abstract FROM 'data/index/golden/works.parquet' LIMIT 2000\").df().to_dict('records')
t = time.time(); v = embed_texts(build_texts(works)); dt = time.time() - t
print(f'{v.shape}, {len(works)/dt:.0f} документов/с')"
```

Записать цифру в чат: от неё зависит, сколько доменов мы успеем проиндексировать.
Если ловишь OOM — уменьшай `batch_size` до 32 или 16, модель не меняй.

- [ ] **Шаг 6: коммит**

```bash
git add semantic/embed.py semantic/test_embed.py
git commit -m "Эмбеддинги документов на multilingual-e5-large"
```

---

## Task K-06: Кластеризация и названия кластеров

**Файлы:**
- Создать: `semantic/cluster.py`
- Тест: `semantic/test_cluster.py`

**Интерфейсы:**
- Отдаёт: `reduce_and_cluster(emb: np.ndarray, min_cluster_size: int = 25) -> np.ndarray` (метки, `-1` = шум); `label_clusters(texts: list[str], labels: np.ndarray, top_n: int = 10) -> dict[int, list[str]]`

- [ ] **Шаг 1: падающий тест**

Тест на c-TF-IDF — он детерминирован и проверяем без GPU.

```python
# semantic/test_cluster.py
import numpy as np

from semantic.cluster import label_clusters


def test_названия_кластеров_отражают_их_содержание():
    texts = ["diffusion model image", "diffusion model sampling",
             "federated learning privacy", "federated learning devices"]
    labels = np.array([0, 0, 1, 1])
    имена = label_clusters(texts, labels, top_n=2)
    assert "diffusion" in имена[0]
    assert "federated" in имена[1]


def test_шум_не_получает_названия():
    texts = ["a b", "c d"]
    labels = np.array([-1, -1])
    assert label_clusters(texts, labels) == {}
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest semantic/test_cluster.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'semantic.cluster'`

- [ ] **Шаг 3: реализация**

```python
# semantic/cluster.py
"""Тематические кластеры.

Зачем кластеры, а не только термины: у зарождающегося тренда часто ещё нет
устоявшегося названия — это следует прямо из определения. Кластер ловит тему
по смыслу, даже когда авторы называют её пятью разными словами.

random_state=42 обязателен: воспроизводимость прогона — часть нашего питча.
"""
import numpy as np

СИД = 42


def reduce_and_cluster(emb: np.ndarray, min_cluster_size: int = 25,
                       min_samples: int = 5) -> np.ndarray:
    """UMAP до 5 измерений, затем HDBSCAN. Возвращает метки, -1 = шум."""
    import hdbscan
    import umap

    сжатые = umap.UMAP(n_neighbors=15, n_components=5, min_dist=0.0,
                       metric="cosine", random_state=СИД).fit_transform(emb)
    return hdbscan.HDBSCAN(min_cluster_size=min_cluster_size,
                           min_samples=min_samples, metric="euclidean",
                           cluster_selection_method="eom").fit_predict(сжатые)


def label_clusters(texts: list[str], labels: np.ndarray,
                   top_n: int = 10) -> dict[int, list[str]]:
    """c-TF-IDF: «документом» считается склейка всех текстов кластера.

    Слово важно для кластера, если внутри него встречается часто, а в остальных
    кластерах — редко. Обычный TF-IDF по отдельным документам этого не даёт.
    """
    from sklearn.feature_extraction.text import CountVectorizer

    уникальные = sorted({int(c) for c in labels if c != -1})
    if not уникальные:
        return {}

    склейки = [" ".join(t for t, c in zip(texts, labels, strict=True) if c == k)
               for k in уникальные]
    vec = CountVectorizer(stop_words="english", min_df=1, ngram_range=(1, 2))
    X = vec.fit_transform(склейки).toarray().astype(np.float64)
    слова = np.array(vec.get_feature_names_out())

    tf = X / np.maximum(X.sum(axis=1, keepdims=True), 1)
    в_скольких = (X > 0).sum(axis=0)
    idf = np.log(1 + len(уникальные) / np.maximum(в_скольких, 1))
    ctfidf = tf * idf

    out = {}
    for i, k in enumerate(уникальные):
        топ = np.argsort(ctfidf[i])[::-1][:top_n]
        out[k] = [w for w in слова[топ] if ctfidf[i][слова.tolist().index(w)] > 0]
    return out
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest semantic/test_cluster.py -v`
Ожидаемо: 2 passed

- [ ] **Шаг 5: подобрать min_cluster_size**

```bash
uv run python -c "
import numpy as np, collections
from semantic.cluster import reduce_and_cluster
emb = np.load('data/index/golden/embeddings.npy')
for m in (10, 25, 50):
    l = reduce_and_cluster(emb, min_cluster_size=m)
    c = collections.Counter(l)
    print(f'min_cluster_size={m}: кластеров {len([k for k in c if k!=-1])}, шум {c[-1]/len(l):.0%}')"
```

Что ищем: слишком большой — слабые сигналы сливаются с мейнстримом; слишком
маленький — тысячи мусорных кластеров. Показать вывод Антону, решение общее.

- [ ] **Шаг 6: коммит**

```bash
git add semantic/cluster.py semantic/test_cluster.py
git commit -m "Кластеризация UMAP+HDBSCAN, названия через c-TF-IDF"
```

---

## Task K-07: Кандидаты-термины и технологический фильтр

**Файлы:**
- Создать: `semantic/terms.py`, `semantic/techfilter.py`
- Тест: `semantic/test_terms.py`, `semantic/test_techfilter.py`

**Интерфейсы:**
- Отдаёт: `extract_terms(titles: list[str], min_docs: int = 30) -> dict[str, int]`
- Отдаёт: `is_technology(term: str) -> bool`

- [ ] **Шаг 1: падающие тесты**

```python
# semantic/test_terms.py
from semantic.terms import extract_terms, ngrams


def test_нграммы_не_начинаются_и_не_кончаются_стоп_словом():
    assert "the model" not in list(ngrams("the model of learning"))
    assert "model of" not in list(ngrams("the model of learning"))


def test_редкие_термины_отсекаются_порогом():
    titles = ["physics informed neural networks"] * 5 + ["rare thing here"]
    assert "physics informed" in extract_terms(titles, min_docs=5)
    assert "rare thing" not in extract_terms(titles, min_docs=5)
```

```python
# semantic/test_techfilter.py
from semantic.techfilter import is_technology


def test_события_и_болезни_не_технологии():
    assert not is_technology("covid-19 pandemic")
    assert not is_technology("breast cancer")
    assert not is_technology("united states")


def test_технологии_проходят():
    assert is_technology("physics-informed neural network")
    assert is_technology("federated learning")
    assert is_technology("state space model")
```

- [ ] **Шаг 2: убедиться, что падают**

Запустить: `uv run pytest semantic/test_terms.py semantic/test_techfilter.py -v`
Ожидаемо: `ModuleNotFoundError`

- [ ] **Шаг 3: реализация terms.py**

Логику `ngrams` взять из `spikes/openalex_probe.py:143-155` без изменений —
она проверена. Отличие одно и принципиальное: порог `min_docs` теперь в
десятках документов от **полного корпуса**, а не «8 из 2500». Именно старый
порог и делал отбор частотным, то есть находил мейнстрим.

```python
# semantic/terms.py
"""Кандидаты-термины: устойчивые n-граммы из заголовков полного корпуса."""
import re
from collections import Counter
from collections.abc import Iterator

СТОП = set("""a an the of for and or in on to with by from using based via as at is are was were be been
this that these those we our their its it his her they he she you your not no non can could may might
new novel study studies research analysis approach method methods model models system systems
paper article review survey towards toward use uses used case cases results result data
between during under over about into through than then them us all any each more most other others
such which who whom whose what when where why how have has had do does did but if than so
one two three first second third high low large small good better best big
application applications framework technique techniques design development evaluation performance
comparison comparative effect effects impact role state art overview introduction chapter
""".split())

ТОКЕН = re.compile(r"[a-z][a-z0-9\-\+]{1,}")


def ngrams(title: str, n_min: int = 2, n_max: int = 4) -> Iterator[str]:
    toks = ТОКЕН.findall(title.lower())
    for n in range(n_min, n_max + 1):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in СТОП or g[-1] in СТОП:
                continue
            if sum(1 for t in g if t in СТОП) > (n - 2):
                continue
            if all(len(t) <= 2 for t in g):
                continue
            yield " ".join(g)


def extract_terms(titles: list[str], min_docs: int = 30) -> dict[str, int]:
    """Термин -> в скольких заголовках встретился. Порог считаем от полного корпуса."""
    счётчик = Counter()
    for t in titles:
        счётчик.update(set(ngrams(t)))
    return {g: c for g, c in счётчик.items() if c >= min_docs}
```

- [ ] **Шаг 4: реализация techfilter.py**

Зачем: в бэктесте первое место занял `covid-19 pandemic` — это событие, а не
технология. Идеального решения нет, нужно достаточно хорошее.

```python
# semantic/techfilter.py
"""Отсев нетехнологических кандидатов.

В бэктесте на срезе 2021 первое место занял 'covid-19 pandemic' — событие,
а не технология. Тут работает связка «чёрный список» + «техно-маркеры»:
термин проходит, если он не в чёрном списке И содержит признак технологии.
"""
import re

ЧЁРНЫЙ_СПИСОК = {
    "covid", "covid-19", "pandemic", "sars", "influenza", "hiv", "cancer",
    "tumor", "diabetes", "patients", "patient", "children", "women", "men",
    "united", "states", "china", "europe", "india", "africa", "university",
    "hospital", "school", "students", "climate", "war", "policy", "government",
}

ТЕХНО_МАРКЕРЫ = {
    "network", "networks", "learning", "model", "models", "algorithm", "algorithms",
    "architecture", "transformer", "encoder", "decoder", "embedding", "embeddings",
    "neural", "quantum", "graph", "attention", "diffusion", "generative", "inference",
    "training", "optimization", "compression", "distillation", "retrieval", "agent",
    "agents", "protocol", "circuit", "sensor", "material", "materials", "device",
    "computing", "processor", "memory", "detection", "segmentation", "prediction",
    "representation", "reinforcement", "supervised", "unsupervised", "federated",
    "transfer", "multimodal", "language", "vision", "robot", "robotic", "simulation",
}

ТОКЕН = re.compile(r"[a-z0-9\-\+]+")


def is_technology(term: str) -> bool:
    токены = set(ТОКЕН.findall(term.lower()))
    if токены & ЧЁРНЫЙ_СПИСОК:
        return False
    расширенные = токены | {ч for t in токены for ч in t.split("-")}
    return bool(расширенные & ТЕХНО_МАРКЕРЫ)
```

- [ ] **Шаг 5: тесты зелёные**

Запустить: `uv run pytest semantic/ -v`
Ожидаемо: все passed

- [ ] **Шаг 6: коммит**

```bash
git add semantic/terms.py semantic/techfilter.py semantic/test_terms.py semantic/test_techfilter.py
git commit -m "Кандидаты-термины из полного корпуса и технологический фильтр"
```

---

## Task K-08: Сборка стадии semantic

**Файлы:**
- Создать: `semantic/build.py`
- Тест: `semantic/test_build.py`

**Интерфейсы:**
- CLI: `python -m semantic.build --domain artificial-intelligence [--min-cluster-size 25]`
- Пишет: `candidates.parquet`, `cand_docs.parquet`, `embeddings.npy`, обновляет `meta.json`

- [ ] **Шаг 1: падающий тест на формат выхода**

```python
# semantic/test_build.py
import numpy as np
import pyarrow.parquet as pq

from contracts.schemas import CANDIDATES, CAND_DOCS
from semantic.build import собрать_кандидатов


def test_кандидаты_и_связи_пишутся_по_схеме(tmp_path):
    works = [{"doc_id": f"openalex:W{i}", "title": "federated learning privacy",
              "abstract": None} for i in range(60)]
    emb = np.zeros((60, 1024), dtype=np.float32)
    emb[:, 0] = 1.0
    собрать_кандидатов(works, emb, "test-domain", tmp_path, min_cluster_size=10)

    assert pq.read_schema(tmp_path / "candidates.parquet").equals(CANDIDATES)
    assert pq.read_schema(tmp_path / "cand_docs.parquet").equals(CAND_DOCS)
    assert np.load(tmp_path / "embeddings.npy").dtype == np.float32
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest semantic/test_build.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'semantic.build'`

- [ ] **Шаг 3: реализация**

```python
# semantic/build.py
"""Стадия semantic: корпус -> кандидаты в тренды.

    python -m semantic.build --domain artificial-intelligence
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from contracts.schemas import CAND_DOCS, CANDIDATES
from semantic.cluster import label_clusters, reduce_and_cluster
from semantic.embed import build_texts, embed_texts
from semantic.techfilter import is_technology
from semantic.terms import extract_terms, ngrams


def собрать_кандидатов(works: list[dict], emb: np.ndarray, domain: str,
                       out_dir: Path, min_cluster_size: int = 25) -> dict:
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(exist_ok=True)

    кандидаты, связи, центроиды = [], [], []

    # --- кластеры: тренд часто ещё не имеет устоявшегося названия
    метки = reduce_and_cluster(emb, min_cluster_size=min_cluster_size)
    имена = label_clusters([w["title"] for w in works], метки)
    for k, слова in имена.items():
        подпись = " ".join(слова[:3])
        if not is_technology(подпись):
            continue
        индексы = [i for i, m in enumerate(метки) if m == k]
        центроид = emb[индексы].mean(axis=0)
        центроид /= max(float(np.linalg.norm(центроид)), 1e-9)
        cand_id = f"c:{domain}:cl{k:04d}"
        кандидаты.append({
            "cand_id": cand_id, "kind": "cluster", "label": подпись,
            "aliases": слова[3:], "top_terms": слова,
            "emb_row": len(центроиды), "n_docs": len(индексы), "domain": domain,
        })
        центроиды.append(центроид)
        for i in индексы:
            связи.append({"cand_id": cand_id, "doc_id": works[i]["doc_id"],
                          "weight": float(emb[i] @ центроид)})

    # --- термины: второй тип кандидата, ловит то, у чего название уже есть
    заголовки = [w["title"] for w in works]
    порог = max(10, len(works) // 500)
    for i, (термин, _) in enumerate(sorted(extract_terms(заголовки, порог).items())):
        if not is_technology(термин):
            continue
        cand_id = f"c:{domain}:tm{i:05d}"
        совпали = [w["doc_id"] for w, t in zip(works, заголовки, strict=True)
                   if термин in set(ngrams(t))]
        кандидаты.append({
            "cand_id": cand_id, "kind": "term", "label": термин,
            "aliases": [], "top_terms": термин.split(), "emb_row": None,
            "n_docs": len(совпали), "domain": domain,
        })
        связи.extend({"cand_id": cand_id, "doc_id": d, "weight": 1.0} for d in совпали)

    pq.write_table(pa.Table.from_pylist(кандидаты, schema=CANDIDATES),
                   out_dir / "candidates.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(связи, schema=CAND_DOCS),
                   out_dir / "cand_docs.parquet", compression="zstd")
    np.save(out_dir / "embeddings.npy",
            np.array(центроиды, dtype=np.float32) if центроиды
            else np.zeros((0, emb.shape[1]), dtype=np.float32))
    return {"n_candidates": len(кандидаты), "n_links": len(связи)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--min-cluster-size", type=int, default=25)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    корпус = Path("data/corpus") / args.domain / "works.parquet"
    if not корпус.exists():
        корпус = Path("data/index/golden/works.parquet")
        sys.stderr.write(f"[внимание] полного корпуса нет, работаю на {корпус}\n")

    works = duckdb.sql(
        f"SELECT doc_id, title, abstract FROM '{корпус}'").df().to_dict("records")
    sys.stderr.write(f"[semantic] {len(works)} документов\n")

    emb = embed_texts(build_texts(works), device=args.device)
    out_dir = Path("data/index") / args.domain
    итог = собрать_кандидатов(works, emb, args.domain, out_dir, args.min_cluster_size)

    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update(итог)
    meta["embedding_model"] = "intfloat/multilingual-e5-large"
    meta.setdefault("stages", {})["semantic"] = dt.date.today().isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    sys.stderr.write(f"[готово] {итог}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest semantic/ -v`
Ожидаемо: все passed

- [ ] **Шаг 5: прогон на золотом снапшоте и валидация**

```bash
uv run python -m semantic.build --domain golden --device cuda
uv run python contracts/validate.py data/index/golden/candidates.parquet --schema candidates
uv run python contracts/validate.py data/index/golden/cand_docs.parquet --schema cand_docs
```

- [ ] **Шаг 6: коммит**

```bash
git add semantic/ data/index/golden/
git commit -m "Стадия semantic: корпус -> кандидаты с эмбеддингами"
```

---

## Task K-09: Ещё два домена

Жюри почти наверняка попросит ввести своё направление. Прогнать конвейер для
«quantum computing» и «biotechnology» — проверка, что ничего не захардкожено под ИИ.

- [ ] **Шаг 1: прогнать**

```bash
for d in "quantum computing" "biotechnology"; do
  uv run python -m ingest.harvest --domain "$d" --years 2015-2026
  uv run python -m semantic.build --domain "$(echo $d | tr ' ' '-')"
done
```

- [ ] **Шаг 2: проверить, что схемы соблюдены**

```bash
for d in quantum-computing biotechnology; do
  uv run python contracts/validate.py data/corpus/$d/works.parquet --schema works
  uv run python contracts/validate.py data/index/$d/candidates.parquet --schema candidates
done
```

- [ ] **Шаг 3: выложить корпуса и написать в чат**

```bash
gh release create corpus-quantum-computing data/corpus/quantum-computing/works.parquet \
  --title "Корпус: квантовые вычисления" --notes "Собран $(date +%F)"
gh release create corpus-biotechnology data/corpus/biotechnology/works.parquet \
  --title "Корпус: биотех" --notes "Собран $(date +%F)"
```

Если что-то захардкожено под ИИ — это вскроется здесь. Чинить сразу.
