"""Tests for scraper module."""
from unittest.mock import AsyncMock, patch

import pytest

from scraper import ScraperEngine, SourceConfig


class TestScraperEngine:
    """Test ScraperEngine core functionality."""
    
    @pytest.mark.asyncio
    async def test_init_loads_config(self, temp_db):
        """Test that scraper loads config correctly."""
        scraper = ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db)
        assert scraper.config is not None
        assert 'sources' in scraper.config
        assert len(scraper.config['sources']['ats_boards']) > 0
    
    @pytest.mark.asyncio
    async def test_context_manager(self, temp_db):
        """Test async context manager."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            assert scraper.session is not None
        # Session should be closed after exit
    
    @pytest.mark.asyncio
    async def test_fetch_with_retry(self, temp_db):
        """Test fetch with retry logic."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            # Mock successful response
            with patch.object(scraper, 'session') as mock_session:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value="<html>test</html>")
                mock_session.get.return_value.__aenter__.return_value = mock_resp
                
                result = await scraper.fetch("https://example.com")
                assert result == "<html>test</html>"
    
    @pytest.mark.asyncio
    async def test_fetch_handles_404(self, temp_db):
        """Test fetch handles 404 gracefully."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            with patch.object(scraper, 'session') as mock_session:
                mock_resp = AsyncMock()
                mock_resp.status = 404
                mock_session.get.return_value.__aenter__.return_value = mock_resp
                
                result = await scraper.fetch("https://example.com/notfound")
                assert result is None
    
    @pytest.mark.asyncio
    async def test_parse_markdown_line_table_format(self, temp_db):
        """Test parsing markdown table rows."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(name="Test Internships", url="", type="markdown_list")
            
            # Table row with company, role, location, link
            line = "| **Company** | **Role** | **Location** | **Apply** | **Date** |"
            result = scraper._parse_markdown_line(line, src)
            assert result is None  # Header row
            
            line = "| **TestCorp** | Security Intern | Bangalore, India | [Apply](https://test.com/apply) | 2026-01-15 |"
            result = scraper._parse_markdown_line(line, src)
            assert result is not None
            assert result.company == "TestCorp"
            assert result.title == "Security Intern"
            assert result.location == "Bangalore, India"
            assert result.apply_url == "https://test.com/apply"
            assert result.job_type == "internship"
    
    @pytest.mark.asyncio
    async def test_parse_markdown_line_continuation_row(self, temp_db):
        """Test parsing continuation rows (same company, different role)."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(name="Test", url="", type="markdown_list")
            
            # First row establishes company
            line1 = "| **TestCorp** | Security Engineer | Bangalore | [Apply](https://test.com/1) | 2026-01-15 |"
            result1 = scraper._parse_markdown_line(line1, src)
            assert result1 is not None
            assert result1.company == "TestCorp"
            
            # Continuation row
            line2 = "| ↳ | Pentest Intern | Mumbai | [Apply](https://test.com/2) | 2026-01-16 |"
            result2 = scraper._parse_markdown_line(line2, src)
            assert result2 is not None
            assert result2.company == "TestCorp"  # Should inherit from previous
    
    @pytest.mark.asyncio
    async def test_parse_rss_entry(self, temp_db):
        """Test RSS entry parsing."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(name="Test RSS", url="https://example.com/rss", type="rss")
            
            # Mock feedparser entry with .get() method and __contains__ support
            class MockEntry:
                def __init__(self):
                    self.data = {
                        "title": "Security Engineer at TestCorp",
                        "link": "https://example.com/job/123",
                        "summary": "We are hiring a security engineer...",
                        "published_parsed": (2026, 1, 15, 10, 30, 0, 0, 0, 0),
                        "id": "123",
                    }
                def get(self, key, default=""):
                    return self.data.get(key, default)
                def __contains__(self, key):
                    return key in self.data
            
            entry = MockEntry()
            result = scraper._parse_rss_entry(entry, src)
            assert result is not None
            assert result.title == "Security Engineer at TestCorp"
            assert result.apply_url == "https://example.com/job/123"
            assert result.source == "Test RSS"
    
    @pytest.mark.asyncio
    async def test_scrape_all_returns_counts(self, temp_db):
        """Test scrape_all returns dict of source counts."""
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            # Mock all fetch methods to return empty
            with patch.object(scraper, 'scrape_rss', new_callable=AsyncMock) as mock_rss,\
                 patch.object(scraper, 'scrape_github_api_dir', new_callable=AsyncMock) as mock_github,\
                 patch.object(scraper, 'scrape_json_api', new_callable=AsyncMock) as mock_json,\
                 patch.object(scraper, 'scrape_ats_board', new_callable=AsyncMock) as mock_ats,\
                 patch.object(scraper, 'scrape_lever_board', new_callable=AsyncMock) as mock_lever:
                
                mock_rss.return_value = (0, 0)
                mock_github.return_value = (0, 0)
                mock_json.return_value = (0, 0)
                mock_ats.return_value = (0, 0)
                mock_lever.return_value = (0, 0)
                
                counts = await scraper.scrape_all()
                assert isinstance(counts, dict)
                assert all(isinstance(v, int) for v in counts.values())
