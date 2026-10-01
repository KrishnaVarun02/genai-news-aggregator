import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents import FixtureAgent, OpenAIAgent
from .collectors import collect
from .database import Article, Digest, Summary, connect, initialize, store_article
from .domain import Profile, Source, utc, utcnow
from .fixtures import fixture_articles
from .pipeline import enrich, run_pipeline


def enabled(name):
    return os.getenv(name, "false").lower() == "true"


def smtp_config():
    return {"host": os.getenv("SMTP_HOST", "localhost"), "port": int(os.getenv("SMTP_PORT", "1025")),
        "username": os.getenv("SMTP_USERNAME", ""), "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("SMTP_FROM", "news@example.invalid"), "recipient": os.getenv("SMTP_TO", "reader@example.invalid"),
        "starttls": enabled("SMTP_STARTTLS"), "allow_real": enabled("ALLOW_REAL_EMAIL")}


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(description="AI news collection → summaries → profile ranking → digest preview")
    parser.add_argument("command", choices=["demo", "run", "collect", "enrich", "inspect", "check-openai"])
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--database-url")
    parser.add_argument("--profile", default=os.getenv("PROFILE_PATH", "config/profile.json"))
    parser.add_argument("--sources", default=os.getenv("SOURCES_PATH", "config/sources.json"))
    parser.add_argument("--preview-dir", default=os.getenv("PREVIEW_DIR", "previews"))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--now", help="ISO 8601 timestamp; fixture default is fixed for reproducibility")
    parser.add_argument("--send", choices=["preview", "sink", "real"], default="preview")
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--description-only-articles", action="store_true", help="Keep YouTube transcripts, use feed descriptions for articles instead of Docling")
    parser.add_argument("--retry-enrichment", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.hours <= 24 * 365:
            raise ValueError("--hours must be between 1 and 8760")
        mode = "fixture" if args.command == "demo" else args.mode
        now = utc(datetime.fromisoformat(args.now)) if args.now else (datetime(2026, 1, 1, 12, tzinfo=timezone.utc) if mode == "fixture" else utcnow())
        Path("data").mkdir(exist_ok=True)
        db_url = args.database_url or ("sqlite:///data/demo.db" if args.command == "demo" else os.getenv("DATABASE_URL", "postgresql+psycopg://news:local-development-only@localhost:55432/news"))
        engine = connect(db_url)
        initialize(engine)
        if args.command == "inspect":
            with Session(engine) as session:
                print(json.dumps({table.__tablename__: session.scalar(select(func.count()).select_from(table)) for table in (Article, Summary, Digest)}))
            return 0
        if args.command == "enrich":
            with Session(engine) as session:
                errors = enrich(session, mode, not args.no_enrich, args.retry_enrichment, documents=not args.description_only_articles)
                statuses = session.execute(select(Article.content_status, func.count()).where(Article.mode == mode).group_by(Article.content_status)).all()
            print(json.dumps({"mode": mode, "content_status": dict(statuses), "errors": errors}))
            return 1 if errors else 0
        profile = Profile.model_validate_json(Path(args.profile).read_text(encoding="utf-8"))
        if args.command in {"run", "demo", "check-openai"}:
            agent = FixtureAgent() if mode == "fixture" and args.command != "check-openai" else OpenAIAgent(
                api_key=os.getenv("OPENAI_API_KEY", ""), allow_paid=enabled("ALLOW_PAID_API"),
                summary_model=os.getenv("SUMMARY_MODEL", "gpt-4.1-mini"), curator_model=os.getenv("CURATOR_MODEL", "gpt-4o-mini"),
                email_model=os.getenv("EMAIL_MODEL", "gpt-4o-mini"))
        if args.command == "check-openai":
            result = agent.introduction(profile, [])
            print(json.dumps({"provider": "OpenAI", "model": agent.email_model, "structured_response": result.model_dump()}))
            return 0
        errors, warnings = [], []
        if mode == "fixture":
            articles = fixture_articles(now)
        else:
            sources = [Source.model_validate(source) for source in json.loads(Path(args.sources).read_text(encoding="utf-8"))]
            articles, errors, warnings = collect(sources, now - timedelta(hours=args.hours), now)
        if args.command == "collect":
            with Session(engine) as session:
                inserted = sum(store_article(session, item, mode) for item in articles)
                session.commit()
            print(json.dumps({"mode": mode, "collected": len(articles), "inserted": inserted, "duplicates": len(articles) - inserted, "errors": errors, "warnings": warnings}))
            return 1 if errors else 0
        report = run_pipeline(engine, articles, agent, profile, now, args.hours,
            args.preview_dir, args.send, smtp_config(), not args.no_enrich, args.retry_enrichment, errors, not args.description_only_articles)
        report["warnings"] = warnings
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else 0
    except Exception as exc:
        # SQL connection errors can embed passwords. Only report a safe class plus
        # our own known configuration/validation messages.
        if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) and exc.__class__.__module__ in {"builtins", "news_aggregator.agents"}:
            detail = str(exc)
        else:
            detail = "Check service availability, configuration, and credentials; sensitive details omitted"
        print(f"error: {type(exc).__name__}: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
