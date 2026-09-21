"""Google News RSS: неподтверждённый URL оболочки остаётся индикатором."""
from ingest.sources.rss import parse_feed


async def collect(client, query, domain, harvested_at, *, lang='en'):
    if lang not in {'en', 'ru'}:
        raise ValueError('Поддерживаются en и ru')
    body = await client.get('https://news.google.com/rss/search', {
        'q': query, 'hl': lang, 'gl': 'US' if lang == 'en' else 'RU',
        'ceid': 'US:en' if lang == 'en' else 'RU:ru',
    })
    return parse_feed(body, 'gnews', domain, harvested_at, lang=lang)
