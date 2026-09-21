"""Признаки для классификатора, версия 1: публикации, код, модели.

Всё - с бесключевых API, всё кэшируется в classifier/features_cache.json:
прогон воспроизводим, повторный запуск офлайн.

Новостных признаков здесь НЕТ - их даёт стадия ingest (K-14) по контракту
FEATURES. Когда приедут, встанут рядом отдельными колонками, и отчёт покажет,
сколько они добавляют к точности. Это честное разделение: сначала baseline
на том, что есть, потом прирост от каждого источника.

Правило: каждый признак объясним одной фразой аналитику. Фразы - в ОПИСАНИЯ.
"""
import datetime as dt
import json
import math
import os
import subprocess
from pathlib import Path

import httpx

from core.components import components
from core.normalize import peer_normalizer

КЭШ = Path("classifier/features_cache.json")
ПОЧТА = "flesha98@gmail.com"
ЛЕТ = 10

ОПИСАНИЯ = {
    "pub_total_10y": "сколько научных работ упоминают технологию за 10 лет",
    "pub_last_3y_share": "какая доля этих работ вышла за последние 3 года",
    "pub_growth": "наклон роста публикаций (логарифм, за 5 лет)",
    "pub_accel": "ускорение публикаций: усилился ли рост в последние годы",
    "pub_burst": "всплеск: во сколько раз последний год превысил базовую линию",
    "pub_age": "лет с года взлёта публикаций (выход на 10% собственного пика)",
    "pub_countries": "сколько стран публикуют по теме за 3 года",
    "pub_company_share": "доля работ с корпоративной аффилиацией - признак коммерциализации",
    "github_repos": "сколько репозиториев на GitHub по запросу",
    "github_stars_max": "звёзды самого популярного репозитория",
    "github_new_share": "доля репозиториев, созданных за последние 2 года",
    "hf_models": "сколько моделей на Hugging Face по запросу",
    "log_pub_total": "логарифм числа публикаций - чтобы масштаб не давил остальные",
}


def _кэш() -> dict:
    return json.loads(КЭШ.read_text(encoding="utf-8")) if КЭШ.exists() else {}


def _сохранить(d: dict) -> None:
    КЭШ.parent.mkdir(parents=True, exist_ok=True)
    КЭШ.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def _github_token() -> str | None:
    t = os.getenv("GITHUB_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class Сборщик:
    def __init__(self, кэш: dict | None = None, client: httpx.Client | None = None):
        self.кэш = кэш if кэш is not None else _кэш()
        self.client = client or httpx.Client(timeout=60, follow_redirects=True,
                                             headers={"User-Agent": f"trendradar/0.2 (+mailto:{ПОЧТА})"})
        self.год = dt.date.today().year
        tok = _github_token()
        self.gh_headers = {"Authorization": f"Bearer {tok}"} if tok else {}

    # ---------- сырые запросы, каждый кэшируется по ключу
    def _get(self, ключ: str, url: str, params: dict, headers: dict | None = None) -> dict:
        if ключ in self.кэш:
            return self.кэш[ключ]
        r = self.client.get(url, params=params, headers=headers or {})
        d = r.json() if r.status_code == 200 else {"_error": r.status_code}
        self.кэш[ключ] = d
        return d

    def openalex_годы(self, q: str) -> dict[int, int]:
        d = self._get(f"oa:years:{q}", "https://api.openalex.org/works",
                      {"filter": f'title_and_abstract.search:"{q}"', "group_by": "publication_year",
                       "mailto": ПОЧТА})
        return {int(g["key"]): g["count"] for g in d.get("group_by", [])
                if str(g["key"]).isdigit() and self.год - ЛЕТ < int(g["key"]) <= self.год}

    def openalex_страны(self, q: str) -> int:
        d = self._get(f"oa:countries:{q}", "https://api.openalex.org/works",
                      {"filter": f'title_and_abstract.search:"{q}",publication_year:{self.год-2}-{self.год}',
                       "group_by": "authorships.institutions.country_code", "per-page": 200, "mailto": ПОЧТА})
        return len([g for g in d.get("group_by", []) if g.get("count", 0) >= 2])

    def openalex_компании(self, q: str) -> float:
        общ = self._get(f"oa:total3:{q}", "https://api.openalex.org/works",
                        {"filter": f'title_and_abstract.search:"{q}",publication_year:{self.год-2}-{self.год}',
                         "per-page": 1, "mailto": ПОЧТА}).get("meta", {}).get("count", 0)
        комп = self._get(f"oa:company3:{q}", "https://api.openalex.org/works",
                         {"filter": f'title_and_abstract.search:"{q}",publication_year:{self.год-2}-{self.год},'
                                    'authorships.institutions.type:company',
                          "per-page": 1, "mailto": ПОЧТА}).get("meta", {}).get("count", 0)
        return комп / общ if общ else 0.0

    def github(self, q: str) -> dict:
        d = self._get(f"gh:{q}", "https://api.github.com/search/repositories",
                      {"q": q, "sort": "stars", "order": "desc", "per_page": 50}, self.gh_headers)
        items = d.get("items", []) or []
        порог = f"{self.год - 2}-01-01"
        return {"github_repos": int(d.get("total_count", 0) or 0),
                "github_stars_max": max((i.get("stargazers_count", 0) for i in items), default=0),
                "github_new_share": (sum(1 for i in items if (i.get("created_at") or "") >= порог)
                                     / len(items)) if items else 0.0}

    def hf(self, q: str) -> int:
        d = self._get(f"hf:{q}", "https://huggingface.co/api/models", {"search": q, "limit": 100})
        return len(d) if isinstance(d, list) else 0

    # ---------- признаки одной технологии
    def признаки(self, q: str, norm: dict[int, float] | None = None) -> dict:
        годы = self.openalex_годы(q)
        norm = norm or {y: 1.0 for y in range(self.год - ЛЕТ + 1, self.год + 1)}
        c = components(годы, norm, as_of=self.год)
        всего = sum(годы.values())
        посл3 = sum(n for y, n in годы.items() if y >= self.год - 2)
        gh = self.github(q)
        return {
            "pub_total_10y": всего,
            "pub_last_3y_share": посл3 / всего if всего else 0.0,
            "pub_growth": c["growth"], "pub_accel": c["accel"], "pub_burst": c["burst"],
            "pub_age": min(c["age"], 30),
            "pub_countries": self.openalex_страны(q),
            "pub_company_share": self.openalex_компании(q),
            **gh,
            "hf_models": self.hf(q),
            "log_pub_total": math.log1p(всего),
        }


def собрать_признаки(выборка: list[dict], запросы: dict[str, dict]) -> list[dict]:
    """Признаки для всей выборки. Peer-нормировка - по пулу всей выборки."""
    сб = Сборщик()
    ряды = {s["label"]: сб.openalex_годы(запросы[s["label"]]["query_en"]) for s in выборка}
    _сохранить(сб.кэш)
    годы_окна = list(range(сб.год - 6, сб.год + 1))
    norm = peer_normalizer(list(ряды.values()), годы_окна)
    out = []
    for i, s in enumerate(выборка, 1):
        q = запросы[s["label"]]["query_en"]
        f = сб.признаки(q, norm)
        out.append({**s, "query_en": q, **f})
        if i % 20 == 0:
            _сохранить(сб.кэш)
            print(f"  {i}/{len(выборка)}")
    _сохранить(сб.кэш)
    return out
