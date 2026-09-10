"""Термины из заголовков всего корпуса, без временного ранжирования.

Два прохода: частоты, затем связи только прошедших порог терминов.
Промежуточные postings для всего словаря не сохраняются. Возвращаемые связи
остаются в памяти; интерфейс принимает список, а не поток parquet.
"""

import hashlib
import re
from collections import Counter

from semantic.filter import technology_reason

_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
_STOP = frozenset(
    """a an the of in on for to and or with by from at as is are was were
this that these those using based study analysis approach new via into
и в во на для с со к по из от о об а но или это как при
исследование анализ новый новая новые""".split()
)
_MAX_TITLE_CHARS = 4096
_MAX_TITLE_TOKENS = 128


def ngrams(title: str):
    """Выдать смежные 2–4-граммы, сохраняя правила стоп-слов прототипа."""
    tokens = _TOKEN_RE.findall(title[:_MAX_TITLE_CHARS].casefold())[:_MAX_TITLE_TOKENS]
    for size in range(2, 5):
        for start in range(len(tokens) - size + 1):
            group = tokens[start : start + size]
            if group[0] in _STOP or group[-1] in _STOP:
                continue
            if sum(token in _STOP for token in group) > size - 2:
                continue
            if all(len(token) <= 2 for token in group):
                continue
            yield " ".join(group)


def extract_terms(
    rows: list[dict],
    domain: str,
    min_docs: int = 20,
) -> tuple[list[dict], list[dict], dict]:
    """Создать строки CANDIDATES/CAND_DOCS и диагностику лексического отсева.

    doc_id должны быть уникальны; повторение термина внутри заголовка
    учитывается один раз. Идентификаторы зависят только от домена и термина.
    Ограничение длины заголовка явно отражено в диагностике; лимита числа
    кандидатов нет. Годы и аннотации не влияют на извлечение.
    """
    if isinstance(min_docs, bool) or not isinstance(min_docs, int) or min_docs < 1:
        raise ValueError("min_docs должен быть положительным целым")
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain не должен быть пустым")
    seen = set()
    counts = Counter()
    bounded_titles = 0
    for row in rows:
        doc_id = row["doc_id"]
        if not isinstance(doc_id, str) or not doc_id or doc_id in seen:
            raise ValueError("doc_id должен быть непустым и уникальным")
        seen.add(doc_id)
        title = row["title"]
        if not isinstance(title, str):
            raise ValueError("title должен быть строкой")
        if (
            len(title) > _MAX_TITLE_CHARS
            or len(_TOKEN_RE.findall(title[:_MAX_TITLE_CHARS])) > _MAX_TITLE_TOKENS
        ):
            bounded_titles += 1
        counts.update(set(ngrams(title)))
    rejected = Counter()
    candidates = []
    accepted = {}
    for term, frequency in sorted(counts.items()):
        if frequency < min_docs:
            continue
        reason = technology_reason(term)
        if reason is not None:
            rejected[reason] += 1
            continue
        digest = hashlib.sha256((domain + "\0" + term).encode("utf-8")).hexdigest()[:24]
        cand_id = f"t:{domain}:{digest}"
        accepted[term] = cand_id
        candidates.append(
            {
                "cand_id": cand_id,
                "kind": "term",
                "label": term,
                "aliases": [],
                "top_terms": [term],
                "emb_row": None,
                "n_docs": frequency,
                "domain": domain,
            }
        )
    links = []
    for row in rows:
        for term in set(ngrams(row["title"])) & accepted.keys():
            links.append({"cand_id": accepted[term], "doc_id": row["doc_id"], "weight": 1.0})
    links.sort(key=lambda link: (link["cand_id"], link["doc_id"]))
    return (
        candidates,
        links,
        {
            "method": "title_ngrams_2_4_lexical_v1",
            "min_docs": min_docs,
            "n_documents": len(rows),
            "n_distinct_ngrams": len(counts),
            "n_candidates": len(candidates),
            "n_links": len(links),
            "rejected_by_reason": dict(sorted(rejected.items())),
            "n_bounded_titles": bounded_titles,
            "max_title_chars": _MAX_TITLE_CHARS,
            "max_title_tokens": _MAX_TITLE_TOKENS,
        },
    )
