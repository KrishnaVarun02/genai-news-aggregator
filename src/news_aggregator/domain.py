from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Article URL must be an HTTP(S) URL without credentials")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


class Source(BaseModel):
    name: str
    kind: str
    url: str


class Profile(BaseModel):
    name: str
    background: str
    interests: list[str]
    avoid: list[str] = []
    top_n: int = Field(default=10, ge=1, le=50)


class CollectedArticle(BaseModel):
    source: str
    kind: str
    external_id: str
    url: str
    title: str
    description: str
    published_at: datetime

    def identity(self, mode: str) -> str:
        return hashlib.sha256(f"{mode}:{canonical_url(self.url)}".encode()).hexdigest()[:32]


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    summary: str
    category: str


class RankedArticle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: str
    score: float = Field(ge=0, le=100)
    reason: str


class RankingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    articles: list[RankedArticle]


class IntroductionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    greeting: str
    introduction: str
