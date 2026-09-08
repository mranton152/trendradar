# Фаза 0 — Михаил: продукт (API, фронт, карточки)

> Общие правила и Global Constraints — в [README.md](README.md). Личный бриф — [../../team/PROMPT-mikhail.md](../../team/PROMPT-mikhail.md).

**Цель:** превратить предрассчитанный индекс в сервис, который открывается,
отвечает меньше чем за секунду и убедительно выглядит на защите.

**Архитектура:** API ничего не считает и никуда не ходит по сети — читает parquet
через DuckDB на старте и держит в памяти. Фронт отдельным приложением, до
появления API работает на моках, собранных из золотого снапшота. Генерация
текста карточек — офлайн-стадия, а не рантайм.

**Стек:** FastAPI, Pydantic v2, DuckDB, Next.js 15, TypeScript, Tailwind, Recharts, Ollama.

---

## Task M-01: Слой чтения индекса и /health

**Файлы:**
- Создать: `api/store.py`, `api/main.py`
- Тест: `api/test_store.py`

**Интерфейсы:**
- Отдаёт: `Store(index_root: str | Path)` с методами `domains() -> list[str]`, `trends(domain: str, as_of: int, top: int) -> list[dict]`, `trend(trend_id: str) -> dict | None`, `works(doc_ids: list[str]) -> list[dict]`

- [ ] **Шаг 1: падающий тест**

```python
# api/test_store.py
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from api.store import Store
from contracts.schemas import TRENDS


def _тренд(rank: int, as_of: int = 2026) -> dict:
    return {
        "trend_id": f"t:d:{as_of}:{rank:02d}", "domain": "d", "as_of": as_of,
        "rank": rank, "cand_id": f"c{rank}", "label": f"тренд {rank}",
        "aliases": [], "emergence_score": 1.0 - rank / 100,
        "c_novelty": 0.5, "c_growth": 0.5, "c_accel": 0.5,
        "c_burst": 0.5, "c_diffusion": 0.5, "maturity_pct": 0.3,
        "first_mention": 2019, "takeoff_year": 2022,
        "years": [2022, 2023], "counts": [10, 20],
        "freq_per_million": [1.0, 2.0], "n_docs": 30, "n_countries": 40,
        "n_orgs": None, "n_patents": None, "top_doc_ids": ["openalex:W1"],
        "stage": "emerging", "confidence": "high", "methodology_version": "1.0",
    }


@pytest.fixture
def индекс(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    строки = [_тренд(i) for i in range(1, 4)] + [_тренд(1, as_of=2021)]
    pq.write_table(pa.Table.from_pylist(строки, schema=TRENDS), d / "trends.parquet")
    return tmp_path


def test_домены_находятся_по_наличию_trends(индекс):
    assert Store(индекс).domains() == ["d"]


def test_тренды_фильтруются_по_срезу_и_сортируются(индекс):
    строки = Store(индекс).trends("d", as_of=2026, top=2)
    assert [r["rank"] for r in строки] == [1, 2]
    assert all(r["as_of"] == 2026 for r in строки)


def test_неизвестный_домен_даёт_пустой_список(индекс):
    assert Store(индекс).trends("нет-такого", as_of=2026, top=15) == []
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest api/test_store.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'api.store'`

- [ ] **Шаг 3: реализация**

```python
# api/store.py
"""Чтение предрассчитанного индекса.

API не считает ничего и не ходит в сеть: демо обязано работать в самолётном
режиме. Всё, что нужно, лежит в parquet и читается SQL-запросом по файлу.
"""
from functools import lru_cache
from pathlib import Path

import duckdb


class Store:
    def __init__(self, index_root: str | Path = "data/index"):
        self.root = Path(index_root)
        self.con = duckdb.connect(database=":memory:")

    def domains(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir()
                      if (p / "trends.parquet").exists())

    def _путь(self, domain: str) -> Path | None:
        p = self.root / domain / "trends.parquet"
        return p if p.exists() else None

    def trends(self, domain: str, as_of: int, top: int = 15) -> list[dict]:
        p = self._путь(domain)
        if p is None:
            return []
        return self.con.sql(f"""
            SELECT * FROM '{p}' WHERE as_of = {int(as_of)}
            ORDER BY rank LIMIT {int(top)}
        """).df().to_dict("records")

    def trend(self, trend_id: str) -> dict | None:
        domain = trend_id.split(":")[1] if trend_id.count(":") >= 2 else None
        p = self._путь(domain) if domain else None
        if p is None:
            return None
        строки = self.con.sql(
            f"SELECT * FROM '{p}' WHERE trend_id = '{trend_id}'").df().to_dict("records")
        return строки[0] if строки else None

    def works(self, domain: str, doc_ids: list[str]) -> list[dict]:
        """Документы по идентификаторам — для списка источников в карточке."""
        корпус = self.root.parent / "corpus" / domain / "works.parquet"
        if not корпус.exists():
            корпус = self.root / domain / "works.parquet"
        if not корпус.exists() or not doc_ids:
            return []
        список = ", ".join(f"'{d}'" for d in doc_ids)
        return self.con.sql(f"""
            SELECT doc_id, title, url, year, doc_type, cited_by
            FROM '{корпус}' WHERE doc_id IN ({список})
        """).df().to_dict("records")


@lru_cache(maxsize=1)
def get_store() -> Store:
    return Store()
```

```python
# api/main.py
"""Точка входа. Индекс читается лениво и кэшируется, ответ укладывается в секунду."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.store import get_store

log = logging.getLogger("trendradar")
app = FastAPI(title="TrendRadar API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.on_event("startup")
def показать_индекс() -> None:
    домены = get_store().domains()
    if домены:
        log.warning("индекс: %s", ", ".join(домены))
    else:
        log.warning("индекс пуст — работаем на моках, ждём data/index/")


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "indexed_domains": get_store().domains(),
            "offline_mode": True}
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest api/test_store.py -v`
Ожидаемо: 3 passed

- [ ] **Шаг 5: проверить руками**

```bash
uv run uvicorn api.main:app --port 8000 &
curl -s localhost:8000/api/v1/health
```
Ожидаемо: `{"status":"ok","indexed_domains":["golden"],"offline_mode":true}`

- [ ] **Шаг 6: коммит**

```bash
git add api/store.py api/main.py api/test_store.py
git commit -m "API: чтение индекса через DuckDB и эндпойнт health"
```

---

## Task M-02: Эндпойнты трендов

**Файлы:**
- Создать: `api/models.py`, `api/routes/trends.py`, `api/routes/__init__.py`
- Изменить: `api/main.py` (подключить роутер)
- Тест: `api/test_trends.py`

**Интерфейсы:**
- `POST /api/v1/trends` тело `{domain, top_n=15, as_of=2026}` → `TrendsResponse`
- `GET /api/v1/trends/{trend_id}` → `Trend`
- `POST /api/v1/domains/resolve` тело `{query}` → `{resolved, in_index, alternatives}`

- [ ] **Шаг 1: падающий тест**

```python
# api/test_trends.py
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_топ_отдаётся_по_контракту():
    r = client.post("/api/v1/trends", json={"domain": "golden", "top_n": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == 2026
    assert len(body["trends"]) <= 3
    первый = body["trends"][0]
    for поле in ("trend_id", "rank", "title", "emergence_score",
                 "components", "evidence", "stage", "confidence"):
        assert поле in первый
    assert {"novelty", "growth", "accel", "burst", "diffusion"} == set(первый["components"])
    assert первый["evidence"]["series"][0].keys() >= {"year", "count"}


def test_неизвестный_домен_даёт_понятную_ошибку():
    r = client.post("/api/v1/trends", json={"domain": "нет-такого"})
    assert r.status_code == 404
    assert "не найден" in r.json()["detail"]
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest api/test_trends.py -v`
Ожидаемо: 404 на несуществующем маршруте либо `ModuleNotFoundError`

- [ ] **Шаг 3: схемы ответа**

```python
# api/models.py
"""Схемы ответа. Соответствуют contracts/api.openapi.yaml — это контракт с фронтом."""
from pydantic import BaseModel, Field


class Components(BaseModel):
    novelty: float
    growth: float
    accel: float
    burst: float
    diffusion: float


class SeriesPoint(BaseModel):
    year: int
    count: int
    freq_per_million: float


class Evidence(BaseModel):
    first_mention: int | None = None
    takeoff_year: int | None = None
    series: list[SeriesPoint]
    n_docs: int
    n_countries: int
    n_orgs: int | None = None
    n_patents: int | None = None


class Source(BaseModel):
    doc_id: str
    title: str
    url: str
    year: int
    type: str


class Trend(BaseModel):
    trend_id: str
    rank: int
    title: str
    label_en: str
    aliases: list[str] = []
    emergence_score: float
    components: Components
    evidence: Evidence
    sources: list[Source] = []
    stage: str
    confidence: str


class TrendsRequest(BaseModel):
    domain: str
    top_n: int = Field(default=15, ge=1, le=50)
    as_of: int = 2026


class TrendsResponse(BaseModel):
    domain: dict
    as_of: int
    methodology_version: str
    trends: list[Trend]
```

- [ ] **Шаг 4: роутер**

```python
# api/routes/trends.py
"""Эндпойнты выдачи трендов."""
import re

from fastapi import APIRouter, HTTPException

from api.models import (Components, Evidence, SeriesPoint, Source, Trend,
                        TrendsRequest, TrendsResponse)
from api.store import get_store

router = APIRouter(prefix="/api/v1")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _в_модель(row: dict, store, domain: str) -> Trend:
    документы = {d["doc_id"]: d for d in store.works(domain, list(row["top_doc_ids"]))}
    return Trend(
        trend_id=row["trend_id"], rank=int(row["rank"]),
        title=row["label"], label_en=row["label"],
        aliases=list(row["aliases"] or []),
        emergence_score=float(row["emergence_score"]),
        components=Components(novelty=row["c_novelty"], growth=row["c_growth"],
                              accel=row["c_accel"], burst=row["c_burst"],
                              diffusion=row["c_diffusion"]),
        evidence=Evidence(
            first_mention=row["first_mention"], takeoff_year=row["takeoff_year"],
            series=[SeriesPoint(year=int(y), count=int(c), freq_per_million=float(f))
                    for y, c, f in zip(row["years"], row["counts"],
                                       row["freq_per_million"], strict=True)],
            n_docs=int(row["n_docs"]), n_countries=int(row["n_countries"]),
            n_orgs=row["n_orgs"], n_patents=row["n_patents"]),
        sources=[Source(doc_id=d["doc_id"], title=d["title"], url=d["url"],
                        year=int(d["year"]), type=d["doc_type"])
                 for d in документы.values()],
        stage=row["stage"], confidence=row["confidence"])


@router.post("/domains/resolve")
def resolve(body: dict) -> dict:
    store = get_store()
    домены = store.domains()
    искомый = _slug(body.get("query", ""))
    точное = искомый if искомый in домены else None
    близкие = [d for d in домены if искомый and (искомый in d or d in искомый)]
    return {"resolved": точное or (близкие[0] if близкие else None),
            "in_index": точное is not None,
            "alternatives": [d for d in домены if d != точное]}


@router.post("/trends", response_model=TrendsResponse)
def trends(req: TrendsRequest) -> TrendsResponse:
    store = get_store()
    домен = req.domain if req.domain in store.domains() else _slug(req.domain)
    строки = store.trends(домен, req.as_of, req.top_n)
    if not строки:
        доступно = ", ".join(store.domains()) or "индекс пуст"
        raise HTTPException(404, f"домен '{req.domain}' не найден. Есть: {доступно}")
    return TrendsResponse(
        domain={"query": req.domain, "resolved": домен},
        as_of=req.as_of,
        methodology_version=строки[0]["methodology_version"],
        trends=[_в_модель(r, store, домен) for r in строки])


@router.get("/trends/{trend_id}", response_model=Trend)
def trend(trend_id: str) -> Trend:
    store = get_store()
    row = store.trend(trend_id)
    if row is None:
        raise HTTPException(404, f"тренд '{trend_id}' не найден")
    return _в_модель(row, store, row["domain"])
```

```python
# api/routes/__init__.py
"""Роутеры API."""
```

В `api/main.py` добавить после создания `app`:

```python
from api.routes import trends as trends_routes  # noqa: E402

app.include_router(trends_routes.router)
```

- [ ] **Шаг 5: тесты зелёные**

Запустить: `uv run pytest api/ -v`
Ожидаемо: все passed

- [ ] **Шаг 6: коммит**

```bash
git add api/
git commit -m "API: эндпойнты трендов, карточки и резолва домена"
```

---

## Task M-03: Каркас фронта и моки

Не жди бэкенд: моки собираются из золотого снапшота, фронт разрабатывается сразу.

**Файлы:**
- Создать: `web/package.json`, `web/app/layout.tsx`, `web/app/page.tsx`, `web/lib/api.ts`, `web/mocks/trends.json`, `web/scripts/make-mocks.py`

- [ ] **Шаг 1: инициализировать проект**

```bash
cd web && npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --no-eslint --use-npm --yes
npm i recharts
```

- [ ] **Шаг 2: генератор моков**

```python
# web/scripts/make-mocks.py
"""Моки для фронта из золотого снапшота: фронт не ждёт бэкенд.

    uv run python web/scripts/make-mocks.py
"""
import json
from pathlib import Path

import duckdb

ИНДЕКС = Path("data/index/golden/trends.parquet")
ВЫХОД = Path("web/mocks/trends.json")


def main() -> None:
    if not ИНДЕКС.exists():
        raise SystemExit(f"нет {ИНДЕКС} — ждём золотой снапшот от Константина")
    строки = duckdb.sql(f"SELECT * FROM '{ИНДЕКС}' ORDER BY rank").df().to_dict("records")
    тренды = [{
        "trend_id": r["trend_id"], "rank": int(r["rank"]), "title": r["label"],
        "label_en": r["label"], "aliases": list(r["aliases"] or []),
        "emergence_score": float(r["emergence_score"]),
        "components": {"novelty": float(r["c_novelty"]), "growth": float(r["c_growth"]),
                       "accel": float(r["c_accel"]), "burst": float(r["c_burst"]),
                       "diffusion": float(r["c_diffusion"])},
        "evidence": {
            "first_mention": r["first_mention"], "takeoff_year": r["takeoff_year"],
            "series": [{"year": int(y), "count": int(c), "freq_per_million": float(f)}
                       for y, c, f in zip(r["years"], r["counts"],
                                          r["freq_per_million"], strict=True)],
            "n_docs": int(r["n_docs"]), "n_countries": int(r["n_countries"])},
        "sources": [], "stage": r["stage"], "confidence": r["confidence"],
    } for r in строки]

    ВЫХОД.parent.mkdir(parents=True, exist_ok=True)
    ВЫХОД.write_text(json.dumps(
        {"domain": {"query": "технологии в ИИ", "resolved": "golden"},
         "as_of": 2026, "methodology_version": "1.0", "trends": тренды},
        ensure_ascii=False, indent=2))
    print(f"{len(тренды)} трендов -> {ВЫХОД}")


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 3: слой доступа к данным**

Одна переменная окружения переключает моки на живой API.

```typescript
// web/lib/api.ts
// Пока API не поднят, фронт живёт на моках. Переключение — одной переменной.
import mock from "@/mocks/trends.json";

export type Trend = {
  trend_id: string; rank: number; title: string; label_en: string;
  aliases: string[]; emergence_score: number;
  components: { novelty: number; growth: number; accel: number; burst: number; diffusion: number };
  evidence: {
    first_mention: number | null; takeoff_year: number | null;
    series: { year: number; count: number; freq_per_million: number }[];
    n_docs: number; n_countries: number;
  };
  sources: { doc_id: string; title: string; url: string; year: number; type: string }[];
  stage: string; confidence: string;
};

export type TrendsResponse = {
  domain: { query: string; resolved: string };
  as_of: number; methodology_version: string; trends: Trend[];
};

const BASE = process.env.NEXT_PUBLIC_API_URL;

export async function fetchTrends(domain: string, asOf = 2026, topN = 15): Promise<TrendsResponse> {
  if (!BASE) return mock as TrendsResponse;
  const r = await fetch(`${BASE}/api/v1/trends`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, as_of: asOf, top_n: topN }),
    cache: "no-store",
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? "ошибка запроса");
  return r.json();
}
```

- [ ] **Шаг 4: страница ввода**

```tsx
// web/app/page.tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Home() {
  const [q, setQ] = useState("технологии в ИИ");
  const router = useRouter();
  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-3xl font-semibold tracking-tight">TrendRadar</h1>
      <p className="mt-2 text-neutral-600">
        Зарождающиеся технологические тренды: те, что ещё не стали массовыми.
      </p>
      <form
        className="mt-8 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          router.push(`/trends/${encodeURIComponent(q)}`);
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="технологическое направление"
          className="flex-1 rounded-md border border-neutral-300 px-4 py-2.5 outline-none focus:border-neutral-900"
        />
        <button className="rounded-md bg-neutral-900 px-5 py-2.5 text-white">
          Найти
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Шаг 5: проверить, что поднимается**

```bash
uv run python web/scripts/make-mocks.py
cd web && npm run dev
```
Открыть http://localhost:3000 — форма отображается, ввод работает.

- [ ] **Шаг 6: коммит**

```bash
git add web/
git commit -m "Каркас фронта на Next.js и генератор моков из снапшота"
```

---

## Task M-04: Список трендов и карточка с графиком

Главное свойство интерфейса: **любое число кликабельно и ведёт к первоисточнику.**
Это то, ради чего всё делается, и именно это спросит жюри.

**Файлы:**
- Создать: `web/app/trends/[domain]/page.tsx`, `web/app/trends/[domain]/[id]/page.tsx`, `web/components/TrendCard.tsx`, `web/components/TimeSeriesChart.tsx`, `web/components/ScoreBreakdown.tsx`

- [ ] **Шаг 1: карточка в списке**

```tsx
// web/components/TrendCard.tsx
import Link from "next/link";
import type { Trend } from "@/lib/api";

const СТАДИИ: Record<string, string> = {
  emerging: "зарождение",
  early_growth: "ранний рост",
  scaling: "масштабирование",
};

const УВЕРЕННОСТЬ: Record<string, string> = {
  high: "высокая уверенность",
  medium: "средняя уверенность",
  low: "мало данных",
};

export function TrendCard({ trend, domain }: { trend: Trend; domain: string }) {
  return (
    <Link
      href={`/trends/${encodeURIComponent(domain)}/${encodeURIComponent(trend.trend_id)}`}
      className="block rounded-lg border border-neutral-200 p-4 transition hover:border-neutral-900"
    >
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-sm tabular-nums text-neutral-400">#{trend.rank}</span>
        <h2 className="flex-1 font-medium">{trend.title}</h2>
        <span className="tabular-nums text-sm text-neutral-500">
          {trend.emergence_score.toFixed(3)}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-600">
        <span>взлёт {trend.evidence.takeoff_year ?? "—"}</span>
        <span>{trend.evidence.n_docs} публикаций</span>
        <span>{trend.evidence.n_countries} стран</span>
        <span className="text-neutral-400">{СТАДИИ[trend.stage] ?? trend.stage}</span>
        {trend.confidence === "low" && (
          <span className="text-amber-700">{УВЕРЕННОСТЬ.low}</span>
        )}
      </div>
    </Link>
  );
}
```

- [ ] **Шаг 2: график динамики**

```tsx
// web/components/TimeSeriesChart.tsx
"use client";
import {
  CartesianGrid, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Точка = { year: number; count: number; freq_per_million: number };

export function TimeSeriesChart({
  series, takeoff,
}: { series: Точка[]; takeoff: number | null }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
        <XAxis dataKey="year" tick={{ fontSize: 12 }} />
        <YAxis tick={{ fontSize: 12 }} width={44} />
        <Tooltip
          formatter={(v: number) => [`${v} публикаций`, ""]}
          labelFormatter={(y) => `${y} год`}
        />
        {takeoff && (
          <ReferenceLine
            x={takeoff}
            stroke="#b45309"
            label={{ value: "взлёт", position: "top", fontSize: 11 }}
          />
        )}
        <Line type="monotone" dataKey="count" stroke="#171717" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Шаг 3: разбор скора**

```tsx
// web/components/ScoreBreakdown.tsx
const ПОДПИСИ: Record<string, string> = {
  novelty: "новизна",
  growth: "рост",
  accel: "ускорение",
  burst: "всплеск",
  diffusion: "распространение",
};

export function ScoreBreakdown({ components }: { components: Record<string, number> }) {
  return (
    <div className="space-y-2">
      {Object.entries(components).map(([k, v]) => (
        <div key={k} className="flex items-center gap-3 text-sm">
          <span className="w-32 text-neutral-600">{ПОДПИСИ[k] ?? k}</span>
          <div className="h-2 flex-1 rounded bg-neutral-100">
            <div className="h-2 rounded bg-neutral-900" style={{ width: `${v * 100}%` }} />
          </div>
          <span className="w-16 text-right tabular-nums text-neutral-500">
            топ {Math.round((1 - v) * 100)}%
          </span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Шаг 4: страница списка**

```tsx
// web/app/trends/[domain]/page.tsx
import { TrendCard } from "@/components/TrendCard";
import { fetchTrends } from "@/lib/api";

export default async function TrendsPage({
  params, searchParams,
}: {
  params: Promise<{ domain: string }>;
  searchParams: Promise<{ as_of?: string }>;
}) {
  const { domain } = await params;
  const { as_of } = await searchParams;
  const asOf = Number(as_of ?? 2026);
  const data = await fetchTrends(decodeURIComponent(domain), asOf);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="text-2xl font-semibold">
        ТОП-{data.trends.length}: {data.domain.query}
      </h1>
      <p className="mt-1 text-sm text-neutral-500">
        срез {data.as_of} · методология {data.methodology_version}
      </p>
      <div className="mt-6 space-y-3">
        {data.trends.map((t) => (
          <TrendCard key={t.trend_id} trend={t} domain={domain} />
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Шаг 5: страница карточки**

```tsx
// web/app/trends/[domain]/[id]/page.tsx
import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { TimeSeriesChart } from "@/components/TimeSeriesChart";
import { fetchTrends } from "@/lib/api";

export default async function TrendPage({
  params,
}: { params: Promise<{ domain: string; id: string }> }) {
  const { domain, id } = await params;
  const data = await fetchTrends(decodeURIComponent(domain));
  const t = data.trends.find((x) => x.trend_id === decodeURIComponent(id));
  if (!t) return <main className="p-12">Тренд не найден</main>;

  return (
    <main className="mx-auto max-w-3xl space-y-8 px-6 py-12">
      <header>
        <h1 className="text-2xl font-semibold">{t.title}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Emergence Score {t.emergence_score.toFixed(3)} · взлёт{" "}
          {t.evidence.takeoff_year ?? "—"} · первое упоминание{" "}
          {t.evidence.first_mention ?? "—"}
        </p>
      </header>

      <section>
        <h2 className="mb-2 text-sm font-medium text-neutral-500">Динамика публикаций</h2>
        <TimeSeriesChart series={t.evidence.series} takeoff={t.evidence.takeoff_year} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-neutral-500">Из чего сложился скор</h2>
        <ScoreBreakdown components={t.components} />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium text-neutral-500">
          Источники ({t.sources.length})
        </h2>
        <ul className="space-y-1.5 text-sm">
          {t.sources.map((s) => (
            <li key={s.doc_id}>
              <a href={s.url} target="_blank" rel="noreferrer"
                 className="text-neutral-900 underline underline-offset-2 hover:text-amber-700">
                {s.title}
              </a>
              <span className="ml-2 text-neutral-400">{s.year}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
```

- [ ] **Шаг 6: проверить в браузере и снять скриншот**

```bash
cd web && npm run dev
```
Пройти путь: ввод → список → карточка → клик по источнику. Скриншот в
`docs/screenshots/` — пойдёт в презентацию.

- [ ] **Шаг 7: коммит**

```bash
git add web/
git commit -m "Фронт: список трендов, карточка, график динамики, разбор скора"
```

---

## Task M-05: RAG-генерация карточек

Единственное место в системе, где работает LLM. Правило жёсткое: утверждение,
чьи `doc_ids` не подтверждаются входными документами, **выбрасывается**, а не
помечается. Иначе на защите вопрос «откуда это?» останется без ответа.

**Файлы:**
- Создать: `cards/llm.py`, `cards/prompt.py`, `cards/verify.py`, `cards/build.py`
- Тест: `cards/test_verify.py`

**Интерфейсы:**
- Отдаёт: `проверить_цитаты(карточка: dict, разрешённые: set[str]) -> tuple[dict, float]` — очищенная карточка и `citation_coverage`
- Отдаёт: `LLM(backend, model)` с методом `json(prompt: str, schema: dict) -> dict`
- CLI: `python -m cards.build --domain golden --as-of 2026`

- [ ] **Шаг 1: падающий тест**

```python
# cards/test_verify.py
from cards.verify import проверить_цитаты

КАРТОЧКА = {
    "problem": "Дорого считать", "problem_docs": ["openalex:W1"],
    "advantage": "Быстрее", "advantage_docs": ["openalex:W404"],
    "case_text": "Компания X", "case_docs": ["openalex:W2"],
}


def test_утверждение_без_подтверждённого_источника_выбрасывается():
    очищ, покрытие = проверить_цитаты(КАРТОЧКА, {"openalex:W1", "openalex:W2"})
    assert очищ["problem"] == "Дорого считать"
    assert очищ["advantage"] == ""          # W404 нет во входных документах
    assert очищ["advantage_docs"] == []
    assert покрытие == 2 / 3


def test_полностью_подтверждённая_карточка_даёт_единицу():
    _, покрытие = проверить_цитаты(КАРТОЧКА, {"openalex:W1", "openalex:W2", "openalex:W404"})
    assert покрытие == 1.0


def test_пустые_ссылки_считаются_неподтверждёнными():
    к = {**КАРТОЧКА, "problem_docs": []}
    очищ, покрытие = проверить_цитаты(к, {"openalex:W2"})
    assert очищ["problem"] == ""
    assert покрытие < 1.0
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest cards/test_verify.py -v`
Ожидаемо: `ModuleNotFoundError: No module named 'cards.verify'`

- [ ] **Шаг 3: проверка цитат**

```python
# cards/verify.py
"""Постобработка выдачи LLM: всё, что не подтверждено документом, выбрасывается.

Метрика citation_coverage — доля утверждений с подтверждённым источником.
Целимся в 1.0 и показываем цифру жюри: это прямой ответ на вопрос
«а это не галлюцинация?».
"""
ПОЛЯ = [("problem", "problem_docs"), ("advantage", "advantage_docs"),
        ("case_text", "case_docs")]


def проверить_цитаты(карточка: dict, разрешённые: set[str]) -> tuple[dict, float]:
    очищенная = dict(карточка)
    подтверждено = 0
    for текст, ссылки in ПОЛЯ:
        живые = [d for d in (карточка.get(ссылки) or []) if d in разрешённые]
        if живые and (карточка.get(текст) or "").strip():
            очищенная[ссылки] = живые
            подтверждено += 1
        else:
            очищенная[текст] = ""
            очищенная[ссылки] = []
    return очищенная, подтверждено / len(ПОЛЯ)
```

- [ ] **Шаг 4: промпт и клиент LLM**

```python
# cards/prompt.py
"""Промпт генерации карточки.

Формулировка «ты не эксперт по теме, ты извлекаешь факты из поданных документов»
даёт заметно меньше выдумок, чем «расскажи про тренд». Модель не должна считать,
что от неё ждут эрудиции.
"""
ШАБЛОН = """Ты не эксперт по теме. Ты извлекаешь факты из поданных документов.

Тренд: {label}
Год взлёта: {takeoff}. Публикаций за окно: {n_docs}. Стран: {n_countries}.

ДОКУМЕНТЫ:
{документы}

Составь карточку тренда СТРОГО по этим документам. Верни только JSON:
{{
  "title_ru": "название тренда по-русски, 2-5 слов",
  "problem": "какую проблему решает, 1-2 предложения",
  "problem_docs": ["doc_id, из которых это следует"],
  "advantage": "какое даёт преимущество, 1-2 предложения",
  "advantage_docs": ["doc_id"],
  "case_type": "research или company",
  "case_name": "название исследования или компании из документов",
  "case_text": "что именно они делают, 1-2 предложения",
  "case_docs": ["doc_id"],
  "fintech_note": "применимость в финансах, или пустая строка если из документов не следует"
}}

Правила:
- Если факта в документах нет — не пиши его. Пустая строка лучше выдумки.
- Каждый doc_id обязан быть из списка выше. Не придумывай идентификаторы.
- Не используй знания вне поданных документов.
"""


def собрать(тренд: dict, документы: list[dict]) -> str:
    строки = "\n".join(
        f"[{d['doc_id']}] ({d['year']}) {d['title']}"
        + (f"\n  {d['abstract'][:400]}" if d.get("abstract") else "")
        for d in документы)
    return ШАБЛОН.format(
        label=тренд["label"], takeoff=тренд.get("takeoff_year"),
        n_docs=тренд["n_docs"], n_countries=тренд["n_countries"], документы=строки)
```

```python
# cards/llm.py
"""Абстракция провайдера модели.

В контуре банка внешние API недоступны — это прямо влияет на оценку решения.
Провайдер меняется переменной LLM_BACKEND, код остаётся тот же.
"""
import json
import os
import re

import httpx


class LLM:
    def __init__(self, backend: str | None = None, model: str | None = None):
        self.backend = backend or os.getenv("LLM_BACKEND", "ollama")
        self.model = model or os.getenv("LLM_MODEL", "qwen2.5:7b")
        self.base = os.getenv("LLM_BASE_URL", "http://localhost:11434")

    def json(self, prompt: str) -> dict:
        текст = self._вызов(prompt)
        try:
            return json.loads(текст)
        except json.JSONDecodeError:
            # модели любят обрамлять JSON пояснениями — достаём первый объект
            m = re.search(r"\{.*\}", текст, re.S)
            if not m:
                raise
            return json.loads(m.group(0))

    def _вызов(self, prompt: str) -> str:
        if self.backend == "ollama":
            r = httpx.post(f"{self.base}/api/generate", timeout=300, json={
                "model": self.model, "prompt": prompt,
                "format": "json", "stream": False})
            r.raise_for_status()
            return r.json()["response"]
        if self.backend == "openai_compatible":
            r = httpx.post(f"{self.base}/v1/chat/completions", timeout=300,
                           headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
                           json={"model": self.model,
                                 "messages": [{"role": "user", "content": prompt}],
                                 "response_format": {"type": "json_object"}})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        raise ValueError(f"неизвестный LLM_BACKEND: {self.backend}")
```

- [ ] **Шаг 5: сборка cards.parquet**

```python
# cards/build.py
"""Стадия cards: тренды -> текстовые карточки с проверенными цитатами.

    python -m cards.build --domain golden --as-of 2026
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cards.llm import LLM
from cards.prompt import собрать
from cards.verify import проверить_цитаты
from contracts.schemas import CARDS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--as-of", type=int, default=2026)
    args = ap.parse_args()

    index_dir = Path("data/index") / args.domain
    корпус = Path("data/corpus") / args.domain / "works.parquet"
    if not корпус.exists():
        корпус = index_dir / "works.parquet"

    тренды = duckdb.sql(f"""
        SELECT * FROM '{index_dir}/trends.parquet'
        WHERE as_of = {args.as_of} ORDER BY rank
    """).df().to_dict("records")

    llm = LLM()
    строки = []
    for t in тренды:
        ids = list(t["top_doc_ids"])
        список = ", ".join(f"'{d}'" for d in ids)
        документы = duckdb.sql(f"""
            SELECT doc_id, title, abstract, year FROM '{корпус}'
            WHERE doc_id IN ({список})
        """).df().to_dict("records")

        сырая = llm.json(собрать(t, документы))
        чистая, покрытие = проверить_цитаты(сырая, {d["doc_id"] for d in документы})
        sys.stderr.write(f"[cards] {t['label'][:40]:<40} покрытие {покрытие:.0%}\n")

        строки.append({
            "trend_id": t["trend_id"],
            "title_ru": чистая.get("title_ru") or t["label"],
            "problem": чистая.get("problem", ""),
            "problem_docs": чистая.get("problem_docs", []),
            "advantage": чистая.get("advantage", ""),
            "advantage_docs": чистая.get("advantage_docs", []),
            "case_type": чистая.get("case_type") or "research",
            "case_name": чистая.get("case_name", ""),
            "case_text": чистая.get("case_text", ""),
            "case_docs": чистая.get("case_docs", []),
            "fintech_note": чистая.get("fintech_note") or None,
            "citation_coverage": float(покрытие),
            "model": f"{llm.backend}:{llm.model}",
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        })

    pq.write_table(pa.Table.from_pylist(строки, schema=CARDS),
                   index_dir / "cards.parquet", compression="zstd")
    среднее = sum(r["citation_coverage"] for r in строки) / max(1, len(строки))
    sys.stderr.write(f"[готово] {len(строки)} карточек, среднее покрытие {среднее:.0%}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 6: тесты и прогон**

```bash
uv run pytest cards/ -v
ollama pull qwen2.5:7b
uv run python -m cards.build --domain golden --as-of 2026
uv run python contracts/validate.py data/index/golden/cards.parquet --schema cards
```
Если среднее покрытие ниже 80% — правь промпт, а не проверку. Ослаблять
проверку цитат нельзя: она и есть наш ответ на вопрос про галлюцинации.

- [ ] **Шаг 7: коммит**

```bash
git add cards/
git commit -m "RAG-генерация карточек с обязательной проверкой цитат"
```

---

## Task M-06: Вкладка «Методология» и переключатель as_of

Вкладка — прямое требование заказчика. Переключатель `as_of` — главный номер демо:
ставим 2021, показываем, что сервис нашёл бы тогда и что из этого выросло.

**Файлы:**
- Создать: `api/routes/methodology.py`, `web/app/methodology/page.tsx`, `web/components/AsOfSwitch.tsx`
- Изменить: `api/main.py`, `web/app/trends/[domain]/page.tsx`

- [ ] **Шаг 1: эндпойнт методологии**

```python
# api/routes/methodology.py
"""Методология в интерфейсе — прямое требование заказчика."""
import json
from pathlib import Path

from fastapi import APIRouter

from core.filters import ПОРОГИ
from core.score import ВЕРСИЯ_МЕТОДОЛОГИИ, ВЕСА

router = APIRouter(prefix="/api/v1")

ОПИСАНИЯ = {
    "novelty": "Новизна: сколько лет прошло с года взлёта — выхода на 10% собственного пика",
    "growth": "Рост: наклон логарифма частоты за пятилетнее окно",
    "accel": "Ускорение: разница наклонов второй и первой половины окна",
    "burst": "Всплеск: во сколько раз последний год превысил базовую линию",
    "diffusion": "Распространение: сколько разных стран публикует по теме",
}


@router.get("/methodology")
def methodology() -> dict:
    отчёт = Path("validation/report.json")
    return {
        "version": ВЕРСИЯ_МЕТОДОЛОГИИ,
        "weights": ВЕСА,
        "descriptions": ОПИСАНИЯ,
        "filters": ПОРОГИ,
        "validation": json.loads(отчёт.read_text()) if отчёт.exists() else None,
    }
```

Подключить в `api/main.py`:

```python
from api.routes import methodology as methodology_routes  # noqa: E402

app.include_router(methodology_routes.router)
```

- [ ] **Шаг 2: переключатель среза**

```tsx
// web/components/AsOfSwitch.tsx
"use client";
import { useRouter, useSearchParams } from "next/navigation";

// Главный номер демо: ставим 2021 и показываем, что сервис нашёл бы тогда.
// Поэтому это заметный переключатель, а не чекбокс в настройках.
export function AsOfSwitch({ domain, current }: { domain: string; current: number }) {
  const router = useRouter();
  const params = useSearchParams();
  const годы = [2021, 2023, 2026];

  return (
    <div className="flex items-center gap-2 rounded-lg border border-neutral-200 p-1">
      <span className="px-2 text-sm text-neutral-500">срез</span>
      {годы.map((y) => (
        <button
          key={y}
          onClick={() => {
            const p = new URLSearchParams(params.toString());
            p.set("as_of", String(y));
            router.push(`/trends/${domain}?${p}`);
          }}
          className={`rounded px-3 py-1.5 text-sm tabular-nums transition ${
            y === current ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"
          }`}
        >
          {y}
        </button>
      ))}
      {current < 2026 && (
        <span className="px-2 text-sm text-amber-700">
          режим бэктеста: что сервис нашёл бы в {current} году
        </span>
      )}
    </div>
  );
}
```

Вставить в `web/app/trends/[domain]/page.tsx` сразу под заголовком:

```tsx
      <div className="mt-4">
        <AsOfSwitch domain={domain} current={asOf} />
      </div>
```

- [ ] **Шаг 3: страница методологии**

```tsx
// web/app/methodology/page.tsx
const BASE = process.env.NEXT_PUBLIC_API_URL;

export default async function MethodologyPage() {
  const data = BASE
    ? await fetch(`${BASE}/api/v1/methodology`, { cache: "no-store" }).then((r) => r.json())
    : { version: "1.0", weights: {}, descriptions: {}, filters: {}, validation: null };

  return (
    <main className="mx-auto max-w-3xl space-y-8 px-6 py-12">
      <h1 className="text-2xl font-semibold">Методология, версия {data.version}</h1>

      <section>
        <h2 className="mb-3 text-sm font-medium text-neutral-500">Компоненты и веса</h2>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(data.weights as Record<string, number>).map(([k, v]) => (
              <tr key={k} className="border-b border-neutral-100">
                <td className="py-2 pr-4 tabular-nums text-neutral-500">{v.toFixed(2)}</td>
                <td className="py-2">{data.descriptions?.[k] ?? k}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium text-neutral-500">
          Фильтры против ложных сигналов
        </h2>
        <ul className="space-y-1 text-sm text-neutral-700">
          {Object.entries(data.filters as Record<string, number>).map(([k, v]) => (
            <li key={k}>
              <code className="text-neutral-500">{k}</code> = {v}
            </li>
          ))}
        </ul>
      </section>

      {data.validation && (
        <section>
          <h2 className="mb-3 text-sm font-medium text-neutral-500">
            Валидация на историческом срезе
          </h2>
          <pre className="overflow-x-auto rounded bg-neutral-50 p-4 text-xs">
            {JSON.stringify(data.validation, null, 2)}
          </pre>
        </section>
      )}
    </main>
  );
}
```

- [ ] **Шаг 4: проверить**

```bash
uv run pytest api/ -v
curl -s localhost:8000/api/v1/methodology | head -20
```
В браузере: переключить срез на 2021 — список меняется, появляется пометка о бэктесте.

- [ ] **Шаг 5: коммит**

```bash
git add api/routes/methodology.py api/main.py web/
git commit -m "Вкладка методологии и переключатель года среза"
```

---

## Task M-07: Экспорт XLSX

Аналитики банка живут в Excel, а не в вебе.

**Файлы:**
- Создать: `api/routes/export.py`
- Тест: `api/test_export.py`

**Интерфейсы:**
- `POST /api/v1/export` тело `{domain, as_of, format:"xlsx"}` → файл

- [ ] **Шаг 1: падающий тест**

```python
# api/test_export.py
import io

import openpyxl
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_выгрузка_содержит_ссылки_и_ряды():
    r = client.post("/api/v1/export",
                    json={"domain": "golden", "as_of": 2026, "format": "xlsx"})
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    шапка = [c.value for c in wb.active[1]]
    assert "Тренд" in шапка and "Год взлёта" in шапка and "Источники" in шапка
    assert wb.active.max_row > 1
```

- [ ] **Шаг 2: убедиться, что падает**

Запустить: `uv run pytest api/test_export.py -v`
Ожидаемо: 404 — маршрута ещё нет

- [ ] **Шаг 3: реализация**

```python
# api/routes/export.py
"""Выгрузка ТОП в XLSX: аналитики банка готовят справки в Excel, не в браузере."""
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from api.store import get_store

router = APIRouter(prefix="/api/v1")

ШАПКА = ["#", "Тренд", "Emergence Score", "Стадия", "Уверенность",
         "Первое упоминание", "Год взлёта", "Публикаций", "Стран",
         "Динамика по годам", "Источники"]


@router.post("/export")
def export(body: dict) -> StreamingResponse:
    домен = body.get("domain", "")
    store = get_store()
    строки = store.trends(домен, int(body.get("as_of", 2026)), 50)
    if not строки:
        raise HTTPException(404, f"домен '{домен}' не найден")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Тренды {body.get('as_of', 2026)}"
    ws.append(ШАПКА)
    for r in строки:
        документы = store.works(домен, list(r["top_doc_ids"])[:5])
        ws.append([
            int(r["rank"]), r["label"], round(float(r["emergence_score"]), 3),
            r["stage"], r["confidence"], r["first_mention"], r["takeoff_year"],
            int(r["n_docs"]), int(r["n_countries"]),
            ", ".join(f"{y}:{c}" for y, c in zip(r["years"], r["counts"], strict=True)),
            "\n".join(d["url"] for d in документы),
        ])
    for колонка, ширина in zip("ABCDEFGHIJK", [4, 40, 10, 14, 12, 10, 10, 10, 8, 30, 50],
                               strict=True):
        ws.column_dimensions[колонка].width = ширина

    буфер = io.BytesIO()
    wb.save(буфер)
    буфер.seek(0)
    return StreamingResponse(
        буфер,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="trends-{домен}.xlsx"'})
```

Подключить в `api/main.py`:

```python
from api.routes import export as export_routes  # noqa: E402

app.include_router(export_routes.router)
```

- [ ] **Шаг 4: тесты зелёные**

Запустить: `uv run pytest api/ -v`
Ожидаемо: все passed

- [ ] **Шаг 5: коммит**

```bash
git add api/routes/export.py api/main.py api/test_export.py
git commit -m "Экспорт ТОП-15 в XLSX со ссылками и годовой динамикой"
```

---

## Task M-08: Docker Compose

Жюри часто просит развернуть у себя. `docker compose up` должен поднимать всё
с нуля на чистой машине. Обязательно arm64 — у нас два мака.

**Файлы:**
- Создать: `api/Dockerfile`, `web/Dockerfile`, `docker-compose.yml`, `.dockerignore`

- [ ] **Шаг 1: Dockerfile API**

```dockerfile
# api/Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY contracts/ ./contracts/
COPY core/ ./core/
COPY api/ ./api/

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Шаг 2: Dockerfile фронта**

```dockerfile
# web/Dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

В `web/next.config.ts` добавить `output: "standalone"`.

- [ ] **Шаг 3: compose**

```yaml
# docker-compose.yml
# Два сервиса и ничего больше: БД нет, индекс — это файлы.
# Поэтому демо работает без сети, а поднятие занимает секунды.
services:
  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data:ro        # индекс только на чтение
    environment:
      LLM_BACKEND: ollama
      LLM_BASE_URL: http://host.docker.internal:11434   # Metal недоступен в контейнере
    extra_hosts: ["host.docker.internal:host-gateway"]

  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    depends_on: [api]
```

```
# .dockerignore
.git
.venv
node_modules
web/.next
data/cache
data/corpus
__pycache__
*.log
```

- [ ] **Шаг 4: проверить подъём с нуля**

```bash
docker compose build && docker compose up -d
curl -s localhost:8000/api/v1/health
open http://localhost:3000
docker image inspect trendradar-api --format '{{.Architecture}}'
```
Ожидаемо: `health` отвечает, фронт открывается, архитектура `arm64` без эмуляции.

- [ ] **Шаг 5: коммит**

```bash
git add api/Dockerfile web/Dockerfile docker-compose.yml .dockerignore web/next.config.ts
git commit -m "Docker Compose: два сервиса, подъём одной командой"
```
