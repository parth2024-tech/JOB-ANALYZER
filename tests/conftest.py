"""Pytest configuration and fixtures for JOB-ANALYZER tests."""
import asyncio
import os
import tempfile

import pytest

from database import JobDatabase
from notifier import TelegramConfig


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    db = JobDatabase(db_path)
    yield db
    # Cleanup
    db.close()
    os.unlink(db_path)


@pytest.fixture
def sample_job_entry():
    """Sample job entry for testing."""
    from datetime import datetime, timedelta, timezone

    from scraper import JobEntry
    # Use a recent date (within 14 days)
    recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    return JobEntry(
        id="test_123",
        source="Test Source",
        source_url="https://example.com/jobs",
        title="Security Engineer Intern",
        company="TestCorp",
        location="Bangalore, India",
        remote=False,
        job_type="internship",
        domain_tags=["appsec", "cloud security"],
        description="Entry level internship position for recent graduates",
        apply_url="https://example.com/apply",
        posted_date=recent_date,
    )


@pytest.fixture
def sample_config():
    """Sample Telegram config for testing."""
    return TelegramConfig(bot_token="test_token", chat_id="123456")
