from datetime import datetime, timezone
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
            with patch.object(scraper, '_run_source', new_callable=AsyncMock) as mock_run:
                mock_run.side_effect = lambda method, src: {src.name: 0}
                counts = await scraper.scrape_all()
                assert isinstance(counts, dict)
                assert all(isinstance(v, int) for v in counts.values())

    @pytest.mark.asyncio
    async def test_scrape_linkedin_guest(self, temp_db):
        """Test LinkedIn Guest scraper parsing."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(
                name="LinkedIn Test",
                url="https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=cybersecurity+intern&geoId=102713980",
                type="linkedin_guest",
            )
            sample_html = f"""
            <ul>
              <li>
                <div class="base-card">
                  <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/cyber-intern-12345?refId=abc"></a>
                  <h3 class="base-search-card__title">Cybersecurity Operations Intern</h3>
                  <h4 class="base-search-card__subtitle"><a href="#">CloudSec India</a></h4>
                  <span class="job-search-card__location">Bangalore, Karnataka, India</span>
                  <time datetime="{today}">1 day ago</time>
                  <img class="artdeco-entity-image" data-delayed-url="https://media.licdn.com/logo.png" />
                </div>
              </li>
            </ul>
            """
            with patch.object(scraper, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = sample_html
                new_jobs, total = await scraper.scrape_linkedin_guest(src)
                assert total >= 1
                assert new_jobs >= 1

    @pytest.mark.asyncio
    async def test_scrape_remotive(self, temp_db):
        """Test Remotive scraper parsing."""
        import json
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(
                name="Remotive Test",
                url="https://remotive.com/api/remote-jobs",
                type="remotive",
            )
            sample_data = {
                "jobs": [
                    {
                        "id": 101,
                        "title": "Junior Application Security Analyst",
                        "company_name": "CloudGuard",
                        "candidate_required_location": "Worldwide",
                        "url": "https://remotive.com/jobs/101",
                        "tags": ["security", "appsec"],
                        "description": "Fresher entry-level application security position",
                        "company_logo": "https://remotive.com/logo.png",
                        "publication_date": f"{today}T10:00:00Z",
                    }
                ]
            }
            with patch.object(scraper, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = json.dumps(sample_data)
                new_jobs, total = await scraper.scrape_remotive(src)
                assert total == 1
                assert new_jobs == 1

    @pytest.mark.asyncio
    async def test_scrape_remotive_multi_category(self, temp_db):
        """Test Remotive scraper parsing for Programming, Support, and Design roles with ATS extraction."""
        import json
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(
                name="Remotive Multi Test",
                url="https://remotive.com/api/remote-jobs",
                type="remotive",
            )
            sample_data = {
                "jobs": [
                    {
                        "id": 201,
                        "title": "Cloud Security Engineer",
                        "company_name": "Askable Tech",
                        "candidate_required_location": "Worldwide",
                        "url": "https://remotive.com/jobs/201",
                        "tags": ["Cloud Security", "AWS", "IAM", "PostgreSQL"],
                        "description": "<p>Build cloud security infrastructure. Apply at https://boards.greenhouse.io/askable/jobs/201</p>",
                        "company_logo": "https://remotive.com/logo201.png",
                        "salary": "$120,000 - $140,000",
                        "publication_date": f"{today}T12:00:00Z",
                    },
                    {
                        "id": 202,
                        "title": "Cyber Security Analyst",
                        "company_name": "SupportDesk Global",
                        "candidate_required_location": "Worldwide",
                        "url": "https://remotive.com/jobs/202",
                        "tags": ["Cybersecurity", "SIEM", "SOC", "Troubleshooting"],
                        "description": "<p>Resolve security issues for enterprise developers.</p>",
                        "company_logo": "https://remotive.com/logo202.png",
                        "salary": "$60,000 - $80,000",
                        "publication_date": f"{today}T12:00:00Z",
                    },
                    {
                        "id": 203,
                        "title": "Application Security Engineer",
                        "company_name": "DesignCraft AI",
                        "candidate_required_location": "Worldwide",
                        "url": "https://remotive.com/jobs/203",
                        "tags": ["AppSec", "Vulnerability", "DevSecOps"],
                        "description": "<p>Lead our AppSec code audits. <a href='https://jobs.lever.co/designcraft/203'>Apply on Lever</a></p>",
                        "company_logo": "https://remotive.com/logo203.png",
                        "salary": "$130,000",
                        "publication_date": f"{today}T12:00:00Z",
                    }
                ]
            }
            with patch.object(scraper, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = json.dumps(sample_data)
                new_jobs, total = await scraper.scrape_remotive(src)
                assert total == 3
                assert new_jobs == 3

                # Verify ATS extraction for Greenhouse
                dev_res = temp_db.get_jobs_filtered(search="Askable Tech")
                assert dev_res["total"] == 1
                assert dev_res["items"][0]["ats_provider"] == "Greenhouse"
                assert "greenhouse.io" in dev_res["items"][0]["apply_url"]
                assert dev_res["items"][0]["salary_display"] == "$120,000 - $140,000"

                # Verify Security Analyst role
                sup_res = temp_db.get_jobs_filtered(search="SupportDesk Global")
                assert sup_res["total"] == 1
                assert sup_res["items"][0]["title"] == "Cyber Security Analyst"

                # Verify AppSec role with Lever ATS
                des_res = temp_db.get_jobs_filtered(search="DesignCraft AI")
                assert des_res["total"] == 1
                assert des_res["items"][0]["title"] == "Application Security Engineer"
                assert des_res["items"][0]["ats_provider"] == "Lever"
                assert "lever.co" in des_res["items"][0]["apply_url"]

    @pytest.mark.asyncio
    async def test_scrape_internshala_ajax(self, temp_db):
        """Test Internshala AJAX scraper parsing."""
        import json

        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(
                name="Internshala Bangalore Test",
                url="https://internshala.com/internships_ajax/internship-in-bangalore/page-1",
                type="internshala_ajax",
            )
            html_chunk = """
            <div class="individual_internship" id="individual_internship_998877" internshipid="998877" employment_type="internship" data-href="/internship/detail/python-cyber-intern-998877">
                <a class="job-title-href" href="/internship/detail/python-cyber-intern-998877">Cybersecurity Analyst Intern</a>
                <a class="company-name">Acme Security Labs</a>
                <div class="locations">Bangalore</div>
                <div class="stipend">₹ 15,000 - 20,000 /month</div>
                <div class="posted_by_container">2 days ago</div>
            </div>
            """
            sample_payload = json.dumps({"internship_list_html": html_chunk})

            with patch.object(scraper, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = sample_payload
                new_jobs, total = await scraper.scrape_internshala_ajax(src)
                assert total == 1
                assert new_jobs == 1

                # Verify job inserted into DB with in-office and stipend properties
                job_res = temp_db.get_jobs_filtered(in_office_india=True)
                assert job_res["total"] >= 1
                item = job_res["items"][0]
                assert item["is_in_office_india"] is True
                assert item["stipend_inr_monthly"] == 17500.0

    @pytest.mark.asyncio
    async def test_scrape_wellfound_seo(self, temp_db):
        """Test Wellfound SEO SSR hydration state extraction."""
        import json

        async with ScraperEngine("/home/thor/Desktop/linkedin/config.yaml", temp_db) as scraper:
            src = SourceConfig(
                name="Wellfound India Test",
                url="https://wellfound.com/role/l/security-engineer/india",
                type="wellfound_seo",
            )
            apollo_data = {
                "StartupResult:112233": {
                    "__typename": "StartupResult",
                    "id": "112233",
                    "name": "SecuFlow Technologies",
                    "logoUrl": "https://photos.wellfound.com/logo.jpg",
                    "companySize": "11-50",
                    "highConcept": "Cloud native security compliance automation",
                    "highlightedJobListings": [{"__ref": "JobListingSearchResult:556677"}],
                },
                "JobListingSearchResult:556677": {
                    "__typename": "JobListingSearchResult",
                    "id": "556677",
                    "title": "Junior Security Engineer",
                    "slug": "junior-security-engineer",
                    "compensation": "$60k – $80k",
                    "locationNames": ["Bangalore", "Pune"],
                    "remote": False,
                    "jobType": "full-time",
                    "atsSource": "AtsIntegration::Greenhouse::Listing",
                    "description": "Develop and maintain secure cloud services",
                    "yearsExperienceMin": 1,
                    "liveStartAt": int(datetime.now(timezone.utc).timestamp()),
                }
            }
            next_data = {
                "props": {
                    "pageProps": {
                        "apolloState": {
                            "data": apollo_data
                        }
                    }
                }
            }
            sample_html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></body></html>'

            with patch.object(scraper, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = sample_html
                new_jobs, total = await scraper.scrape_wellfound_seo(src)
                assert total == 1
                assert new_jobs == 1

                job_res = temp_db.get_jobs_filtered(search="SecuFlow")
                assert job_res["total"] == 1
                item = job_res["items"][0]
                assert item["company"] == "SecuFlow Technologies"
                assert item["ats_provider"] == "Greenhouse"

