from cards.prompt import собрать


def test_prompt_lists_allowed_document_ids_for_literal_copying() -> None:
    prompt = собрать(
        {
            "label": "demo trend",
            "takeoff_year": 2025,
            "n_docs": 12,
            "n_countries": 5,
        },
        [
            {
                "doc_id": "openalex:W1",
                "year": 2025,
                "title": "Первый документ",
                "abstract": "Краткое описание.",
            },
            {
                "doc_id": "openalex:W2",
                "year": 2026,
                "title": "Второй документ",
                "abstract": None,
            },
        ],
    )

    assert "ДОПУСТИМЫЕ ID ДЛЯ ЦИТИРОВАНИЯ:" in prompt
    assert "openalex:W1, openalex:W2" in prompt
    assert "копируй ID только из блока" in prompt
    assert "описывай технологию «demo trend»" in prompt
    assert "Не выдавай частный случай за суть технологии." in prompt
    assert "Если подан только один документ, будь скромен" in prompt
    assert "Количество документов: 2" in prompt


def test_prompt_requires_modest_scope_for_one_document() -> None:
    prompt = собрать(
        {
            "label": "demo trend",
            "takeoff_year": 2025,
            "n_docs": 1,
            "n_countries": 1,
        },
        [
            {
                "doc_id": "openalex:W1",
                "year": 2025,
                "title": "Единственный документ",
                "abstract": None,
            }
        ],
    )

    assert "Подан РОВНО ОДИН документ" in prompt
    assert "описывай только задачу и результат этого конкретного исследования" in prompt
    assert "problem` обязан начинаться с «В единственном представленном исследовании»" in prompt
