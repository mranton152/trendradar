"""Абстракция локальной или совместимой с OpenAI модели для генерации JSON."""

import json
import os
import re
from collections.abc import Mapping
from typing import Any

import httpx


class LLM:
    """Вызывает настроенный провайдер, не привязывая этап cards к конкретной модели."""

    def __init__(self, backend: str | None = None, model: str | None = None) -> None:
        self.backend = backend or os.getenv("LLM_BACKEND", "ollama")
        self.model = model or os.getenv("LLM_MODEL", "qwen2.5:7b")
        self.base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434").rstrip("/")

    def json(self, prompt: str, schema: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Возвращает JSON-объект; обрамляющий текст модели допускается только вне объекта."""
        text = self._request(prompt, schema)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match is None:
                raise
            payload = json.loads(match.group(0))

        if not isinstance(payload, dict):
            raise ValueError("LLM вернула JSON, но не объект")
        return payload

    def _request(self, prompt: str, schema: Mapping[str, Any] | None) -> str:
        if self.backend == "ollama":
            response = httpx.post(
                f"{self.base_url}/api/generate",
                timeout=300,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "format": dict(schema) if schema else "json",
                    "stream": False,
                },
            )
            response.raise_for_status()
            return response.json()["response"]

        if self.backend == "openai_compatible":
            response = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                timeout=300,
                headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        raise ValueError(f"Неизвестный LLM_BACKEND: {self.backend}")
