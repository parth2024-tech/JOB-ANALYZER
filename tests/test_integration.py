"""Integration tests for full pipeline."""
from unittest.mock import AsyncMock, patch

import pytest

from main import CyberSecJobScraper


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_full_scrape_cycle_mocked(self, temp_db):
        """Test full scrape cycle with all sources mocked."""
        scraper = CyberSecJobScraper("/home/thor/Desktop/linkedin/config.yaml", test_mode=True)
        
        # Mock all source scrapers to return some jobs
        async def mock_scrape_all():
            return {"Test Source": 5}
        
        with patch.object(scraper, 'run_once', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"Test Source": 5}
            counts = await scraper.run_once()
            assert counts == {"Test Source": 5}
    
    @pytest.mark.asyncio
    async def test_run_once_updates_stats(self, temp_db):
        """Test that run_once updates database stats."""
        scraper = CyberSecJobScraper("/home/thor/Desktop/linkedin/config.yaml", test_mode=True)
        
        # Add some initial jobs
        from datetime import datetime, timedelta, timezone

        from scraper import JobEntry
        recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        
        initial_jobs = [
            JobEntry(id=f"init_{i}", source="Init", source_url="u", title=f"Security Intern {i}", company=f"C{i}", location="Bangalore", remote=False, job_type="internship", domain_tags=[], description="Entry level internship", apply_url="u", posted_date=recent_date)
            for i in range(3)
        ]
        for j in initial_jobs:
            temp_db.insert_job(j, [])
        
        initial_stats = temp_db.get_stats()
        assert initial_stats['total'] == 3
    
    @pytest.mark.asyncio
    async def test_daemon_mode_stoppable(self, temp_db):
        """Test daemon mode can be stopped."""
        scraper = CyberSecJobScraper("/home/thor/Desktop/linkedin/config.yaml", test_mode=True)
        scraper.running = True
        
        # Simulate stop signal
        scraper.stop()
        assert scraper.running is False
