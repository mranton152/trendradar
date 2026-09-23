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
# OpenAlex с 2026 считает дневной бюджет на IP без ключа; ключ бесплатный.
# Без него на 200 технологий x 5 запросов бюджета не хватает: первый прогон
# получил 441 отказ 429 из 1176, и нули в признаках выглядели как "нет
# публикаций". Ключ - в OPENALEX_API_KEY.
OPENALEX_KEY = os.getenv("OPENALEX_API_KEY")


class ОтказИсточника(RuntimeError):
    """Источник ответил ошибкой. Не кэшируем и не подменяем нулём: ноль
    «нет публикаций» и ноль «ответа не было» - разные вещи, а модель этого
    не различит."""

# Слова, по которым индустрия сигналит о ранней стадии. Из датасета заказчика:
# там обоснование почти всегда - раунд, выход из stealth, первый пилот.
СЛОВА_РАУНДОВ = ("raises", "raised", "funding", "series a", "series b", "seed",
                 "stealth", "launches", "pilot", "startup", "acquires", "unveils")

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

# Признаки Hacker News исключены из набора после замера: они ухудшают точность
# (76% -> 74%) и направление у них обратное - у сигналов упоминаний МЕНЬШЕ,
# чем у зрелых (медиана 0 против 3). Причина: поиск по фразе меряет
# известность названия, а не новизну технологии. "Kubernetes" обсуждают
# постоянно, а "AI agent IAM" - это наше сгенерированное название, которого
# в индустрии не пишут. Код сбора оставлен: он понадобится, когда появятся
# настоящие новостные кандидаты с именами компаний и продуктов (K-11..K-13).
HN_ПРИЗНАКИ = ("hn_mentions_12m", "hn_recent_share", "hn_funding_mentions", "hn_points_max")


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
        self.client = client or httpx.Client(
            timeout=60, follow_redirects=True,
            headers={"User-Agent": f"trendradar/0.2 (+mailto:{ПОЧТА})"})
        self.год = dt.date.today().year
        self.отказов = 0
        # какой запрос реально дал данные - в отчёт, чтобы цифры можно было проверить
        self.использованный_запрос: dict[str, str] = {}
        tok = _github_token()
        self.gh_headers = {"Authorization": f"Bearer {tok}"} if tok else {}

    # ---------- сырые запросы, каждый кэшируется по ключу
    def _get(self, ключ: str, url: str, params: dict, headers: dict | None = None) -> dict:
        готово = self.кэш.get(ключ)
        if готово is not None and "_error" not in готово:
            return готово
        if "openalex" in url and OPENALEX_KEY:
            params = {**params, "api_key": OPENALEX_KEY}
        r = self.client.get(url, params=params, headers=headers or {})
        if r.status_code != 200:
            self.отказов += 1
            raise ОтказИсточника(f"{r.status_code} {url.split('/')[2]}: {ключ[:60]}")
        d = r.json()
        self.кэш[ключ] = d
        return d

    def _годы_одного(self, q: str) -> dict[int, int]:
        # Без кавычек: И-связка слов, а не точная фраза. Точная фраза давала ноль
        # у 63 сигналов из 100 - многословные названия технологий никто не пишет
        # дословно. "AI agent IAM" в кавычках - 0 работ, без кавычек - 136.
        d = self._get(f"oa:years:{q}", "https://api.openalex.org/works",
                      {"filter": f"title_and_abstract.search:{q}",
                       "group_by": "publication_year", "mailto": ПОЧТА})
        return {int(g["key"]): g["count"] for g in d.get("group_by", [])
                if str(g["key"]).isdigit() and self.год - ЛЕТ < int(g["key"]) <= self.год}

    def openalex_годы(self, q: str, алиасы: list[str] | None = None) -> dict[int, int]:
        """Годовой ряд. При пустом результате пробуем альтернативные названия."""
        for кандидат in [q, *(алиасы or [])]:
            годы = self._годы_одного(кандидат)
            if годы:
                self.использованный_запрос[q] = кандидат
                return годы
        self.использованный_запрос[q] = q
        return {}

    def openalex_страны(self, q: str) -> int:
        окно = f"publication_year:{self.год - 2}-{self.год}"
        d = self._get(f"oa:countries:{q}", "https://api.openalex.org/works",
                      {"filter": f"title_and_abstract.search:{q},{окно}",
                       "group_by": "authorships.institutions.country_code",
                       "per-page": 200, "mailto": ПОЧТА})
        return len([g for g in d.get("group_by", []) if g.get("count", 0) >= 2])

    def openalex_компании(self, q: str) -> float:
        окно = f"publication_year:{self.год - 2}-{self.год}"
        базовый = f"title_and_abstract.search:{q},{окно}"
        общ = self._get(f"oa:total3:{q}", "https://api.openalex.org/works",
                        {"filter": базовый, "per-page": 1, "mailto": ПОЧТА}
                        ).get("meta", {}).get("count", 0)
        комп = self._get(f"oa:company3:{q}", "https://api.openalex.org/works",
                         {"filter": f"{базовый},authorships.institutions.type:company",
                          "per-page": 1, "mailto": ПОЧТА}
                         ).get("meta", {}).get("count", 0)
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

    def hackernews(self, q: str) -> dict:
        """Индустриальные упоминания через Hacker News Algolia - без ключа, с датами.

        Публикационные признаки не отличают нейроморфные чипы (наука с 1980-х,
        индустрия с 2025) от зрелых технологий. Новостной сигнал отличает.
        """
        d = self._get(f"hn:{q}", "https://hn.algolia.com/api/v1/search",
                      {"query": q, "tags": "story", "hitsPerPage": 100})
        hits = d.get("hits", []) or []
        if not hits:
            return {"hn_mentions_12m": 0, "hn_recent_share": 0.0,
                    "hn_funding_mentions": 0, "hn_points_max": 0}
        порог = dt.datetime.now(dt.UTC).timestamp() - 365 * 24 * 3600
        свежие = [h for h in hits if (h.get("created_at_i") or 0) >= порог]
        раунды = sum(1 for h in hits
                     if any(w in (h.get("title") or "").lower() for w in СЛОВА_РАУНДОВ))
        return {"hn_mentions_12m": len(свежие),
                "hn_recent_share": len(свежие) / len(hits),
                "hn_funding_mentions": раунды,
                "hn_points_max": max((h.get("points") or 0) for h in hits)}

    def hf(self, q: str) -> int:
        d = self._get(f"hf:{q}", "https://huggingface.co/api/models", {"search": q, "limit": 100})
        return len(d) if isinstance(d, list) else 0

    # ---------- признаки одной технологии
    def признаки(self, q: str, norm: dict[int, float] | None = None,
                 алиасы: list[str] | None = None) -> dict:
        годы = self.openalex_годы(q, алиасы)
        q = self.использованный_запрос.get(q, q)   # дальше считаем тем же запросом
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
            **self.hackernews(q),   # собираем, но в ОПИСАНИЯ не входят - см. HN_ПРИЗНАКИ
        }


def собрать_признаки(выборка: list[dict], запросы: dict[str, dict]) -> list[dict]:
    """Признаки для всей выборки. Peer-нормировка - по пулу всей выборки."""
    сб = Сборщик()
    try:
        ряды = {s["label"]: сб.openalex_годы(запросы[s["label"]]["query_en"],
                                             запросы[s["label"]].get("keyphrases"))
                for s in выборка}
    except ОтказИсточника as e:
        _сохранить(сб.кэш)
        raise SystemExit(f"источник отказал: {e}. Кэш сохранён, повторный запуск продолжит "
                         f"с этого места. Для OpenAlex нужен OPENALEX_API_KEY.") from e
    _сохранить(сб.кэш)
    годы_окна = list(range(сб.год - 6, сб.год + 1))
    norm = peer_normalizer(list(ряды.values()), годы_окна)
    out = []
    for i, s in enumerate(выборка, 1):
        q = запросы[s["label"]]["query_en"]
        try:
            f = сб.признаки(q, norm, запросы[s["label"]].get("keyphrases"))
        except ОтказИсточника as e:
            _сохранить(сб.кэш)
            raise SystemExit(f"источник отказал на «{s['label'][:40]}»: {e}. "
                             f"Кэш сохранён ({i - 1}/{len(выборка)} готово).") from e
        out.append({**s, "query_en": q,
                    "query_used": сб.использованный_запрос.get(q, q), **f})
        if i % 20 == 0:
            _сохранить(сб.кэш)
            print(f"  {i}/{len(выборка)}")
    _сохранить(сб.кэш)
    return out
