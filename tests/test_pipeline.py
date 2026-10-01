import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from news_aggregator.agents import AgentError, FixtureAgent
from news_aggregator.database import Article, Digest, Summary, candidates, store_article
from news_aggregator.domain import RankedArticle, RankingOutput
from news_aggregator.fixtures import fixture_articles
from news_aggregator.pipeline import build_digest, enrich, run_pipeline


def test_end_to_end_dedup_and_original_date_filter(engine, profile, now, tmp_path):
    items = fixture_articles(now)
    report = run_pipeline(engine, items, FixtureAgent(), profile, now, preview_dir=tmp_path)
    assert report["inserted"] == 4 and report["summarized"] == 3 and report["selected"] == 2
    assert report["errors"] == []
    payload = json.loads((tmp_path / f"{report['digest']}.json").read_text())
    assert payload["candidate_count"] == 3
    assert "old" not in " ".join(x["url"] for x in payload["articles"])
    assert all(x["title"].startswith("[FIXTURE]") for x in payload["articles"])
    second = run_pipeline(engine, items, FixtureAgent(), profile, now, preview_dir=tmp_path)
    assert second["duplicates"] == 4 and second["inserted"] == second["summarized"] == 0
    assert second["digest_reused"] and second["digest"] == report["digest"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Digest)) == 1


def test_url_dedup_cross_feeds_and_fixture_live_separation(engine, now):
    item = fixture_articles(now)[0]
    duplicate = item.model_copy(update={"source": "another-feed", "url": item.url + "?utm_source=other#section"})
    with Session(engine) as session:
        assert store_article(session, item, "fixture")
        assert not store_article(session, duplicate, "fixture")
        assert store_article(session, item, "live")
        session.commit()
        assert session.scalar(select(func.count()).select_from(Article)) == 2


def test_enrichment_failure_marked_once_and_explicit_retry(engine, now):
    calls = []
    def failed(_):
        calls.append(1)
        raise RuntimeError("No transcript")
    with Session(engine) as session:
        store_article(session, fixture_articles(now)[0], "live")
        session.commit()
        assert len(enrich(session, "live", transcript=failed)) == 1
        assert enrich(session, "live", transcript=failed) == []
        assert len(calls) == 1
        enrich(session, "live", retry=True, transcript=lambda _: "Recovered fixture transcript")
        row = session.scalar(select(Article))
        assert row.content_status == "transcript" and row.content_hash


def test_summary_failure_retains_retry_and_avoids_partial_digest(engine, profile, now, tmp_path):
    class Failed(FixtureAgent):
        def summarize(self, article):
            raise AgentError("provider unavailable")
    report = run_pipeline(engine, fixture_articles(now), Failed(), profile, now, preview_dir=tmp_path)
    assert report["digest"] is None and len(report["errors"]) == 3
    repaired = run_pipeline(engine, fixture_articles(now), FixtureAgent(), profile, now, preview_dir=tmp_path)
    assert repaired["summarized"] == 3 and repaired["digest"]


def test_collection_failure_does_not_freeze_empty_daily_digest(engine, profile, now, tmp_path):
    report = run_pipeline(engine, [], FixtureAgent(), profile, now, preview_dir=tmp_path, collection_errors=["source offline"])
    assert report["digest"] is None and report["errors"] == ["source offline"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Digest)) == 0


@pytest.mark.parametrize("ids", [["invented"], [], ["duplicate", "duplicate"]])
def test_reject_hallucinated_missing_duplicate_ranking_ids(engine, profile, now, tmp_path, ids):
    class Bad(FixtureAgent):
        def rank(self, profile, articles):
            return RankingOutput(articles=[RankedArticle(article_id=x, score=50, reason="x") for x in ids])
    with pytest.raises(ValueError, match="exactly once"):
        run_pipeline(engine, fixture_articles(now), Bad(), profile, now, preview_dir=tmp_path)


def test_empty_window_calls_no_model(engine, profile, now, tmp_path):
    class NoCalls(FixtureAgent):
        def rank(self, *_):
            raise AssertionError("No model needed")
    report = run_pipeline(engine, [], NoCalls(), profile, now, preview_dir=tmp_path)
    assert report["selected"] == 0


def test_no_future_or_ingestion_time_leak(engine, profile, now, tmp_path):
    items = fixture_articles(now)
    items.append(items[0].model_copy(update={"url": "https://example.invalid/future", "external_id": "future", "published_at": now + timedelta(hours=1)}))
    report = run_pipeline(engine, items, FixtureAgent(), profile, now, preview_dir=tmp_path)
    with Session(engine) as session:
        assert len(candidates(session, "fixture", now - timedelta(hours=24), now)) == 3


def test_old_failure_does_not_block_current_digest(engine, profile, now, tmp_path):
    class RefuseOld(FixtureAgent):
        def summarize(self, article):
            if "old" in article.url:
                raise AgentError("old source invalid")
            return super().summarize(article)
    result = run_pipeline(engine, fixture_articles(now), RefuseOld(), profile, now, preview_dir=tmp_path)
    assert result["digest"] and not result["errors"]


def test_enrichment_invalidates_summary_and_refreshes_unsent_digest(engine, profile, now, tmp_path):
    class TestLive(FixtureAgent):
        mode = "live"
    agent = TestLive()
    first = run_pipeline(engine, fixture_articles(now)[:1], agent, profile, now, preview_dir=tmp_path, enrichment=False)
    with Session(engine) as session:
        enrich(session, "live", retry=True, transcript=lambda _: "A recovered transcript about retrieval. Additional evaluation details.")
        assert session.scalar(select(func.count()).select_from(Summary)) == 0
    second = run_pipeline(engine, [], agent, profile, now, preview_dir=tmp_path, enrichment=False)
    assert second["summarized"] == 1 and not second["digest_reused"]
    payload = json.loads((tmp_path / f"{first['digest']}.json").read_text())
    assert "recovered transcript" in payload["articles"][0]["summary"]
    assert payload["articles"][0]["content_status"] == "transcript"
