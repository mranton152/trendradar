"""Отдельный процесс для ограничения синхронного вызова cards.llm по времени."""
import json
import os
import sys

import httpx

from cards.llm import LLM


class StudioLLM(LLM):
    """Совместимость LM Studio с JSON Schema при сохранении парсера cards.llm."""

    def _request(self, prompt, schema):
        response = httpx.post(
            self.base_url + '/v1/chat/completions', timeout=120,
            headers={'Authorization': 'Bearer ' + os.getenv('LLM_API_KEY', 'lm-studio')},
            json={'model': self.model, 'messages': [{'role': 'user', 'content': prompt}],
                  'max_tokens': 512, 'temperature': 0,
                  'response_format': {'type': 'json_schema', 'json_schema': {
                      'name': 'search_phrases', 'strict': True, 'schema': {
                          'type': 'object', 'properties': {'phrases': {
                              'type': 'array', 'items': {
                                  'type': 'string', 'pattern': '^[\\x20-\\x7e]+$'},
                              'minItems': 1, 'maxItems': 3}},
                          'required': ['phrases'], 'additionalProperties': False}}}})
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']


if __name__ == '__main__':
    model = StudioLLM() if os.getenv('LLM_BACKEND') == 'lmstudio' else LLM()
    print(json.dumps(model.json(sys.stdin.read()), ensure_ascii=False))
