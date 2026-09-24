"""Явные правила источников из брифа; доверенность не заменяет проверку материала."""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SourceTrust:
    trust_level: str
    source_type: str | None
    rule_domain: str | None
    reason: str


# Только подтверждённые брифом правила. Незнакомые домены не повышаем автоматически.
RULES = {
    'arxiv.org': ('trusted', 'preprint'),
    'openalex.org': ('trusted', 'article'),
    'nature.com': ('trusted', 'article'),
    'github.com': ('trusted', 'repo'),
    'huggingface.co': ('trusted', 'model'),
    'techcrunch.com': ('trusted', 'news'),
    'siliconangle.com': ('trusted', 'news'),
    'venturebeat.com': ('trusted', 'news'),
    'theregister.com': ('trusted', 'news'),
    'eetimes.com': ('trusted', 'news'),
    'prnewswire.com': ('indicator', 'press_release'),
    'medium.com': ('indicator', 'blog'),
    'x.com': ('indicator', 'blog'),
    'reddit.com': ('indicator', 'aggregator'),
    'news.ycombinator.com': ('indicator', 'aggregator'),
    'news.google.com': ('indicator', 'aggregator'),
}


DATASET_RULES = json.loads(
    Path(__file__).with_name('source_trust.json').read_text(encoding='utf-8'))


def normalize_host(value: str) -> str | None:
    """Принимает HTTP(S) URL или домен; отвергает неоднозначные адреса."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return None
    if '\\' in value:
        return None
    try:
        parsed = urlsplit(value if '://' in value else '//'+value)
        if parsed.scheme and parsed.scheme.lower() not in {'http', 'https'}:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        # Чтение порта выявляет некорректные числовые значения.
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return None
        host = (parsed.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
    except (ValueError, UnicodeError):
        return None
    if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x)
                                  for x in host.split('.')):
        return None
    return host


def classify(value: str) -> SourceTrust:
    """Возвращает наиболее специфичное доменное правило либо unknown."""
    host = normalize_host(value)
    if host:
        for domain in sorted(RULES.keys() | DATASET_RULES.keys(), key=len, reverse=True):
            if host == domain or host.endswith('.'+domain):
                if domain in DATASET_RULES:
                    rule = DATASET_RULES[domain]
                    return SourceTrust(rule['trust_level'], rule['source_type'],
                                       domain, rule['reason'])
                level, kind = RULES[domain]
                return SourceTrust(level, kind, domain, 'Правило team/PROMPT-konstantin.md')
    return SourceTrust('unknown', None, None, 'Нет явного правила или некорректный URL')
