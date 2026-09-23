"""Перевод русских названий технологий в английские поисковые запросы.

Датасет заказчика на русском и многословный: «Квантово-инспирированное сжатие
моделей для запуска LLM на edge-железе». OpenAlex, GitHub и Hugging Face ищут
по-английски и по коротким фразам. Переводит локальная модель.

ТЗ требует раскрывать формат выбора модели и явно логировать: у каждого
перевода записано, какая модель его сделала. Кэш версионируется - прогон
воспроизводим, повторный запуск офлайн.
"""
import json
import re
from pathlib import Path

КЭШ_ПО_УМОЛЧАНИЮ = Path("classifier/queries_cache.json")

ПРОМПТ = """Ты переводишь название технологии в поисковые запросы на английском.

Технология: {label}
Область: {domain}
Контекст: {why}

Верни только JSON:
{{
  "query_en": "одна короткая английская фраза, 2-5 слов, как её называют в индустрии",
  "keyphrases": ["2-4 альтернативных названия или близких термина по-английски"]
}}

Правила: никаких кавычек внутри строк, никаких пояснений вне JSON,
термины - как в отраслевых новостях и статьях, а не дословный перевод."""


def _разобрать(текст: str) -> dict:
    m = re.search(r"\{.*\}", текст, re.S)
    d = json.loads(m.group(0) if m else текст)
    return {"query_en": str(d["query_en"]).strip(),
            "keyphrases": [str(k).strip() for k in d.get("keyphrases", []) if str(k).strip()]}


class ЗапросыКэш:
    def __init__(self, путь: str | Path | None = КЭШ_ПО_УМОЛЧАНИЮ):
        self.путь = Path(путь) if путь else None
        self._d: dict[str, dict] = {}
        if self.путь and self.путь.exists():
            self._d = json.loads(self.путь.read_text(encoding="utf-8"))

    def взять(self, label: str) -> dict | None:
        return self._d.get(label)

    def положить(self, label: str, запрос: dict, model: str) -> None:
        self._d[label] = {**запрос, "model": model}
        if self.путь:
            self.путь.parent.mkdir(parents=True, exist_ok=True)
            self.путь.write_text(json.dumps(self._d, ensure_ascii=False, indent=1, sort_keys=True),
                                 encoding="utf-8")


def перевести(строка: dict, кэш: ЗапросыКэш, llm=None) -> dict:
    """Запрос для одной технологии: из кэша, иначе через модель с записью в кэш."""
    готовый = кэш.взять(строка["label"])
    if готовый:
        return готовый
    if llm is None:
        from cards.llm import LLM
        llm = LLM()
    текст = llm.json(ПРОМПТ.format(label=строка["label"], domain=строка["domain"],
                                    why=(строка.get("why") or "")[:300]))
    запрос = _разобрать(json.dumps(текст) if isinstance(текст, dict) else текст)
    кэш.положить(строка["label"], запрос, f"{llm.backend}:{llm.model}")
    return кэш.взять(строка["label"])


def main() -> None:
    """python -m classifier.queries - перевести всю выборку, заполнить кэш."""
    import sys

    from classifier.dataset import собрать_выборку

    xlsx = sys.argv[1] if len(sys.argv) > 1 else \
        "../tz/Датасет/Датасет/100_слабых_технологических_сигналов_сентябрь_2026.xlsx"
    кэш = ЗапросыКэш()
    выборка = собрать_выборку(xlsx)
    for i, s in enumerate(выборка, 1):
        q = перевести(s, кэш)
        print(f"[{i:>3}/{len(выборка)}] {s['label'][:50]:<50} -> {q['query_en']}")


if __name__ == "__main__":
    main()
