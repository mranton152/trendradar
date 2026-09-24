"""Репозитории и модели используют дату создания, а не обновления."""
import pytest

from ingest.normalize import from_github, from_huggingface


def test_github_creation_and_no_fake_citations():
    row = from_github({'full_name': 'org/robot', 'html_url': 'https://github.com/org/robot',
                       'created_at': '2024-01-01T00:00:00Z',
                       'updated_at': '2026-01-01T00:00:00Z', 'stargazers_count': 100},
                      'robotics', '2026-09-19')
    assert row['year'] == 2024
    assert row['source_type'] == 'repo'
    assert row['cited_by'] is None


def test_hf_creation_and_identity():
    row = from_huggingface({'id': 'org/model', 'createdAt': '2025-01-01T00:00:00Z',
                            'likes': 20}, 'robotics', '2026-09-19')
    assert row['url'] == 'https://huggingface.co/org/model'
    assert row['year'] == 2025
    assert row['source_type'] == 'model'
    assert row['trust_level'] == 'trusted'


def test_hf_rejects_path_traversal():
    with pytest.raises(ValueError):
        from_huggingface({'id': '../model', 'createdAt': '2025-01-01'}, 'robotics', '2026-09-19')
