"""Live-кандидаты без кластеров и без ослабления лексического фильтра."""
from semantic.live import extract_live


def test_ambiguous_company_words_require_company_context_for_each_document():
    for label, unrelated in [
        ('Humanoid', 'XPENG Robotics Raises Funding for Humanoid Robots'),
        ('Run Robotics', 'Funding to Help Run Robotics Training Centre'),
    ]:
        rows = [{'doc_id': '1', 'title': f'{label} raises funding for robotics'},
                {'doc_id': '2', 'title': unrelated}]
        assert not any(c['label'] == label for c in extract_live(rows, 'robotics', min_docs=2)[0])
        rows.append({'doc_id': '3', 'title': f'{label} launches robotics software'})
        candidates, links, _ = extract_live(rows, 'robotics', min_docs=2)
        candidate = next(c for c in candidates if c['label'] == label)
        assert {r['doc_id'] for r in links if r['cand_id'] == candidate['cand_id']} == {'1', '3'}


def test_isaac_products_do_not_share_evidence_between_owners():
    rows = [{'doc_id': 'n1', 'title': 'NVIDIA Isaac ROS advances robotics software'},
            {'doc_id': 'w1', 'title': 'Weave Robotics launches Isaac 1 home robot'}]
    assert not extract_live(rows, 'robotics', min_docs=2)[0]
    rows += [{'doc_id': 'n2', 'title': 'NVIDIA Isaac ROS releases robotics tools'},
             {'doc_id': 'w2', 'title': 'Weave Robotics unveils Isaac 1 robot'}]
    candidates, links, _ = extract_live(rows, 'robotics', min_docs=2)
    for label, docs in [('NVIDIA Isaac', {'n1', 'n2'}), ('Weave Isaac 1', {'w1', 'w2'})]:
        candidate = next(c for c in candidates if c['label'] == label)
        assert {r['doc_id'] for r in links if r['cand_id'] == candidate['cand_id']} == docs
    assert not any(c['label'] == 'Isaac' for c in candidates)


def test_qualified_product_does_not_attribute_reviewed_competitor_to_weave():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Weave Robotics tests NVIDIA Isaac 1.0 robotics software',
        'Weave Robotics evaluates NVIDIA Isaac 1.0 robotics tools',
    ])]
    labels = {c['label'] for c in extract_live(rows, 'robotics', min_docs=2)[0]}
    assert 'NVIDIA Isaac' in labels
    assert 'Weave Isaac 1' not in labels


def test_ambiguous_company_context_uses_normalized_name():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Humanoid launches robotics software',
        'New Humanoid releases robotics software',
    ])]
    candidate = next(c for c in extract_live(rows, 'robotics', min_docs=2)[0]
                     if c['label'] == 'Humanoid')
    assert candidate['n_docs'] == 2


def test_person_mentions_do_not_count_as_product_evidence():
    titles = ['Weave launches Isaac robotics software',
              'Isaac Asimov shaped robotics software',
              "Isaac Asimov's robotics laws"]
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate(titles)]
    assert not extract_live(rows, 'robotics', min_docs=2)[0]
    rows.append({'doc_id': '3', 'title': 'Isaac robotics software released'})
    candidates, links, _ = extract_live(rows, 'robotics', min_docs=2)
    isaac = next(c for c in candidates if c['label'] == 'Isaac')
    assert isaac['n_docs'] == 2
    assert {link['doc_id'] for link in links if link['cand_id'] == isaac['cand_id']} == {'0', '3'}


def test_person_exclusion_keeps_company_in_same_title_and_unrelated_names():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "Travis Kalanick's Atoms improves robotics software",
        'Atoms robotics software reaches production',
        'Asimov launches robotics software',
        'Asimov develops robotics software',
    ])]
    labels = {c['label'] for c in extract_live(rows, 'robotics', min_docs=2)[0]}
    assert {'Atoms', 'Asimov'} <= labels


def test_observed_people_and_places_are_not_company_labels():
    for name in ['Dean Kamen', 'Sebastian Thrun', 'Travis Kalanick',
                 'Afghanistan', 'Korea', 'Utah', 'Pittsburgh', 'Navy']:
        rows = [{'doc_id': str(i), 'title': f"{name}'s robotics software"}
                for i in range(2)]
        assert not extract_live(rows, 'robotics', min_docs=2)[0], name


def test_robotics_generic_headline_fragments_are_not_entities():
    for name in ['Funding', 'Top Funding', 'Week', 'Powerful', 'Robotic',
                 'Robotics Lab', 'High School Robotics', 'Three Laws', 'Taps Meta']:
        rows = [{'doc_id': str(i), 'title': f"{name}'s robotics software"}
                for i in range(2)]
        assert not extract_live(rows, 'robotics', min_docs=2)[2]['entity_candidate_ids'], name


def test_robotics_distinctive_names_survive_generic_word_filter():
    for name in ['Generalist', 'Humanoid', 'World Labs', 'Agility Robotics', 'Isaac']:
        rows = [{'doc_id': str(i), 'title': f'{name} launches robotics software'}
                for i in range(2)]
        assert any(c['label'] == name for c in extract_live(
            rows, 'robotics', min_docs=2)[0]), name


def test_live_support_threshold_is_explicit_and_never_single_document():
    import pytest

    rows = [{'doc_id': str(i), 'title': 'Acme launches cybersecurity software'}
            for i in range(2)]
    assert any(c['label'] == 'Acme' for c in extract_live(rows, 'cyber', min_docs=2)[0])
    assert not extract_live(rows, 'cyber', min_docs=3)[0]
    with pytest.raises(ValueError):
        extract_live(rows, 'cyber', min_docs=1)


def test_two_document_threshold_rejects_generic_titles_and_known_people():
    for name in ['AI-powered', 'Best Scientific Cybersecurity Paper', 'Version',
                 'Josh Brown', 'Vinod Paul']:
        rows = [{'doc_id': str(i), 'title': f"{name}'s cybersecurity software"}
                for i in range(2)]
        assert not extract_live(rows, 'cyber', min_docs=2)[2]['entity_candidate_ids'], name


def test_guide_in_saved_headlines_is_not_a_product():
    titles = [
        'Top Quantum Software Companies 2026: The Definitive Stack Guide',
        "Smartening the Telecom Edge: An Operator's Guide to LLM deployment "
        'and Inference Optimisation',
        'Running LLMs on Raspberry Pi and Edge Devices: A Practical Guide',
    ]
    candidates, _, _ = extract_live(
        [{'doc_id': str(i), 'title': t} for i, t in enumerate(titles)], 'ai')
    assert not any(c['label'].casefold() == 'guide' for c in candidates)


def test_common_words_cannot_accumulate_entity_evidence():
    words = ['Guide', 'AGent', 'Agentic', 'Behavior', 'Controls', 'Database',
             'Edge', 'First', 'Identity', 'Industry', 'Law', 'Network', 'Neuromorphic',
             'Next', 'Payments', 'Problem', 'Protocol', 'Roadmap', 'Robotics',
             'Rules', 'Signature', 'Web', 'Where', 'Who', 'With', 'World',
             'AI Strategy', 'First Agentic AI Phone', 'Full-Stack Safety System']
    for word in words:
        rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
            f"Acme's {word} introduces AI cybersecurity software",
            f'AI cybersecurity with {word.lower()}',
            f'AI cybersecurity tools and {word.lower()}',
        ])]
        assert not extract_live(rows, 'ai')[2]['entity_candidate_ids'], word


def test_distinctive_names_keep_common_words_without_losing_technical_terms():
    for name in ['Guidewire', 'Acme Network', 'Applied Computing', 'IdentityGuard',
                 'World Labs', 'Path Robotics', 'AGentShield']:
        rows = [{'doc_id': str(i), 'title': f'{name} launches neuromorphic computing tools'}
                for i in range(3)]
        candidates, _, _ = extract_live(rows, 'ai')
        assert {name, 'neuromorphic computing'} <= {c['label'] for c in candidates}


def test_known_person_region_and_policy_group_are_not_companies():
    for name in ['Elon Musk', 'Silicon Valley', 'G7']:
        rows = [{'doc_id': str(i), 'title': f"{name}'s AI cybersecurity strategy"}
                for i in range(3)]
        assert not extract_live(rows, 'ai')[2]['entity_candidate_ids'], name


def test_proof_brand_and_fido_product_seed_survive_generic_word_filter():
    titles = [
        'Proof’s VDC launch brings together banking regulation, reusable identity and AI agents',
        'Proof Joins FIDO Alliance to Link AI Agent Actions to Verified Human Identity',
        'Proof’s FIDO Alliance membership to shape AI agent standards',
        'OpenAI joins FIDO Alliance to help AI agent authentication push',
    ]
    candidates, _, _ = extract_live(
        [{'doc_id': str(i), 'title': t} for i, t in enumerate(titles)], 'ai')
    labels = {c['label'] for c in candidates}
    assert {'Proof', 'FIDO Alliance'} <= labels


def test_generic_looking_owner_does_not_remove_distinctive_product():
    titles = ["Identity's ShieldGuard improves cybersecurity", 'ShieldGuard encryption tools',
              'Testing ShieldGuard cybersecurity software']
    candidates, _, _ = extract_live(
        [{'doc_id': str(i), 'title': t} for i, t in enumerate(titles)], 'ai')
    assert 'ShieldGuard' in {c['label'] for c in candidates}


def test_cybersecurity_company_mentions_have_technical_context():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches cybersecurity service',
        'Acme cybersecurity tools enter production',
        'Testing Acme encryption software',
    ])]
    assert any(c['label'] == 'Acme' and c['n_docs'] == 3
               for c in extract_live(rows, 'cybersecurity')[0])


def test_product_after_launch_has_observed_support():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches ShieldGuard for cybersecurity',
        'ShieldGuard improves encryption',
        'Testing ShieldGuard cybersecurity software',
    ])]
    candidates, _, _ = extract_live(rows, 'cybersecurity')
    assert any(c['label'] == 'ShieldGuard' and c['n_docs'] == 3 for c in candidates)
    assert not any(c['label'] == 'Acme' for c in candidates)


def test_title_case_verb_and_owned_product():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme Launches ShieldGuard for cybersecurity',
        "Acme's ShieldGuard improves encryption",
        'Testing ShieldGuard cybersecurity software',
    ])]
    assert any(c['label'] == 'ShieldGuard' and c['n_docs'] == 3
               for c in extract_live(rows, 'cybersecurity')[0])


def test_cyber_context_does_not_admit_disease_or_generic_product():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "Cancer launches New AI for cybersecurity",
        "Cancer's AI improves cybersecurity", 'Cancer and AI cybersecurity software',
    ])]
    assert not extract_live(rows, 'cybersecurity')[2]['entity_candidate_ids']


def test_policy_and_generic_subjects_are_not_technology_companies():
    subjects = ['Cybersecurity', 'Cybersecurity Firm', 'Germany', 'Japan',
                'It', 'Nation', 'State', 'White House', 'CISA', 'NSA',
                'New Cybersecurity Platform']
    for subject in subjects:
        rows = [{'doc_id': str(i), 'title': f'{subject} launches cybersecurity initiative'}
                for i in range(3)]
        assert not extract_live(rows, 'security')[2]['entity_candidate_ids'], subject


def test_product_name_stops_at_sentence_boundary():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches ShieldGuard. Encryption improves',
        'ShieldGuard encryption tools', 'Testing ShieldGuard encryption',
    ])]
    assert any(c['label'] == 'ShieldGuard' for c in extract_live(rows, 'security')[0])


def test_pronoun_possessive_is_not_product_owner():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "It's Time to improve cybersecurity", 'Time for encryption',
        'Time to test cybersecurity software',
    ])]
    assert not extract_live(rows, 'security')[2]['entity_candidate_ids']


def test_related_product_name_is_not_an_implicit_alias():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches ShieldGuard for cybersecurity',
        'ShieldGuard encryption tools', 'Sec-ShieldGuard encryption software',
    ])]
    assert not extract_live(rows, 'security')[2]['entity_candidate_ids']


def test_dotted_name_is_not_an_implicit_alias():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches cybersecurity service', 'Acme encryption software',
        'Acme.org funds cybersecurity research',
    ])]
    assert not extract_live(rows, 'security')[2]['entity_candidate_ids']


def test_seed_cannot_start_inside_hyphenated_or_dotted_name():
    for separator in ['-', '.']:
        rows = [{'doc_id': str(i), 'title': f'{prefix}{separator}Sec launches encryption tools'}
                for i, prefix in enumerate(['open', 'other', 'another'])]
        assert not extract_live(rows, 'security')[2]['entity_candidate_ids']


def test_political_person_is_not_a_company():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "Senator Smith's cybersecurity initiative", 'Senator Smith cybersecurity policy',
        'Senator Smith discusses encryption',
    ])]
    assert not extract_live(rows, 'security')[2]['entity_candidate_ids']


def test_startup_description_is_not_part_of_company_name():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Italian Cybersecurity Startup Acme Raises Funding',
        'Cybersecurity Startup Acme Launches New Service',
        'Acme encryption software enters production',
        'Senator launches cybersecurity initiative',
        'Senator cybersecurity policy', 'Senator discusses cybersecurity',
    ])]
    candidates, _, meta = extract_live(rows, 'security')
    entities = [c['label'] for c in candidates if c['cand_id'] in meta['entity_candidate_ids']]
    assert entities == ['Acme']


def test_no_sentence_fragments():
    rows = [{'doc_id': str(i), 'title': 'Algorithms for fault detection using machine learning'}
            for i in range(3)]
    labels = {c['label'].casefold() for c in extract_live(rows, 'ai')[0]}
    assert 'machine learning' in labels
    assert 'algorithms for fault' not in labels
    assert 'algorithms' not in labels
    assert 'detection using machine learning' not in labels


def test_modern_technology_names_and_alias_evidence():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches retrieval augmented generation with LoRA and vector databases',
        'Beta builds RAG with LoRA and vector databases',
        'Gamma launches RAG with LoRA and vector databases',
    ])]
    candidates, links, _ = extract_live(rows, 'ai')
    by_label = {c['label']: c for c in candidates}
    assert {'retrieval augmented generation', 'LoRA', 'vector database'} <= by_label.keys()
    for label in ['retrieval augmented generation', 'LoRA', 'vector database']:
        c = by_label[label]
        assert c['n_docs'] == 3
        assert len([link for link in links if link['cand_id'] == c['cand_id']]) == 3


def test_catalogue_does_not_invent_absent_names():
    rows = [{'doc_id': str(i), 'title': 'Acme launches quantum sensors'} for i in range(3)]
    assert 'LoRA' not in {c['label'] for c in extract_live(rows, 'ai')[0]}


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


def test_entity_seed_counts_other_observed_mentions():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'Acme launches quantum sensors',
        'Quantum sensors from Acme enter production',
        'Testing Acme quantum sensors',
    ])]
    candidates, links, _ = extract_live(rows, 'sensors')
    candidate = next(c for c in candidates if c['label'] == 'Acme')
    assert candidate['n_docs'] == 3
    assert len([r for r in links if r['cand_id'] == candidate['cand_id']]) == 3


def test_company_possessive_in_technical_news():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "Acme's new quantum sensor enters production",
        'Acme builds quantum sensors',
        'Testing Acme quantum sensors',
    ])]
    assert any(c['label'] == 'Acme' for c in extract_live(rows, 'sensors')[0])


def test_publisher_mentions_do_not_inflate_entity_support():
    rows = [{'doc_id': str(i), 'title': title, 'source': 'gnews'}
            for i, title in enumerate([
                'Acme launches quantum sensors - Journal',
                'New quantum sensors - Acme',
                'Optical sensors improve - Acme',
            ])]
    assert not any(c['label'] == 'Acme' for c in extract_live(rows, 'sensors')[0])


def test_generic_capitals_are_not_companies():
    rows = [{'doc_id': str(i), 'title': "Here AI's Brain builds quantum sensors"}
            for i in range(3)]
    candidates, _, meta = extract_live(rows, 'sensors')
    assert not meta['entity_candidate_ids']
    assert candidates


def test_disease_does_not_become_company_in_technology_context():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        "Cancer's neural networks", 'Cancer research uses neural networks',
        'New neural networks predict cancer',
    ])]
    assert not extract_live(rows, 'health')[2]['entity_candidate_ids']


def test_noun_plural_and_hyphen_variants_share_evidence():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'New quantum sensor', 'New quantum sensors', 'New quantum-sensors',
    ])]
    candidates, _, _ = extract_live(rows, 'sensors')
    assert [(c['label'], c['n_docs']) for c in candidates] == [('quantum sensor', 3)]


def test_entity_prefix_and_duplicate_technology():
    rows = [{'doc_id': str(i), 'title': title} for i, title in enumerate([
        'New Acme launches quantum sensors', 'Acme builds quantum sensors',
        'The Acme deploys quantum sensors',
        'Neural Networks releases quantum sensors',
        'Neural Networks builds quantum sensors',
        'Neural Networks launches quantum sensors',
    ])]
    candidates, _, meta = extract_live(rows, 'sensors')
    entities = [c['label'] for c in candidates if c['cand_id'] in meta['entity_candidate_ids']]
    assert entities == ['Acme']


def test_build_live_retains_source_for_publisher_filter(tmp_path, monkeypatch):
    import json
    import sys

    import pyarrow as pa
    import pyarrow.parquet as pq
    import pytest

    from semantic import build, live

    works = tmp_path / 'works.parquet'
    pq.write_table(pa.Table.from_pylist([{
        'doc_id': '1', 'title': 'Quantum sensor - Acme', 'abstract': None,
        'domain': 'test', 'year': 2026, 'source': 'gnews',
    }]), works)
    works.with_name('meta.json').write_text(json.dumps({
        'domain': 'test', 'n_docs': 1, 'corpus_sha256': build.fingerprint(works),
    }))

    class Captured(Exception):
        pass

    observed_thresholds = []

    def capture(rows, domain, *, min_docs):
        assert rows[0]['source'] == 'gnews'
        observed_thresholds.append(min_docs)
        raise Captured

    monkeypatch.setattr(live, 'extract_live', capture)
    monkeypatch.setattr(sys, 'argv', ['build', '--domain', 'test', '--works', str(works),
                                    '--output', str(tmp_path / 'index'), '--cache',
                                    str(tmp_path / 'cache'), '--scope', 'live', '--as-of', '2026'])
    with pytest.raises(Captured):
        build.main()
    assert observed_thresholds == [2]
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--min-docs', '3'])
    with pytest.raises(Captured):
        build.main()
    assert observed_thresholds == [2, 3]
    monkeypatch.setattr(sys, 'argv', [*sys.argv, '--min-docs', '1'])
    with pytest.raises(SystemExit) as error:
        build.main()
    assert error.value.code == 2
    assert observed_thresholds == [2, 3]
