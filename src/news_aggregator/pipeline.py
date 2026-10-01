from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .collectors import docling_markdown, youtube_transcript
from .database import Article, Digest, Summary, candidates, set_content, store_article
from .domain import IntroductionOutput, utc, utcnow
from .mailer import send_email, validate_delivery, write_preview


def enrich(session, mode, enabled=True, retry=False, transcript=youtube_transcript, markdown=docling_markdown, documents=True):
    errors = []
    statuses = ["pending", "unavailable", "description_only"] if retry else ["pending"]
    rows = session.scalars(select(Article).where(Article.mode == mode, Article.content_status.in_(statuses))).all()
    for article in rows:
        previous_text = article.content or article.description
        if mode == "fixture":
            set_content(article, article.description, "fixture")
        elif article.kind == "openai" or not enabled or (article.kind == "anthropic" and not documents):
            set_content(article, "", "description_only")
        else:
            try:
                content = transcript(article.external_id) if article.kind == "youtube" else markdown(article.url)
                if not content.strip():
                    raise ValueError("Empty content")
                set_content(article, content, "transcript" if article.kind == "youtube" else "markdown")
            except Exception as exc:
                # Mark unavailable once, matching the tutorial; explicit retry is available.
                reason = f"{type(exc).__name__}: enrichment unavailable; using feed description"
                set_content(article, "", "unavailable", reason)
                errors.append(f"{article.id}: {reason}")
        if (article.content or article.description) != previous_text:
            stale = session.get(Summary, article.id)
            if stale:
                session.delete(stale)
        session.commit()
    return errors


def summarize(session, mode, agent, start, end):
    errors, count = [], 0
    rows = session.scalars(select(Article).outerjoin(Summary).where(Article.mode == mode, Summary.article_id.is_(None), Article.published_at >= start, Article.published_at <= end)).all()
    for article in rows:
        try:
            output = agent.summarize(article)
            session.add(Summary(article_id=article.id, title=output.title, summary=output.summary,
                                category=output.category, model=agent.summary_model,
                                content_status=article.content_status, content_hash=article.content_hash))
            session.commit()
            count += 1
        except Exception as exc:
            session.rollback()
            errors.append(f"{article.id}: summary failed ({type(exc).__name__}); retained for retry")
    return count, errors


def build_digest(session, mode, profile, now, hours, agent):
    start = now - timedelta(hours=hours)
    # Daily profile/window identity prevents reruns from generating duplicate mail.
    identity = f"{mode}:{now.date()}:{hours}:{profile.model_dump_json()}"
    digest_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    existing = session.get(Digest, digest_id)
    rows = candidates(session, mode, start, now)
    catalog = {article.id: {
        "article_id": article.id, "title": summary.title, "summary": summary.summary,
        "url": article.url, "source": article.source, "published_at": utc(article.published_at).isoformat(),
        "content_status": summary.content_status,
    } for article, summary in rows}
    fingerprint = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    if existing and (existing.delivery_status != "preview" or json.loads(existing.payload_json).get("source_fingerprint") == fingerprint):
        return existing, True
    if catalog:
        ranked = agent.rank(profile, list(catalog.values())).articles
        ids = [item.article_id for item in ranked]
        if len(ids) != len(set(ids)) or set(ids) != set(catalog):
            raise ValueError("Curator must return every supplied ID exactly once without invented IDs")
        selected = sorted(ranked, key=lambda item: (-item.score, item.article_id))[:profile.top_n]
        articles = [{**catalog[item.article_id], "score": item.score, "reason": item.reason} for item in selected]
        introduction = agent.introduction(profile, articles)
    else:
        articles = []
        introduction = IntroductionOutput(greeting=f"Hello {profile.name},", introduction="No new articles matched the publication window.")
    payload = {"id": digest_id, "mode": mode, "date": str(now.date()), "window_start": start.isoformat(), "window_end": now.isoformat(),
               "greeting": introduction.greeting, "introduction": introduction.introduction,
               "articles": articles, "candidate_count": len(catalog), "source_fingerprint": fingerprint}
    row = existing or Digest(id=digest_id, mode=mode, profile_json=profile.model_dump_json(), window_start=start,
                            window_end=now, payload_json="")
    row.payload_json = json.dumps(payload, ensure_ascii=False)
    row.window_start, row.window_end = start, now
    session.add(row)
    session.commit()
    return row, False


def run_pipeline(engine, articles, agent, profile, now, hours=24, preview_dir="previews",
                 delivery="preview", smtp_config=None, enrichment=True, retry_enrichment=False, collection_errors=None, documents=True):
    report = {"mode": agent.mode, "collected": len(articles), "inserted": 0, "duplicates": 0, "summarized": 0, "errors": []}
    with Session(engine) as session:
        for item in articles:
            inserted = store_article(session, item, agent.mode)
            report["inserted" if inserted else "duplicates"] += 1
        session.commit()
        report["errors"].extend(enrich(session, agent.mode, enrichment, retry_enrichment, documents=documents))
        report["summarized"], summary_errors = summarize(session, agent.mode, agent, now - timedelta(hours=hours), now)
        report["errors"].extend(summary_errors)
        if summary_errors or collection_errors:
            # Do not cache or send an incomplete daily digest; summaries can retry.
            report["digest"] = None
            report["errors"].extend(collection_errors or [])
            return report
        digest, reused = build_digest(session, agent.mode, profile, now, hours, agent)
        payload = json.loads(digest.payload_json)
        report["digest"], report["digest_reused"] = digest.id, reused
        report["selected"] = len(payload["articles"])
        report["previews"] = write_preview(payload, preview_dir)
        if delivery != "preview" and digest.delivery_status not in {"sent_real", "sent_sink", "sending", "delivery_uncertain"}:
            validate_delivery(payload, smtp_config or {}, delivery)
            claimed = session.execute(update(Digest).where(Digest.id == digest.id, Digest.delivery_status == "preview").values(delivery_status="sending")).rowcount
            session.commit()
            if not claimed:
                session.refresh(digest)
                report["delivery_status"] = digest.delivery_status
                return report
            try:
                send_email(payload, smtp_config or {}, delivery)
            except Exception:
                # Outcome can be uncertain after a transport failure. Do not auto-retry mail.
                digest.delivery_status = "delivery_uncertain"
                session.commit()
                raise
            digest.delivery_status = "sent_" + delivery
            digest.delivered_at = utcnow()
            session.commit()
        report["delivery_status"] = digest.delivery_status
    return report
