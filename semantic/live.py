"""Названия технологий и контекстные имена: без сырого пула n-грамм."""
import hashlib
import re
from collections import defaultdict

from semantic.filter import technology_reason

# Явные названия, не результат LLM и не готовые кандидаты: нужны упоминания.
# Регистр аббревиатур сохраняется, чтобы rag/lora как обычные слова не давали сигнал.
_NAMES = {
    'prompt engineering': r'(?i:prompt[- ]engineering)',
    'retrieval augmented generation': r'(?i:retrieval[- ]augmented[- ]generation)|RAG',
    'mixture of experts': r'(?i:mixture[- ]of[- ]experts)|MoE',
    'LoRA': r'LoRA|(?i:low[- ]rank adaptation)',
    'vector database': r'(?i:vector databases?)',
    'differentiable rendering': r'(?i:differentiable rendering)',
    'machine learning': r'(?i:machine learning)',
    'deep learning': r'(?i:deep learning)',
    'large language model': r'(?i:large language models?)|LLMs?',
    'small language model': r'(?i:small language models?)|SLMs?',
    'federated learning': r'(?i:federated learning)',
    'confidential computing': r'(?i:confidential computing)',
    'post-quantum cryptography': r'(?i:post[- ]quantum cryptography)',
    'zero trust': r'(?i:zero[- ]trust)',
    'prompt injection': r'(?i:prompt[- ]injection)',
    'machine unlearning': r'(?i:machine unlearning)',
    'AI agent': r'(?i:AI agents?|agentic AI)',
    'synthetic data': r'(?i:synthetic data)',
    'neuromorphic computing': r'(?i:neuromorphic computing)',
}
_PATTERNS = {name: re.compile(r'(?<!\w)(?:' + pattern + r')(?!\w)')
             for name, pattern in _NAMES.items()}
# Открытая комбинация технических определений и предметных существительных.
_NOUN = re.compile(
    r'\b(?:quantum|neural|photonic|optical|neuromorphic|tactile|autonomous|'
    r'robotic|biomedical|semiconductor|adaptive|generative|federated)'
    r'(?:[- ](?:quantum|neural|photonic|optical|vision|language|edge|memory))*'
    r'[- ](?:sensors?|processors?|networks?|computing|robotics|models?|'
    r'learning|chips?|vision|actuators?|imaging)\b', re.IGNORECASE)
# Имена не извлекаются из любого слова с заглавной буквы: нужен контекст действия.
_NAME_TOKEN = r'[A-Z][A-Za-z0-9&-]*(?:\.[A-Za-z0-9&-]+)*'
_CAPITAL_NAME = _NAME_TOKEN + r'(?:[ \t]+' + _NAME_TOKEN + r'){0,3}'
_ENTITY = re.compile(
    r'(?<![\w.-])(' + _CAPITAL_NAME + r')'
    r'[ \t]+(?i:launches|builds|raises|unveils|introduces|develops|releases|'
    r'announces|secures|deploys|partners|acquires)\b')
_POSSESSIVE = re.compile(r"(?<![\w.-])(" + _CAPITAL_NAME + r")[’']s\b")
_PRODUCT = re.compile(
    r'\b(?i:launches|unveils|introduces|releases|deploys)\s+('
    + _CAPITAL_NAME + r')')
_OWNED_PRODUCT = re.compile(r"(?<![\w.-])(" + _CAPITAL_NAME + r")[’']s\s+("
                            + _CAPITAL_NAME + r')')
_COMPANY_DESCRIPTION = re.compile(
    r'^(?:(?:Italian|Nigerian|French|German|American|British|Israeli|Indian|'
    r'Canadian|Australian|Japanese|European|Swiss|Swedish|Finnish|Dutch)\s+)?'
    r'(?:(?:Cybersecurity|AI|Robotics|Biotech|Quantum)\s+)?'
    r'(?:Startup|Company|Firm)\s+', re.IGNORECASE)
_STOP_NAMES = {'the', 'new', 'this', 'how', 'why', 'what', 'a', 'an',
               'algorithms', 'researchers', 'scientists', 'study', 'report',
               'company', 'startup', 'team', 'government', 'china', 'us',
               'here', 'there', 'ai', 'brain', 'llm', 'llms', 'technology',
               'technologies', 'quantum', 'robot', 'robots', 'model', 'models',
               'it', 'its', 'he', 'she', 'they', 'we', 'you', 'our', 'their',
               'nation', 'state', 'city', 'country', 'federal', 'national',
               'cybersecurity', 'cyber', 'security', 'firm', 'firms', 'companies',
               'encryption', 'cryptography', 'intelligence', 'artificial',
               'platform', 'platforms', 'tool', 'tools', 'software', 'service', 'services',
               'senator', 'minister', 'president', 'ministry', 'governor', 'mayor'}
# Заглавная буква в заголовке не превращает обычное слово в имя.
# Только отсев названия, не владельца продукта: Identity's ShieldGuard может
# дать ShieldGuard при независимых упоминаниях, но не кандидата Identity.
_GENERIC_NAME_WORDS = {
    'guide', 'guides', 'agent', 'agents', 'agentic', 'behavior', 'behaviour',
    'control', 'controls', 'database', 'databases', 'edge', 'first', 'identity',
    'identities', 'industry', 'law', 'network', 'networks', 'neuromorphic',
    'next', 'payment', 'payments', 'problem', 'problems', 'protocol',
    'protocols', 'roadmap', 'robotics', 'rule', 'rules', 'signature', 'signatures',
    'web', 'where', 'who', 'with', 'without', 'world', 'strategy', 'strategies',
    'phone', 'phones', 'full-stack', 'safety', 'system', 'systems',
    'ai-powered', 'best', 'scientific', 'paper', 'papers', 'version', 'versions',
    'funding', 'top', 'week', 'powerful', 'robotic', 'lab', 'high', 'school',
}
# Подтверждённые фрагменты заголовков, а не названия продуктов/компаний.
_HEADLINE_FRAGMENTS = {'three laws', 'taps meta'}
# Подтверждённые омонимы: обычного совпадения строки недостаточно.
_AMBIGUOUS_NAMES = {'humanoid', 'run robotics'}
_QUALIFIED_PRODUCTS = {
    'NVIDIA Isaac': re.compile(r'\bNVIDIA(?:[’\']s)?\s+Isaac\b', re.IGNORECASE),
    'Weave Isaac 1': re.compile(
        r'\bWeave Robotics(?:[’\']s)?\s+'
        r'(?:(?:launches|unveils|introduces|releases)\s+)?Isaac\s+1(?![\w-]|\.\d)',
        re.IGNORECASE),
}


def normalized_entity_name(label):
    words = label.strip().split()
    while words and words[0].casefold() in {'the', 'new', 'this', 'a', 'an'}:
        words.pop(0)
    return _COMPANY_DESCRIPTION.sub('', ' '.join(words))


def ambiguous_company_context(label, title):
    """Для омонимов требуем явного действия компании или притяжательного имени."""
    return any(normalized_entity_name(match.group(1)).casefold() == label
               for pattern in (_ENTITY, _POSSESSIVE) for match in pattern.finditer(title))


# Полное известное имя не является упоминанием одноимённого продукта.
# Фамилии отдельно не запрещаем: Asimov может быть названием компании.
_PERSON_NAMES = {'isaac asimov', 'dean kamen', 'sebastian thrun', 'travis kalanick',
                 'elon musk', 'josh brown', 'vinod paul'}
_PERSON_PATTERN = re.compile(
    r'(?<![\w.-])(?:' + '|'.join(re.escape(n) for n in sorted(_PERSON_NAMES))
    + r')(?![\w-]|\.[A-Za-z0-9])', re.IGNORECASE)
# Это отсев явных общественно-политических сущностей, не справочник компаний.
# Полноценный NER здесь не заявляется: незнакомое имя остаётся гипотезой.
_NON_COMPANIES = {
    'germany', 'japan', 'france', 'india', 'canada', 'australia', 'ukraine',
    'israel', 'iran', 'brazil', 'italy', 'spain', 'europe', 'european union',
    'uk', 'usa', 'eu', 'white house', 'congress', 'senate', 'parliament',
    'cisa', 'nsa', 'fbi', 'cia', 'nist', 'fcc', 'hhs', 'irs', 'enisa',
    'elon musk', 'silicon valley', 'g7',
    'josh brown', 'vinod paul',
    'afghanistan', 'korea', 'utah', 'pittsburgh', 'navy',
}
_SINGULAR = dict(zip(
    ('sensors', 'processors', 'networks', 'models', 'chips', 'actuators'),
    ('sensor', 'processor', 'network', 'model', 'chip', 'actuator'), strict=True))


def noun_label(surface):
    words = surface.casefold().replace('-', ' ').split()
    words[-1] = _SINGULAR.get(words[-1], words[-1])
    label = ' '.join(words)
    return next((name for name, pattern in _PATTERNS.items() if pattern.fullmatch(label)), label)


def live_technology_reason(label):
    """Базовый техно-фильтр плюс конечный перечень точных технических названий."""
    reason = technology_reason(label)
    if reason is not None and label not in _NAMES:
        return reason
    return None


def extract_live(rows, domain, *, min_docs=3):
    # Значение API сохранено для прежних вызовов; CLI задаёт свой live-default.
    if isinstance(min_docs, bool) or not isinstance(min_docs, int) or min_docs < 2:
        raise ValueError('Live требует минимум два разных документа')
    if not domain or len({r['doc_id'] for r in rows}) != len(rows):
        raise ValueError('Нужен домен и уникальные doc_id')
    evidence = defaultdict(set)
    surfaces = defaultdict(set)
    contextual_titles = []
    qualified_by_doc = {}
    for row in rows:
        title = row['title'][:4096]
        # Google RSS дописывает издателя: это не упоминание компании в новости.
        if row.get('source') == 'gnews':
            title = title.rsplit(' - ', 1)[0]
        original_title = title
        title = _PERSON_PATTERN.sub(lambda match: ' ' * len(match.group()), title)
        technology_context = technology_reason(title) is None
        for label, pattern in _PATTERNS.items():
            matches = list(pattern.finditer(title))
            if matches:
                # Техно-фильтр применяется; точные названия расширяют его
                # покрытие явно, а не разрешают произвольные строки.
                if live_technology_reason(label) is not None:
                    continue
                technology_context = True
                key = ('technology', label)
                evidence[key].add(row['doc_id'])
                surfaces[key].update(m.group() for m in matches)
        for match in _NOUN.finditer(title):
            label = noun_label(match.group())
            if technology_reason(label) is None:
                key = ('technology', label)
                evidence[key].add(row['doc_id'])
                surfaces[key].add(match.group())
        if technology_context:
            qualified = {name for name, rule in _QUALIFIED_PRODUCTS.items() if rule.search(title)}
            qualified_by_doc[row['doc_id']] = qualified
            for name in qualified:
                key = ('entity', name.casefold())
                evidence[key].add(row['doc_id'])
                surfaces[key].add(name)
            contextual_titles.append((row['doc_id'], title))
            for pattern in (_ENTITY, _POSSESSIVE, _PRODUCT, _OWNED_PRODUCT):
                # Имя основателя не учитываем, но его продукт всё ещё нужен.
                seed_title = original_title if pattern is _OWNED_PRODUCT else title
                for match in pattern.finditer(seed_title):
                    if pattern is _OWNED_PRODUCT:
                        if all(word.casefold() in _STOP_NAMES for word in match.group(1).split()):
                            continue
                        label = match.group(2).strip()
                    else:
                        label = match.group(1).strip()
                    label = normalized_entity_name(label)
                    if qualified and re.search(r'\bisaac\b', label, re.IGNORECASE):
                        continue
                    if label.casefold() in _AMBIGUOUS_NAMES and not ambiguous_company_context(
                            label.casefold(), title):
                        continue
                    if label.split() and label.split()[0].casefold() in {
                            'senator', 'minister', 'president', 'governor', 'mayor'}:
                        continue
                    if label.casefold() in _NON_COMPANIES | _HEADLINE_FRAGMENTS | _PERSON_NAMES:
                        continue
                    if not label or _NOUN.fullmatch(label) or any(
                            rule.fullmatch(label) for rule in _PATTERNS.values()):
                        continue
                    # Компания может не содержать технического слова, но явные
                    # болезни, события и географию нельзя превращать в сущности.
                    if technology_reason(label) not in (None, 'нет технологического маркера'):
                        continue
                    if not all(word.casefold() in _STOP_NAMES | _GENERIC_NAME_WORDS
                               for word in label.split()):
                        key = ('entity', label.casefold())
                        evidence[key].add(row['doc_id'])
                        surfaces[key].add(label)
    # Контекст действия нужен для открытия имени, а не для каждого упоминания.
    # Считаем точные границы имени только в технологическом контексте.
    for key in list(evidence):
        if key[0] != 'entity':
            continue
        pattern = re.compile(r'(?<![\w.-])' + re.escape(key[1])
                             + r'(?![\w-]|\.[A-Za-z0-9])', re.IGNORECASE)
        for doc_id, title in contextual_titles:
            qualified = qualified_by_doc[doc_id]
            if key[1] in {name.casefold() for name in _QUALIFIED_PRODUCTS}:
                continue  # Полные названия уже посчитаны по отдельным правилам.
            if key[1] == 'isaac' and qualified:
                continue
            if key[1] in _AMBIGUOUS_NAMES and not ambiguous_company_context(key[1], title):
                continue
            matches = list(pattern.finditer(title))
            if matches:
                evidence[key].add(doc_id)
                surfaces[key].update(match.group() for match in matches)
    candidates, links, entity_ids = [], [], []
    for (category, label), docs in sorted(evidence.items()):
        if len(docs) < min_docs:
            continue
        digest = hashlib.sha256((domain + '\0' + label.casefold()).encode()).hexdigest()[:24]
        cand_id = ('e:' if category == 'entity' else 't:') + domain + ':' + digest
        mentions = surfaces[(category, label)]
        if category == 'entity':
            label = sorted(mentions)[0]
        aliases = sorted(mentions - {label})
        candidates.append({'cand_id': cand_id, 'kind': 'term', 'label': label,
                           'aliases': aliases, 'top_terms': [label], 'emb_row': None,
                           'n_docs': len(docs), 'domain': domain})
        links.extend({'cand_id': cand_id, 'doc_id': doc, 'weight': 1.0} for doc in sorted(docs))
        if category == 'entity':
            entity_ids.append(cand_id)
    return candidates, links, {
        'method': 'observed_technology_names_and_action_entities_v8', 'min_docs': min_docs,
        'n_documents': len(rows), 'n_candidates': len(candidates), 'n_links': len(links),
        'entity_candidate_ids': entity_ids, 'technology_name_rules': len(_PATTERNS),
        'limitations': 'English rules; incomplete vocabulary; entities are contextual hypotheses',
    }
