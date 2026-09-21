"""Публичные RSS; сетевые операции выполняет только NewsClient."""
import calendar
from datetime import UTC, datetime

import feedparser

from ingest.normalize import news_record
from ingest.trust import classify

FEEDS = {
    'techcrunch': 'https://techcrunch.com/feed/',
    'siliconangle': 'https://siliconangle.com/feed/',
    'venturebeat': 'https://venturebeat.com/feed/',
    'theregister': 'https://www.theregister.com/headlines.atom',
    'eetimes': 'https://www.eetimes.com/feed/',
}


def parse_feed(body, source, domain, harvested_at, *, lang='en'):
    feed = feedparser.parse(body)
    if not feed.version:
        raise ValueError('Источник не вернул RSS/Atom')
    rows = []
    for entry in feed.entries:
        published = entry.get('published_parsed')
        if not published:
            continue
        try:
            date = datetime.fromtimestamp(calendar.timegm(published), UTC).isoformat()
            url = entry.get('link', '')
            trust = classify(url)
            rows.append(news_record(source, entry.get('title'), url, date,
                                    domain, harvested_at, lang=lang,
                                    source_type=trust.source_type or 'news'))
        except (ValueError, OverflowError, TypeError):
            continue
    return rows


async def collect(client, name, domain, harvested_at):
    return parse_feed(await client.get(FEEDS[name]), 'rss', domain, harvested_at)
