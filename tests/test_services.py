import json
import os

import httpx
import pytest
from sqlalchemy.engine import make_url

from news_aggregator.agents import FixtureAgent
from news_aggregator.database import Base, connect, initialize
from news_aggregator.fixtures import fixture_articles
from news_aggregator.pipeline import run_pipeline


@pytest.mark.integration
def test_real_postgres_and_local_smtp_sink(profile, now, tmp_path):
    if os.getenv("RUN_SERVICE_TESTS") != "1":
        pytest.skip("Set RUN_SERVICE_TESTS=1 with disposable TEST_DATABASE_URL and local Mailpit")
    url = os.environ["TEST_DATABASE_URL"]
    assert make_url(url).database.endswith("_test"), "Refuse destructive test reset outside a *_test database"
    engine = connect(url)
    assert engine.dialect.name == "postgresql"
    Base.metadata.drop_all(engine)
    initialize(engine)
    try:
        report = run_pipeline(engine, fixture_articles(now), FixtureAgent(), profile, now,
            preview_dir=tmp_path, delivery="sink", smtp_config={"host": "localhost", "port": 1025})
        assert report["inserted"] == 4 and report["selected"] == 2
        assert report["delivery_status"] == "sent_sink"
        second = run_pipeline(engine, fixture_articles(now), FixtureAgent(), profile, now,
            preview_dir=tmp_path, delivery="sink", smtp_config={"host": "localhost", "port": 1025})
        assert second["duplicates"] == 4 and second["digest_reused"]
        messages = httpx.get("http://localhost:8025/api/v1/messages", timeout=10).json()
        assert any("FIXTURE" in message["Subject"] for message in messages["messages"])
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.document
def test_real_docling_html_to_markdown():
    if os.getenv("RUN_DOCLING_TESTS") != "1":
        pytest.skip("Install documents extra and set RUN_DOCLING_TESTS=1")
    from news_aggregator.collectors import docling_markdown
    markdown = docling_markdown("https://example.invalid/article", fetch=lambda _: "<html><body><h1>Authored fixture</h1><p>Agent evaluation example.</p></body></html>")
    assert "Authored fixture" in markdown and "Agent evaluation example." in markdown
