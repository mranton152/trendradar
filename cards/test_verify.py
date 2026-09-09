from cards.verify import проверить_цитаты

CARD = {
    "problem": "Дорого считать",
    "problem_docs": ["openalex:W1"],
    "advantage": "Быстрее",
    "advantage_docs": ["openalex:W404"],
    "case_text": "Компания X",
    "case_docs": ["openalex:W2"],
}


def test_unsupported_statement_is_removed() -> None:
    cleaned, coverage = проверить_цитаты(CARD, {"openalex:W1", "openalex:W2"})

    assert cleaned["problem"] == "Дорого считать"
    assert cleaned["advantage"] == ""
    assert cleaned["advantage_docs"] == []
    assert coverage == 2 / 3


def test_fully_supported_card_has_full_coverage() -> None:
    _, coverage = проверить_цитаты(CARD, {"openalex:W1", "openalex:W2", "openalex:W404"})

    assert coverage == 1.0


def test_empty_citations_are_not_supported() -> None:
    card = {**CARD, "problem_docs": []}

    cleaned, coverage = проверить_цитаты(card, {"openalex:W2"})

    assert cleaned["problem"] == ""
    assert coverage < 1.0
