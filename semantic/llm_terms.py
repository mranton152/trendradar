"""Кандидаты-технологии из заголовков живого корпуса с помощью локальной LLM.

Зачем. Правила extract_live находят названия компаний и технологии из словаря.
На широких запросах этого мало: замер 27.09 — «технологии в ИИ» 7 кандидатов из
1371 документа, «финтех и платежи» 2 из 617, «биотехнологии» 1 из 774. В тех же
корпусах модель за ~30 с называет 13–24 технологии, которые повторяются в разных
заголовках: stablecoin payments, instant payments, physical ai, radiopharma.

Почему это не «тренды из головы модели». Модель только предлагает строки.
Кандидатом строка становится, если она дословно, целым словом, встречается
в заголовках минимум `min_docs` документов корпуса. Связи кандидат — документ
строятся этим совпадением, а не ответом модели. Выдуманная технология, которой
нет в заголовках, отбрасывается автоматически. Дальше кандидат идёт через те же
фильтры ядра, что и остальные: зрелость по OpenAlex, тема запроса, издания.
"""
import json
import re
import time

ПРОМПТ = """From these news headlines, list specific emerging technologies, \
technical approaches or product categories they mention (2-4 words each, English, lowercase).
Exclude company names, people, places, funding words, and generic terms like \
"AI", "technology", "fintech", "startup".
Return JSON {{"technologies": [...]}}.

Headlines:
{headlines}"""

СХЕМА = {"type": "object",
         "properties": {"technologies": {"type": "array", "items": {"type": "string"}}},
         "required": ["technologies"]}

# Слова бизнес-хроники, а не технологий: «ai startups», «pre-seed round»,
# «payments industry», «global expansion» — замер на тех же корпусах.
НЕ_ТЕХНОЛОГИЯ = {"startup", "startups", "funding", "round", "seed", "series", "stock",
                 "stocks", "investment", "investments", "investor", "investors", "industry",
                 "market", "markets", "leader", "leaders", "strategy", "expansion", "deal",
                 "deals", "m&a", "ipo", "valuation", "regulation", "regulations", "law",
                 "laws", "news", "report", "week", "company", "companies", "revenue",
                 "earnings", "innovation", "global", "venture", "vc"}

ПАЧКА = 75           # заголовков на запрос: ~10 с на qwen2.5:7b, M1
МАКС_ЗАГОЛОВКОВ = 300


def _чистый(term: str) -> str | None:
    t = re.sub(r"\s+", " ", term.strip().lower().strip("\"'.,;:"))
    слова = t.split()
    if not 1 <= len(слова) <= 4 or len(t) < 4:
        return None
    if any(w in НЕ_ТЕХНОЛОГИЯ for w in слова):
        return None
    return t


def предложить(заголовки: list[str], llm, бюджет_с: float = 45.0) -> tuple[list[str], dict]:
    """Строки-кандидаты от модели и аудит вызова. Отказ модели — пустой список,
    а не исключение: живой режим обязан вернуть выдачу по остальным кандидатам."""
    начало = time.monotonic()
    найдено: dict[str, None] = {}
    аудит = {"model": getattr(llm, "model", None), "backend": getattr(llm, "backend", None),
             "n_headlines": min(len(заголовки), МАКС_ЗАГОЛОВКОВ), "batches": 0, "errors": []}
    for i in range(0, min(len(заголовки), МАКС_ЗАГОЛОВКОВ), ПАЧКА):
        if time.monotonic() - начало > бюджет_с:
            аудит["errors"].append("бюджет времени исчерпан")
            break
        пачка = "\n".join(f"- {h}" for h in заголовки[i:i + ПАЧКА])
        try:
            ответ = llm.json(ПРОМПТ.format(headlines=пачка), СХЕМА)
        except Exception as exc:  # сеть, провайдер, невалидный JSON — всё не фатально
            аудит["errors"].append(type(exc).__name__)
            continue
        аудит["batches"] += 1
        for term in ответ.get("technologies", []):
            if isinstance(term, str) and (t := _чистый(term)):
                найдено.setdefault(t)
    аудит["elapsed_s"] = round(time.monotonic() - начало, 1)
    аудит["n_proposed"] = len(найдено)
    return list(найдено), аудит


def заголовки_корпуса(rows: list[dict]) -> list[str]:
    """Свежие заголовки новостей без хвоста-издателя Google News."""
    новости = [r for r in rows if r.get("source") in ("gnews", "hackernews", "rss")]
    новости.sort(key=lambda r: r.get("date") or "", reverse=True)
    out = []
    for r in новости:
        t = r["title"]
        if r.get("source") == "gnews":
            t = t.rsplit(" - ", 1)[0]
        out.append(t)
    return out


def шаблон(term: str) -> re.Pattern:
    """Целое слово или фраза, без учёта регистра, с необязательным окончанием -s."""
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"s?(?![\w-])", re.IGNORECASE)


if __name__ == "__main__":  # ручная проверка: python -m semantic.llm_terms works.parquet
    import sys

    import pyarrow.parquet as pq

    from cards.llm import LLM
    rows = pq.read_table(sys.argv[1]).to_pylist()
    термины, аудит = предложить(заголовки_корпуса(rows), LLM())
    print(json.dumps(аудит, ensure_ascii=False), *термины, sep="\n")
