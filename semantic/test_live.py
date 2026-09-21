"""Live-кандидаты без кластеров и без ослабления лексического фильтра."""
from semantic.live import extract_live


def test_live_threshold_and_entities():
    rows = [{'doc_id': str(i), 'title': 'Acme Robotics launches quantum sensor'} for i in range(3)]
    candidates, links, meta = extract_live(rows, 'robotics')
    assert any(c['label'] == 'Acme Robotics' for c in candidates)
    assert all(c['kind'] == 'term' and c['emb_row'] is None for c in candidates)
    assert all(c['n_docs'] == 3 for c in candidates)
    assert len(links) == len(candidates) * 3
    assert meta['entity_candidate_ids']


def test_live_rejects_pandemic_and_rare_entities():
    rows = [{'doc_id': str(i), 'title': 'Covid-19 Pandemic'} for i in range(4)]
    assert extract_live(rows, 'health')[0] == []


def test_entity_uses_technology_context():
    rows = [{'doc_id': str(i), 'title': 'Acme builds quantum sensors'} for i in range(3)]
    assert any(c['label'] == 'Acme' for c in extract_live(rows, 'sensors')[0])
