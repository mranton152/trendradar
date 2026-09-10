"""Явное разрешение домена без подмены первым поисковым результатом."""
import pytest

from ingest.domain import resolve_concept


def test_explicit_concept_is_verified():
    class Client:
        def get(self, path, params):
            assert path == "/concepts/C58053490"
            return {"id": "https://openalex.org/C58053490", "display_name": "Quantum computer"}

    assert resolve_concept(Client(), "quantum computing", "C58053490")["display_name"] == (
        "Quantum computer")


def test_missing_exact_match_does_not_select_unrelated_first_result():
    class Client:
        def get(self, path, params):
            return {"results": [{"id": "C1", "display_name": "Superconducting quantum computing"}]}

    with pytest.raises(ValueError):
        resolve_concept(Client(), "quantum computing")
