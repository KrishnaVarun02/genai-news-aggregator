import json
from email import policy
from email.parser import BytesParser

import pytest
from sqlalchemy.orm import Session

from news_aggregator.agents import FixtureAgent
from news_aggregator.database import Digest
from news_aggregator.fixtures import fixture_articles
from news_aggregator.mailer import email_message, render_digest, send_email
from news_aggregator.pipeline import run_pipeline


def payload():
    return {"id": "fixture", "mode": "fixture", "date": "2026-01-01", "greeting": "Hi <Reader>", "introduction": "A & B",
        "articles": [{"title": '<script>alert("x")</script>', "summary": "<img src=x>", "url": "https://example.invalid/a?x=1&y=2", "reason": "<unsafe>", "source": "fixture", "published_at": "2026-01-01"}]}


def test_preview_escapes_all_untrusted_html_and_has_mime_alternatives():
    value = payload()
    title, plain, html = render_digest(value)
    assert "FIXTURE" in title
    assert "<script>" not in html and "<img" not in html and "&lt;script&gt;" in html
    assert "https://example.invalid/a?x=1&y=2" in plain
    parsed = BytesParser(policy=policy.default).parsebytes(email_message(value).as_bytes())
    assert parsed.get_content_type() == "multipart/alternative"
    assert parsed.get_body(preferencelist=("plain",))
    assert parsed.get_body(preferencelist=("html",))


def test_sink_rejects_remote_host_and_real_send_requires_two_gates():
    with pytest.raises(ValueError, match="local Mailpit"):
        send_email(payload(), {"host": "smtp.gmail.com", "port": 587}, "sink")
    with pytest.raises(ValueError, match="ALLOW_REAL_EMAIL"):
        send_email(payload(), {"host": "smtp.gmail.com", "port": 587}, "real")
    with pytest.raises(ValueError, match="Fixture data"):
        send_email(payload(), {"host": "smtp.gmail.com", "port": 587, "allow_real": True}, "real")


def test_duplicate_delivery_suppressed_and_uncertain_delivery_not_retried(engine, profile, now, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("news_aggregator.pipeline.send_email", lambda *args: calls.append(1))
    kwargs = dict(engine=engine, articles=fixture_articles(now), agent=FixtureAgent(), profile=profile, now=now, preview_dir=tmp_path, delivery="sink", smtp_config={"host": "localhost", "port": 1025})
    first = run_pipeline(**kwargs)
    second = run_pipeline(**kwargs)
    assert len(calls) == 1 and second["delivery_status"] == "sent_sink"
    with Session(engine) as session:
        row = session.get(Digest, first["digest"])
        row.delivery_status = "delivery_uncertain"
        session.commit()
    assert run_pipeline(**kwargs)["delivery_status"] == "delivery_uncertain"
    assert len(calls) == 1


def test_invalid_smtp_preflight_keeps_digest_retryable(engine, profile, now, tmp_path, monkeypatch):
    kwargs = dict(engine=engine, articles=fixture_articles(now), agent=FixtureAgent(), profile=profile, now=now, preview_dir=tmp_path, delivery="sink")
    with pytest.raises(ValueError, match="local Mailpit"):
        run_pipeline(**kwargs, smtp_config={"host": "remote.invalid", "port": 1025})
    calls = []
    monkeypatch.setattr("news_aggregator.pipeline.send_email", lambda *args: calls.append(1))
    assert run_pipeline(**kwargs, smtp_config={"host": "localhost", "port": 1025})["delivery_status"] == "sent_sink"
    assert len(calls) == 1
