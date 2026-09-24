"""Проверка правил доверенности и защиты от подмены домена."""
import pytest

from ingest.trust import classify, normalize_host


@pytest.mark.parametrize('value', ['https://arxiv.org/abs/123', 'WWW.ARXIV.ORG.',
                                  'https://export.arxiv.org/api/query'])
def test_known_domain_and_subdomains(value):
    result = classify(value)
    assert result.trust_level == 'trusted'
    assert result.source_type == 'preprint'
    assert result.rule_domain == 'arxiv.org'


@pytest.mark.parametrize('value', ['arxiv.org.evil.example', 'fakearxiv.org',
                                  'https://evil.example/arxiv.org',
                                  'https://arxiv.org@evil.example/path'])
def test_imitation_never_inherits_trust(value):
    assert classify(value).trust_level == 'unknown'


@pytest.mark.parametrize('value', ['', 'file:///arxiv.org', 'javascript:arxiv.org',
                                  'https://arxiv.org:bad/x', 'https://arxiv.org\\@evil.test',
                                  'https://arxiv.org\n.evil.test', 'https://user@arxiv.org'])
def test_malformed_input_not_trusted(value):
    assert classify(value).trust_level == 'unknown'


def test_specific_aggregator_overrides_company_domain():
    assert classify('news.ycombinator.com').trust_level == 'indicator'
    assert classify('news.ycombinator.com').source_type == 'aggregator'
    assert classify('news.google.com').trust_level == 'indicator'


@pytest.mark.parametrize('domain', ['prnewswire.com', 'medium.com', 'x.com', 'reddit.com'])
def test_indicators(domain):
    assert classify(domain).trust_level == 'indicator'


@pytest.mark.parametrize('domain', ['openalex.org', 'nature.com', 'github.com',
                                  'huggingface.co', 'techcrunch.com', 'siliconangle.com',
                                  'venturebeat.com', 'theregister.com', 'eetimes.com'])
def test_brief_sources(domain):
    assert classify(domain).trust_level == 'trusted'


def test_unknown_is_explicit():
    result = classify('new-university.example')
    assert result.trust_level == 'unknown'
    assert result.source_type is None
    assert result.rule_domain is None
    assert result.reason


def test_normalized_international_host():
    assert normalize_host('https://ПРИМЕР.РФ/статья') == 'xn--e1afmkfd.xn--p1ai'


def test_dataset_has_explicit_source_decisions():
    import json
    from pathlib import Path

    from ingest.trust import DATASET_RULES

    dataset = json.loads(
        Path(__file__).with_name('dataset_sources.json').read_text(encoding='utf-8'))
    assert dataset['technology_rows'] == 100
    assert dataset['link_count'] == 285
    domains = [item['domain'] for item in dataset['domains']]
    assert len(domains) == len(set(domains)) == 206
    assert set(domains) == set(DATASET_RULES)
    for domain in domains:
        rule = DATASET_RULES[domain]
        assert rule['reason']
        assert rule['trust_level'] in {'trusted', 'indicator', 'unknown'}
        assert classify(domain).trust_level == rule['trust_level']
        if rule['trust_level'] != 'unknown':
            assert rule['evidence']


@pytest.mark.parametrize('domain', ['businesswire.com', 'globenewswire.com', 'accessnewswire.com'])
def test_press_release_distributors_are_indicators(domain):
    assert classify(domain).trust_level == 'indicator'
    assert classify(domain).source_type == 'press_release'


@pytest.mark.parametrize('domain,level', [
    ('1kosmos.com', 'trusted'), ('securityweek.com', 'trusted'),
    ('pmc.ncbi.nlm.nih.gov', 'trusted'), ('agenticindex.io', 'indicator'),
    ('neutronrise.com', 'indicator'), ('abovea.tech', 'unknown'),
])
def test_reviewed_source_categories(domain, level):
    assert classify(domain).trust_level == level


def test_source_review_has_no_pending_entries():
    from ingest.trust import DATASET_RULES

    for rule in DATASET_RULES.values():
        assert rule['review_status'] != 'needs_review'
        if rule['review_status'].startswith('unresolved_'):
            assert rule['trust_level'] == 'unknown'
        if rule['review_status'] == 'reviewed_first_party':
            assert rule['reviewed_on']
            assert rule['evidence']
            assert rule['source_category']
