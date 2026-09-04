"""Tests for database module."""
from database import is_india_location, is_target_opportunity


class TestJobDatabase:
    """Test JobDatabase operations."""
    
    def test_init_creates_tables(self, temp_db):
        """Test that database initialization creates all required tables."""
        with temp_db._conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert 'jobs' in table_names
            assert 'scrape_runs' in table_names
            assert 'applications' in table_names
            assert 'sent_alerts' in table_names
            assert 'jobs_fts' in table_names
    
    def test_add_and_get_job(self, temp_db, sample_job_entry):
        """Test adding and retrieving a job."""
        # Load keywords from config like the real scraper does
        import yaml
        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])
        
        result = temp_db.insert_job(sample_job_entry, keywords)
        assert result is True
        
        # Retrieve and verify
        jobs_result = temp_db.get_jobs_filtered(page_size=1)
        assert jobs_result['total'] == 1
        jobs = jobs_result['items']
        assert len(jobs) == 1
        job = jobs[0]
        assert job['title'] == "Security Engineer Intern"
        assert job['company'] == "TestCorp"
        assert job['location'] == "Bangalore, India"
        assert job['job_type'] == "internship"
        # domain_tags are extracted from keywords matching - check for expected tags
        assert len(job['domain_tags']) > 0
        assert any("security" in tag.lower() for tag in job['domain_tags'])
    
    def test_deduplication_by_hash(self, temp_db, sample_job_entry):
        """Test that duplicate jobs (same hash) are not added twice."""
        # Load keywords from config like the real scraper does
        import yaml
        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])
        
        result1 = temp_db.insert_job(sample_job_entry, keywords)
        result2 = temp_db.insert_job(sample_job_entry, keywords)
        assert result1 is True
        assert result2 is False  # Second insert should fail due to UNIQUE constraint
        
        jobs_result = temp_db.get_jobs_filtered(page_size=10)
        assert jobs_result['total'] == 1
    
    def test_get_stats(self, temp_db, sample_job_entry):
        """Test statistics generation."""
        # Load keywords from config like the real scraper does
        import yaml
        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])
        
        temp_db.insert_job(sample_job_entry, keywords)
        stats = temp_db.get_stats()
        assert stats['total'] == 1
        assert 'internship' in stats['by_type']
        assert stats['by_type']['internship'] == 1
    
    def test_is_india_location(self):
        """Test India location detection."""
        assert is_india_location("Bangalore, India") is True
        assert is_india_location("Mumbai") is True
        assert is_india_location("Hyderabad, Telangana") is True
        assert is_india_location("Remote - India") is True
        assert is_india_location("San Francisco, USA") is False
        assert is_india_location("London, UK") is False
        assert is_india_location("Remote") is False
        assert is_india_location(None) is False
    
    def test_is_target_opportunity(self):
        """Test target opportunity filtering."""
        # India Office/WFH - should match if cyber + fresher/intern
        assert is_target_opportunity("Bangalore, India", False, "full-time", "Security Engineer Intern", "Entry level position") is True
        assert is_target_opportunity("Mumbai", True, "full-time", "SOC Analyst Fresher", "Recent graduate") is True
        
        # Global Online Internships - should match if cyber + fresher/intern
        assert is_target_opportunity("Remote", True, "internship", "Security Intern", "Internship program") is True
        assert is_target_opportunity("Worldwide", True, "internship", "Cybersecurity Intern", "Summer internship") is True
        
        # Non-target - should not match
        assert is_target_opportunity("San Francisco, USA", False, "full-time", "Senior Security Engineer", "5 years experience") is False
        assert is_target_opportunity("Remote", False, "full-time", "Security Architect", "10 years experience") is False
        assert is_target_opportunity("London, UK", True, "full-time", "DevOps Engineer", "Experienced") is False
    
    def test_scrape_run_logging(self, temp_db):
        """Test scrape run logging."""
        temp_db.log_scrape_run("Test Source", 5, 100, "ok", "")
        history = temp_db.get_scrape_history(limit=1)
        assert len(history) == 1
        assert history[0]['source'] == "Test Source"
        assert history[0]['new_jobs'] == 5
        assert history[0]['total_fetched'] == 100
        assert history[0]['status'] == "ok"
    
    def test_application_tracking(self, temp_db, sample_job_entry):
        """Test job application tracking."""
        # Load keywords from config like the real scraper does
        import yaml
        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])
        
        temp_db.insert_job(sample_job_entry, keywords)
        
        # Get the job ID
        jobs_result = temp_db.get_jobs_filtered(page_size=1)
        job_id = jobs_result['items'][0]['id']
        
        # Mark as applied
        result = temp_db.mark_applied(job_id, "Applied via LinkedIn")
        assert result is True
        
        # Verify - get_applications returns full job details with app info
        apps = temp_db.get_applications()
        assert len(apps) == 1
        assert apps[0]['id'] == job_id  # Uses 'id' field, not 'job_id'
        assert apps[0]['notes'] == "Applied via LinkedIn"
        assert apps[0]['app_status'] == "applied"
    
    def test_alert_dedup(self, temp_db):
        """Test alert deduplication."""
        fp = "abc123"
        assert temp_db.is_alert_sent(fp) is False
        temp_db.mark_alert_sent(fp)
        assert temp_db.is_alert_sent(fp) is True


class TestDatabaseQueries:
    """Test complex database queries."""
    
    def test_get_jobs_with_filters(self, temp_db):
        """Test job filtering by various criteria."""
        # Add test jobs
        from datetime import datetime, timedelta, timezone

        from scraper import JobEntry
        recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Load keywords from config like the real scraper does
        import yaml
        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])
        
        jobs = [
            JobEntry(id="1", source="S1", source_url="u", title="Security Engineer Intern", company="C1", location="Bangalore", remote=False, job_type="internship", domain_tags=["appsec"], description="Entry level internship", apply_url="u", posted_date=recent_date),
            JobEntry(id="2", source="S1", source_url="u", title="Security Intern", company="C2", location="Remote", remote=True, job_type="internship", domain_tags=["soc"], description="Remote internship", apply_url="u", posted_date=recent_date),
            JobEntry(id="3", source="S1", source_url="u", title="SOC Analyst Fresher", company="C3", location="Mumbai", remote=False, job_type="full-time", domain_tags=["siem"], description="Recent grad welcome", apply_url="u", posted_date=recent_date),
        ]
        for j in jobs:
            temp_db.insert_job(j, keywords)
        
        # Filter by job_type
        internships_result = temp_db.get_jobs_filtered(job_type="internship")
        assert internships_result['total'] == 2
        
        # Filter by location
        india_jobs_result = temp_db.get_jobs_filtered(search="Bangalore")
        assert india_jobs_result['total'] >= 1
        
        # Filter by remote
        remote_jobs_result = temp_db.get_jobs_filtered(remote=True)
        assert remote_jobs_result['total'] >= 1
