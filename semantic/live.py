"""Лексические live-кандидаты; сущности — гипотезы по капитализации."""
import hashlib
import re
from collections import defaultdict

from semantic.filter import technology_reason
from semantic.terms import extract_terms


def extract_live(rows, domain):
    candidates, links, meta = extract_terms(rows, domain, min_docs=3)
    entities = defaultdict(set)
    for row in rows:
        if technology_reason(row['title']) is not None:
            continue
        for match in re.finditer(r'\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3}\b',
                                 row['title'][:4096]):
            label = match.group()
            if label.casefold() not in {'the', 'new', 'this', 'how', 'why', 'what', 'a', 'an'}:
                entities[label].add(row['doc_id'])
    entity_ids = []
    existing = {c['label'].casefold(): c for c in candidates}
    for label, docs in sorted(entities.items()):
        if len(docs) < 3:
            continue
        if label.casefold() in existing:
            candidate = existing[label.casefold()]
            candidate['label'] = label
            entity_ids.append(candidate['cand_id'])
            continue
        cand_id = 'e:' + hashlib.sha256((domain + '\0' + label).encode()).hexdigest()[:24]
        candidates.append({'cand_id': cand_id, 'kind': 'term', 'label': label,
                           'aliases': [], 'top_terms': [label], 'emb_row': None,
                           'n_docs': len(docs), 'domain': domain})
        links.extend({'cand_id': cand_id, 'doc_id': doc, 'weight': 1.0} for doc in sorted(docs))
        entity_ids.append(cand_id)
    meta.update(entity_method='capitalization_with_technology_filter',
                entity_candidate_ids=entity_ids, n_candidates=len(candidates), n_links=len(links))
    return candidates, links, meta
