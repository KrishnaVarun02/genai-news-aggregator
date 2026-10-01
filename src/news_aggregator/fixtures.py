"""Original authored fixtures, deliberately separate from live collection."""
from datetime import timedelta

from .domain import CollectedArticle


def fixture_articles(now):
    items = [
        ("agents", "A fictional agent evaluation toolkit", "A fictional team publishes tools for agents and evaluation. The example demonstrates reproducible testing for open source workflows.", "youtube", 2),
        ("retrieval", "A fictional retrieval method", "An authored fixture describes a retrieval method for AI applications. It is not a report of an actual research result.", "anthropic", 5),
        ("models", "A fictional model release", "A fictional model releases example helps demonstrate the digest. No company has announced this product.", "openai", 9),
        ("old", "An old fictional story", "This item was published three days ago. A 24-hour digest must exclude it despite recent ingestion.", "openai", 72),
    ]
    return [CollectedArticle(source=f"fixture-{kind}", kind=kind, external_id=slug,
        url=f"https://example.invalid/fixture/{slug}", title=title, description=description,
        published_at=now - timedelta(hours=hours)) for slug, title, description, kind, hours in items]
