"""RSS: даты и доверенность оригинальной ссылки."""
import pytest

from ingest.sources.rss import parse_feed


def test_rss_skips_undated_and_preserves_origin():
    body = b'''<rss version="2.0"><channel><title>Test</title>
    <item><title>Robot pilot</title><link>https://techcrunch.com/robot</link>
    <pubDate>Fri, 18 Sep 2026 12:00:00 GMT</pubDate></item>
    <item><title>No date</title><link>https://techcrunch.com/no-date</link></item>
    </channel></rss>'''
    rows = parse_feed(body, 'rss', 'robotics', '2026-09-19', lang='en')
    assert len(rows) == 1
    assert rows[0]['year'] == 2026
    assert rows[0]['trust_level'] == 'trusted'
    assert rows[0]['source_type'] == 'news'


def test_google_wrapper_does_not_inherit_publisher_trust():
    body = b'''<rss version="2.0"><channel><item><title>Robot - Nature</title>
    <link>https://news.google.com/rss/articles/123</link>
    <source url="https://nature.com">Nature</source>
    <pubDate>Fri, 18 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'''
    row = parse_feed(body, 'gnews', 'robotics', '2026-09-19', lang='en')[0]
    assert row['trust_level'] == 'indicator'
    assert row['source_type'] == 'aggregator'


def test_html_is_not_a_feed():
    with pytest.raises(ValueError):
        parse_feed(b'<html><body>Access denied</body></html>', 'rss', 'robot', '2026-09-19')
