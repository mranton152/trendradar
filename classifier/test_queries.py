import json

from classifier.queries import ЗапросыКэш, _разобрать


def test_ответ_модели_разбирается_в_запрос_и_фразы():
    сырой = ('{"query_en": "agent identity access management", '
             '"keyphrases": ["agent IAM", "AI agent identity", "scoped permissions for agents"]}')
    q = _разобрать(сырой)
    assert q["query_en"] == "agent identity access management"
    assert len(q["keyphrases"]) == 3


def test_мусор_вокруг_json_не_ломает_разбор():
    сырой = 'Вот ответ:\n```json\n{"query_en": "x", "keyphrases": ["a"]}\n```'
    assert _разобрать(сырой)["query_en"] == "x"


def test_кэш_переживает_перезапуск_и_помнит_модель(tmp_path):
    p = tmp_path / "q.json"
    к = ЗапросыКэш(p)
    к.положить("Роботы-газонокосилки",
               {"query_en": "robotic lawn mower", "keyphrases": ["robot mower"]},
               "ollama:qwen2.5:7b")
    к2 = ЗапросыКэш(p)
    z = к2.взять("Роботы-газонокосилки")
    assert z["query_en"] == "robotic lawn mower"
    assert z["model"] == "ollama:qwen2.5:7b"
    assert json.loads(p.read_text())


def test_запрос_без_модели_отдаёт_none():
    assert ЗапросыКэш(None).взять("нет такого") is None
