"""Публичный поиск HN через Algolia; исходные очки и URL остаются в кэше."""
import asyncio
import json

import httpx

from ingest.normalize import from_hackernews
from ingest.sources.partial import PartialCollectionError


async def collect(client, query, domain, harvested_at, *, pages=3):
    rows = []
    for page in range(max(0, min(pages, 10))):
        try:
            payload = json.loads(await client.get('https://hn.algolia.com/api/v1/search', {
                'query': query, 'tags': 'story', 'hitsPerPage': 100, 'page': page,
            }))
        except (asyncio.CancelledError, TimeoutError, httpx.HTTPError,
                ValueError, FileNotFoundError) as error:
            raise PartialCollectionError(rows, type(error).__name__) from error
        for record in payload.get('hits', []):
            try:
                rows.append(from_hackernews(record, domain, harvested_at))
            except ValueError:
                continue
        if page + 1 >= payload.get('nbPages', 0):
            break
    return rows
