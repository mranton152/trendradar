"""Корень проекта попадает в sys.path, чтобы работал `import contracts.schemas`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _без_настоящей_llm(monkeypatch):
    """Тесты не ходят в настоящую LLM: результат не должен зависеть от того,
    запущена ли Ollama на машине. Кандидаты от модели проверяются с фейком
    в semantic/test_llm_terms.py."""
    monkeypatch.setenv("TRENDRADAR_LLM_TERMS", "0")
