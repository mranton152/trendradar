"""Промпт для извлечения фактов из документов, а не генерации знаний о тренде."""

from collections.abc import Mapping, Sequence
from typing import Any

TEMPLATE = """Ты не эксперт по теме. Ты извлекаешь факты только из поданных документов.

Тренд: {label}
Год взлёта: {takeoff}. Публикаций за окно: {n_docs}. Стран: {n_countries}.

ДОКУМЕНТЫ:
{documents}

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
  "case_docs": ["doc_id"]
}}

Правила:
- Если факта в документах нет — не пиши его. Пустая строка лучше выдумки.
- Каждый doc_id обязан быть из списка выше. Не придумывай идентификаторы.
- Не используй знания вне поданных документов.
"""


def собрать(trend: Mapping[str, Any], documents: Sequence[Mapping[str, Any]]) -> str:
    """Готовит компактный, но достаточный контекст для LLM."""
    lines = []
    for document in documents:
        abstract = document.get("abstract")
        text = f"[{document['doc_id']}] ({document['year']}) {document['title']}"
        if isinstance(abstract, str) and abstract:
            text += f"\n  {abstract[:400]}"
        lines.append(text)

    return TEMPLATE.format(
        label=trend["label"],
        takeoff=trend.get("takeoff_year"),
        n_docs=trend["n_docs"],
        n_countries=trend["n_countries"],
        documents="\n".join(lines) or "Документы для тренда не найдены.",
    )
