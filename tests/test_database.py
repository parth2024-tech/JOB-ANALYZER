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


class TestSubscriptionsAndTrends:
    """Test JobScoop subscription and trends intelligence engine."""

    def test_subscriptions_crud(self, temp_db):
        """Test creating, reading, toggling, and deleting subscriptions."""
        sub_id1 = temp_db.add_subscription("CrowdStrike", "Intern", notify_telegram=True)
        assert sub_id1 > 0

        sub_id2 = temp_db.add_subscription("*", "SOC Analyst", notify_telegram=False)
        assert sub_id2 > 0

        # Read subscriptions
        subs = temp_db.get_subscriptions()
        assert len(subs) == 2
        s1 = next(s for s in subs if s["id"] == sub_id1)
        assert s1["company"] == "CrowdStrike"
        assert s1["role"] == "Intern"
        assert s1["active"] is True
        assert s1["notify_telegram"] is True
        assert "match_count" in s1

        # Toggle active
        temp_db.toggle_subscription(sub_id1)
        active_subs = temp_db.get_active_subscriptions()
        assert len(active_subs) == 1
        assert active_subs[0]["id"] == sub_id2

        temp_db.toggle_subscription(sub_id1)
        assert len(temp_db.get_active_subscriptions()) == 2

        # Delete subscription
        temp_db.delete_subscription(sub_id1)
        subs_after = temp_db.get_subscriptions()
        assert len(subs_after) == 1
        assert subs_after[0]["id"] == sub_id2

    def test_match_subscription_logic(self):
        """Test tokenized matching with stop words and wildcards."""
        from database import match_subscription

        subs = [
            {"id": 1, "company": "Cloudflare", "role": "security and intern", "active": True},
            {"id": 2, "company": "*", "role": "soc analyst", "active": True},
            {"id": 3, "company": "Fortinet", "role": "engineer", "active": False}
        ]

        # Case 1: Company + role matching with stop words ignored
        m1 = match_subscription("Associate Cyber Security Intern", "Cloudflare", subs)
        assert m1 is not None
        assert m1["id"] == 1

        # Case 2: Wildcard company with token matching
        m2 = match_subscription("L1 SOC Analyst", "Wipro", subs)
        assert m2 is not None
        assert m2["id"] == 2

        # Case 3: Inactive subscription should not match
        m3 = match_subscription("Security Engineer", "Fortinet", subs)
        assert m3 is None

        # Case 4: No match
        m4 = match_subscription("Frontend React Developer", "Cloudflare", subs)
        assert m4 is None

    def test_get_jobs_filtered_subscriptions(self, temp_db):
        """Test filtering jobs grid by active subscriptions."""
        from datetime import datetime, timedelta, timezone

        import yaml

        from scraper import JobEntry

        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])

        recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        temp_db.insert_job(
            JobEntry(id="sub-1", source="S1", source_url="u", title="Security Intern", company="Cloudflare", location="Remote", remote=True, job_type="internship", domain_tags=["appsec"], description="Internship", apply_url="u", posted_date=recent_date),
            keywords
        )
        temp_db.insert_job(
            JobEntry(id="sub-2", source="S1", source_url="u", title="Junior Penetration Tester", company="AcmeCorp", location="Bangalore", remote=False, job_type="full-time", domain_tags=["pentest"], description="Entry level", apply_url="u", posted_date=recent_date),
            keywords
        )

        # Before subscription: 0 subscriptions matches
        res_empty = temp_db.get_jobs_filtered(location_scope="subscriptions")
        assert res_empty["total"] == 0

        # Add subscription for Cloudflare
        temp_db.add_subscription("Cloudflare", "Intern")
        res_sub = temp_db.get_jobs_filtered(location_scope="subscriptions")
        assert res_sub["total"] == 1
        assert res_sub["items"][0]["company"] == "Cloudflare"
        assert res_sub["items"][0]["is_subscribed_match"] is True

    def test_get_trends_summary(self, temp_db):
        """Test market trends and correlation matrix calculation."""
        from datetime import datetime, timedelta, timezone

        import yaml

        from scraper import JobEntry

        with open("/home/thor/Desktop/linkedin/config.yaml") as f:
            config = yaml.safe_load(f)
        keywords = config.get("keywords", {}).get("domains", [])

        recent_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        temp_db.insert_job(
            JobEntry(id="t-1", source="S1", source_url="u", title="Security Intern", company="CrowdStrike", location="Remote", remote=True, job_type="internship", domain_tags=["appsec"], description="internship", apply_url="u1", posted_date=recent_date),
            keywords
        )
        temp_db.insert_job(
            JobEntry(id="t-2", source="S1", source_url="u", title="Junior SOC Analyst", company="CrowdStrike", location="Bangalore", remote=False, job_type="full-time", domain_tags=["soc"], description="entry-level fresher welcome", apply_url="u2", posted_date=recent_date),
            keywords
        )

        trends = temp_db.get_trends_summary(days=30)
        assert trends["total_jobs"] >= 2
        assert len(trends["top_companies"]) >= 1
        assert any(c["company"] == "CrowdStrike" for c in trends["top_companies"])
        assert len(trends["top_roles"]) >= 1
        assert isinstance(trends["correlation_matrix"], list)
        assert isinstance(trends["timeline"], list)

    def test_experience_parsing_and_freshness_bucketing(self, temp_db):
        """Test year ranges parsing, freshness buckets, and max_exp filtering."""
        from datetime import datetime, timedelta, timezone

        from database import (
            compute_freshness_bucket,
            extract_min_exp_years,
            is_fresher_or_intern,
            parse_year_ranges,
        )
        from scraper import JobEntry

        # 1. Test parse_year_ranges
        ranges = parse_year_ranges("Requires 1-3 years of experience in cybersecurity")
        assert ranges == [(1, 3)]

        ranges2 = parse_year_ranges("0-1 yoe, graduate welcome")
        assert ranges2 == [(0, 1)]

        # 2. Test extract_min_exp_years
        assert extract_min_exp_years("Cyber Security Intern", "Internship role") == 0.0
        assert extract_min_exp_years("Junior Security Analyst", "Requires 1-2 years experience") == 1.0

        # 3. Test is_fresher_or_intern rejection of senior experience (>2 years)
        assert is_fresher_or_intern("Cyber Security Analyst", "Requires 3-5 years experience") is False
        assert is_fresher_or_intern("Cyber Security Intern", "No experience required") is True

        # 4. Test compute_freshness_bucket
        now_iso = datetime.now(timezone.utc).isoformat()
        assert compute_freshness_bucket(now_iso, now_iso) == "1h"
        yesterday_iso = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        assert compute_freshness_bucket(yesterday_iso, yesterday_iso) == "24h"
        old_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        assert compute_freshness_bucket(old_iso, old_iso) == "week"

        # 5. Insert job with logo_url and min_exp_years
        keywords = ["appsec", "soc", "infosec"]
        job = JobEntry(
            id="exp-1",
            source="LinkedIn Guest",
            source_url="https://linkedin.com",
            title="Cybersecurity Operations Intern",
            company="TECEZE",
            location="Chennai, India",
            remote=False,
            job_type="internship",
            domain_tags=["soc"],
            description="Internship role for fresh graduates",
            apply_url="https://linkedin.com/jobs/view/12345",
            posted_date=now_iso,
            logo_url="https://media.licdn.com/dms/image/company-logo.png",
            min_exp_years=0.0,
        )
        assert temp_db.insert_job(job, keywords) is True

        # Verify get_jobs_filtered returns logo_url, min_exp_years, and freshness_bucket
        res = temp_db.get_jobs_filtered(search="TECEZE", freshness="1h", max_exp=0.0)
        assert res["total"] == 1
        item = res["items"][0]
        assert item["company"] == "TECEZE"
        assert item["logo_url"] == "https://media.licdn.com/dms/image/company-logo.png"
        assert item["min_exp_years"] == 0.0
        assert item["freshness_bucket"] == "1h"

