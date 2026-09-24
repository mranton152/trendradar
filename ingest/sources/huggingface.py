"""Публичный поиск моделей; likes и downloads сохраняются в сыром кэше."""
import json

from ingest.normalize import from_huggingface


async def collect(client, query, domain, harvested_at, *, limit=100):
    payload = json.loads(await client.get('https://huggingface.co/api/models', {
        'search': query, 'limit': max(1, min(limit, 100)), 'full': 'true',
    }))
    rows = []
    for record in payload:
        try:
            rows.append(from_huggingface(record, domain, harvested_at))
        except ValueError:
            continue
    return rows
