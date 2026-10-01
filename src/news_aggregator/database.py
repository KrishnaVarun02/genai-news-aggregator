from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .domain import CollectedArticle, canonical_url, utc, utcnow


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("mode", "url"), UniqueConstraint("mode", "source", "external_id"))
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(24))
    external_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content: Mapped[str] = mapped_column(Text, default="")
    content_status: Mapped[str] = mapped_column(String(32), default="pending")
    content_error: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")


class Summary(Base):
    __tablename__ = "summaries"
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    content_status: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Digest(Base):
    __tablename__ = "digests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))
    profile_json: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivery_status: Mapped[str] = mapped_column(String(24), default="preview")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def connect(url: str):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
    return engine


def initialize(engine):
    Base.metadata.create_all(engine)


def store_article(session: Session, item: CollectedArticle, mode: str) -> bool:
    article_id = item.identity(mode)
    if session.get(Article, article_id):
        return False
    row = Article(id=article_id, mode=mode, source=item.source, kind=item.kind,
                  external_id=item.external_id, url=canonical_url(item.url), title=item.title,
                  description=item.description, published_at=utc(item.published_at))
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        return False
    return True


def candidates(session: Session, mode: str, start: datetime, end: datetime):
    # Date filtering is on original publication, not ingestion or summary creation.
    return session.execute(select(Article, Summary).join(Summary).where(
        Article.mode == mode, Article.published_at >= start, Article.published_at <= end
    ).order_by(Article.published_at.desc(), Article.id)).all()


def set_content(article: Article, content: str, status: str, error: str = ""):
    article.content = content
    article.content_status = status
    article.content_error = error
    article.content_hash = hashlib.sha256(content.encode()).hexdigest() if content else ""
