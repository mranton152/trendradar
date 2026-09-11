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
