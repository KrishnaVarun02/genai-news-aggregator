from datetime import timedelta

import httpx
import pytest

from news_aggregator.collectors import collect, fetch_text, parse_feed, plain_text
from news_aggregator.domain import Source, canonical_url

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Authored fixture</title>
<item><guid>a</guid><title>Fixture agent</title><link>https://example.invalid/a?utm_source=test</link><pubDate>Thu, 01 Jan 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;A fixture &lt;b&gt;description&lt;/b&gt;&lt;/p&gt;</description></item>
<item><guid>old</guid><title>Old</title><link>https://example.invalid/old</link><pubDate>Mon, 29 Dec 2025 10:00:00 GMT</pubDate></item>
<item><guid>future</guid><title>Future</title><link>https://example.invalid/future</link><pubDate>Fri, 02 Jan 2026 10:00:00 GMT</pubDate></item>
<item><guid>missing</guid><title>Missing date</title><link>https://example.invalid/no-date</link></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"><title>Fixture channel</title><entry><id>yt:video:abcdefghijk</id><yt:videoId>abcdefghijk</yt:videoId><title>Fixture video</title><link href="https://www.youtube.com/watch?v=abcdefghijk"/><published>2026-01-01T10:30:00+02:00</published><media:group><media:description>Fixture video description</media:description></media:group></entry></feed>"""


def test_rss_dates_description_and_canonicalization(now):
    source = Source(name="test", kind="openai", url="https://example.invalid/feed")
    rows, warnings = parse_feed(source, RSS, now - timedelta(hours=24), now)
    assert len(rows) == 1 and len(warnings) == 1
    assert rows[0].url == "https://example.invalid/a"
    assert rows[0].description == "A fixture description"


def test_youtube_atom_and_timezone(now):
    source = Source(name="channel", kind="youtube", url="https://example.invalid/feed")
    rows, _ = parse_feed(source, ATOM, now - timedelta(hours=24), now)
    assert rows[0].external_id == "abcdefghijk"
    assert rows[0].published_at.hour == 8
    assert rows[0].description == "Fixture video description"


def test_provider_failure_does_not_hide_other_sources(now):
    sources = [Source(name=x, kind="openai", url=f"https://example.invalid/{x}") for x in ("bad", "good")]
    def fetch(url):
        if url.endswith("bad"):
            raise httpx.ConnectError("offline")
        return RSS.replace("<item><guid>missing</guid><title>Missing date</title><link>https://example.invalid/no-date</link></item>", "")
    rows, errors, warnings = collect(sources, now - timedelta(hours=24), now, fetch)
    assert len(rows) == 1 and errors == ["bad: collection failed (ConnectError)"]
    assert warnings == []


def test_http_size_status_and_html_feed_errors(now):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="abcdefghij")))
    with pytest.raises(ValueError, match="exceeds"):
        fetch_text("https://example.invalid", client, maximum=5)
    denied = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_text("https://example.invalid", denied)
    with pytest.raises(ValueError, match="readable"):
        parse_feed(Source(name="x", kind="openai", url="https://example.invalid"), "<html>Blocked</html>", now - timedelta(days=1), now)


def test_url_security_and_html_plaintext():
    assert canonical_url("https://EXAMPLE.invalid/a/?utm_campaign=x&b=2#section") == "https://example.invalid/a?b=2"
    for value in ("javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.invalid/"):
        with pytest.raises(ValueError):
            canonical_url(value)
    assert plain_text("<script>bad()</script><p>Hello <strong>world</strong></p>") == "Hello world"
