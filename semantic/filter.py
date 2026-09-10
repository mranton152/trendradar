"""Объяснимый лексический фильтр: не POS-разбор и не классификатор смысла.

Наличие технического маркера сохраняет биомедицинские методы даже при
упоминании болезни. Отсутствие маркера трактуется консервативно: редкая
технология может потребовать расширения словаря и ручной проверки.
"""

import re

# Узкий список однозначных прилагательных вместо POS-модели. Не включаем
# computing/learning/editing: эти формы сами называют методы и технологии.
_TERMINAL_MODIFIERS = frozenset({"neural", "artificial", "convolutional", "recurrent"})

_TECHNOLOGY = re.compile(
    r"\b(?:neural|networks?|computing|quantum|algorithms?|learning|robotics?|"
    r"transformers?|semiconductors?|sensors?|photonic\w*|nanotech\w*|"
    r"bioprint\w*|crispr|immunotherap\w*|vaccin\w*|sequencing|"
    r"gene editing|genome editing|gene therapy|drug delivery|"
    r"нейрон\w*|нейросет\w*|квантов\w*|вычислен\w*|алгоритм\w*|"
    r"робот\w*|сенсор\w*|полупроводник\w*|фотон\w*|"
    r"редактирован\w* геном\w*|генн\w* терап\w*|вакцин\w*|"
    r"иммунотерап\w*|секвенирован\w*)\b",
    re.IGNORECASE,
)
_EVENT = re.compile(r"\b(?:pandemic|epidemic|war|пандеми\w*|эпидеми\w*)\b")
_DISEASE = re.compile(
    r"\b(?:covid(?:-19)?|cancer|diabetes|alzheimer\w*|disease\w*|"
    r"рак|диабет\w*|болезн\w*)\b"
)
_ENTITY = re.compile(
    r"\b(?:united states|united kingdom|china|russia|university|organization|"
    r"росси\w*|китай\w*|университет\w*|организаци\w*)\b"
)


def technology_reason(text: str) -> str | None:
    """Вернуть причину отсева; None означает принятие кандидата."""
    normalized = " ".join(text.casefold().split())
    if not normalized:
        return "пустое название"
    words = re.findall(r"[^\W_]+(?:-[^\W_]+)*", normalized)
    if words and words[-1] in _TERMINAL_MODIFIERS:
        return "оборванный термин: конечный модификатор"
    if _TECHNOLOGY.search(normalized):
        return None
    if _EVENT.search(normalized):
        return "событие без технологического маркера"
    if _DISEASE.search(normalized):
        return "болезнь без технологического маркера"
    if _ENTITY.search(normalized):
        return "география или организация без технологического маркера"
    return "нет технологического маркера"
