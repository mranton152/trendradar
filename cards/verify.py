"""Постобработка выдачи LLM: неподтверждённые утверждения не попадают в карточку."""

from collections.abc import Mapping
from typing import Any

CLAIM_FIELDS = (
    ("problem", "problem_docs"),
    ("advantage", "advantage_docs"),
    ("case_text", "case_docs"),
)


def проверить_цитаты(card: Mapping[str, Any], allowed: set[str]) -> tuple[dict[str, Any], float]:
    """Оставляет только утверждения, подтверждённые хотя бы одним входным документом."""
    cleaned = dict(card)
    supported = 0

    for text_field, docs_field in CLAIM_FIELDS:
        text = card.get(text_field)
        cited_ids = card.get(docs_field)
        live_ids = [
            doc_id for doc_id in cited_ids or [] if isinstance(doc_id, str) and doc_id in allowed
        ]

        if isinstance(text, str) and text.strip() and live_ids:
            cleaned[docs_field] = live_ids
            supported += 1
            continue

        cleaned[text_field] = ""
        cleaned[docs_field] = []
        if text_field == "case_text":
            cleaned["case_name"] = ""

    return cleaned, supported / len(CLAIM_FIELDS)
