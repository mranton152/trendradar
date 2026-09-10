"""Проверяемый концепт OpenAlex для произвольного домена."""
import re


def resolve_concept(client, query, concept_id=None):
    if concept_id:
        if not re.fullmatch(r"C\d+", concept_id):
            raise ValueError("Ожидался concept-id вида C58053490")
        concept = client.get(f"/concepts/{concept_id}", {})
        if concept.get("id", "").rsplit("/", 1)[-1] != concept_id:
            raise ValueError("OpenAlex вернул другой концепт")
        return concept
    concepts = client.get("/concepts", {"search": query, "per_page": 5})["results"]
    concept = next((c for c in concepts if c["display_name"].casefold() == query.casefold()), None)
    if concept is None:
        raise ValueError(f"Не найден точный концепт: {query}; задайте проверенный --concept-id")
    return concept
