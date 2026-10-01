from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from io import BytesIO

import feedparser
import httpx
from bs4 import BeautifulSoup

from .domain import CollectedArticle, Source, canonical_url, utc


def plain_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    return soup.get_text(" ", strip=True)


def fetch_text(url: str, client=None, maximum=5_000_000) -> str:
    canonical_url(url)
    if client is None:
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "AI-News-Aggregator/1.0"}) as owned:
            return fetch_text(url, owned, maximum)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > maximum:
                raise ValueError(f"Response exceeds {maximum} bytes")
        return bytes(raw).decode("utf-8", errors="replace")


def parse_feed(source: Source, xml: str, since: datetime, until: datetime):
    feed = feedparser.parse(xml)
    if not feed.version or (feed.bozo and not feed.entries):
        raise ValueError("Source did not return a readable RSS/Atom feed")
    articles, warnings = [], []
    for entry in feed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        if not stamp:
            warnings.append(f"{source.name}: skipped entry without publication date")
            continue
        published = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)
        if not utc(since) <= published <= utc(until):
            continue
        try:
            url = canonical_url(entry.get("link", ""))
            external_id = entry.get("yt_videoid") or entry.get("id") or url
            description = entry.get("summary", "")
            if source.kind == "youtube":
                description = entry.get("media_description", description)
            articles.append(CollectedArticle(source=source.name, kind=source.kind,
                external_id=external_id, url=url, title=plain_text(entry.get("title", "Untitled")),
                description=plain_text(description), published_at=published))
        except ValueError as exc:
            warnings.append(f"{source.name}: skipped invalid entry ({exc})")
    return articles, warnings


def collect(sources, since, until, fetch=fetch_text):
    articles, errors, warnings = [], [], []
    for source in sources:
        try:
            batch, skipped = parse_feed(source, fetch(source.url), since, until)
            articles.extend(batch)
            warnings.extend(skipped)
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{source.name}: collection failed ({type(exc).__name__})")
    return articles, errors, warnings


def youtube_transcript(video_id: str) -> str:
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi
    if video_id.startswith("yt:video:"):
        video_id = video_id.rsplit(":", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid YouTube video ID")
    class BoundedSession(requests.Session):
        def request(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            return super().request(*args, **kwargs)
    with BoundedSession() as session:
        transcript = YouTubeTranscriptApi(http_client=session).fetch(video_id, languages=["en"])
        return " ".join(segment.text for segment in transcript)


def docling_markdown(url: str, fetch=fetch_text) -> str:
    try:
        from docling.datamodel.base_models import DocumentStream, InputFormat
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError("Install Docling with: uv sync --locked --extra documents") from exc
    # Fetch ourselves for explicit timeout and size limits. HTML pipeline needs no
    # OCR model and performs no PDF/image conversion.
    stream = DocumentStream(name="article.html", stream=BytesIO(fetch(url).encode()))
    result = DocumentConverter(allowed_formats=[InputFormat.HTML]).convert(stream)
    return result.document.export_to_markdown()
