"""Tests for CyberSecWebServer and JobScoop API endpoints."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from web_server import CyberSecWebServer


@pytest.mark.asyncio
async def test_subscriptions_and_trends_endpoints(temp_db):
    """Test JobScoop subscription and trends REST API endpoints."""
    server = CyberSecWebServer(db_path=str(temp_db.db_path), config_path="/home/thor/Desktop/linkedin/config.yaml")
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        # 1. GET /api/subscriptions (initial empty)
        resp = await client.get("/api/subscriptions")
        assert resp.status == 200
        data = await resp.json()
        assert "subscriptions" in data
        assert isinstance(data["subscriptions"], list)

        # 2. POST /api/subscriptions (create subscription)
        resp = await client.post("/api/subscriptions", json={"company": "Cloudflare", "role": "Intern"})
        assert resp.status == 201
        created = await resp.json()
        assert created["status"] == "created"
        sub_id = created["subscription"]["id"]

        # 3. GET /api/subscriptions (verify created)
        resp = await client.get("/api/subscriptions")
        assert resp.status == 200
        subs_data = await resp.json()
        assert any(s["id"] == sub_id for s in subs_data["subscriptions"])

        # 4. PATCH /api/subscriptions/{id}/toggle
        resp = await client.patch(f"/api/subscriptions/{sub_id}/toggle")
        assert resp.status == 200
        toggled = await resp.json()
        assert toggled["status"] == "toggled"

        # 5. GET /api/trends/summary
        resp = await client.get("/api/trends/summary?days=30")
        assert resp.status == 200
        trends = await resp.json()
        assert "total_jobs" in trends
        assert "top_companies" in trends
        assert "top_roles" in trends
        assert "correlation_matrix" in trends

        # 6. GET /api/search/external
        resp = await client.get("/api/search/external?company=Cloudflare&role=Intern")
        assert resp.status == 200
        ext_search = await resp.json()
        assert "google_jobs_url" in ext_search
        assert "linkedin_jobs_url" in ext_search
        assert "indeed_jobs_url" in ext_search
        assert "google.com" in ext_search["google_jobs_url"]
        assert "linkedin.com" in ext_search["linkedin_jobs_url"]
        assert "indeed.com" in ext_search["indeed_jobs_url"]

        # 7. DELETE /api/subscriptions/{id}
        resp = await client.delete(f"/api/subscriptions/{sub_id}")
        assert resp.status == 200
        deleted = await resp.json()
        assert deleted["status"] == "deleted"

    finally:
        await client.close()
