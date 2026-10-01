from datetime import datetime, timezone

import pytest

from news_aggregator.database import connect, initialize
from news_aggregator.domain import Profile


@pytest.fixture
def now():
    return datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def engine(tmp_path):
    value = connect(f"sqlite:///{tmp_path / 'test.db'}")
    initialize(value)
    yield value
    value.dispose()


@pytest.fixture
def profile():
    return Profile(name="Test reader", background="AI engineer", interests=["agents", "evaluation", "retrieval"], top_n=2)
