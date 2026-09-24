"""Публичный поиск GitHub; stars сохраняются в сыром кэше."""
import asyncio
import json

import httpx

from ingest.normalize import from_github
from ingest.sources.partial import PartialCollectionError


async def collect(client, query, domain, harvested_at, *, pages=1):
    rows = []
    for page in range(1, max(0, min(pages, 10)) + 1):
        try:
            payload = json.loads(await client.get('https://api.github.com/search/repositories', {
                'q': query, 'per_page': 100, 'page': page, 'sort': 'updated',
            }))
        except (asyncio.CancelledError, TimeoutError, httpx.HTTPError,
                ValueError, FileNotFoundError) as error:
            raise PartialCollectionError(rows, type(error).__name__) from error
        items = payload.get('items', [])
        for record in items:
            try:
                rows.append(from_github(record, domain, harvested_at))
            except ValueError:
                continue
        if len(items) < 100:
            break
    return rows
