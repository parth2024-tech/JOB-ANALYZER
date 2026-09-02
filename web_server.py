#!/usr/bin/env python3
"""
CyberSecurity Job Scraper - Web Server & REST API Backend
Provides real-time API endpoints and serves the Cyber Tactical Web Dashboard.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
from aiohttp import web
from loguru import logger

# Add root directory to sys.path
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from database import JobDatabase
from scraper import ScraperEngine


class CyberSecWebServer:
    def __init__(self, db_path: str = "jobs.db", config_path: str = "config.yaml", host: str = "127.0.0.1", port: int = 8080):
        self.db = JobDatabase(db_path)
        self.config_path = config_path
        self.host = host
        self.port = port
        self.app = web.Application()
        self.is_scraping = False
        self.last_scrape_stats = {}
        self._setup_routes()

    def _setup_routes(self):
        # Frontend routes
        self.app.router.add_get("/", self.handle_index)
        
        # Static files
        static_dir = BASE_DIR / "static"
        static_dir.mkdir(exist_ok=True)
        self.app.router.add_static("/static/", path=str(static_dir), name="static")

        # REST API endpoints
        self.app.router.add_get("/api/jobs", self.handle_api_jobs)
        self.app.router.add_get("/api/jobs/{id}", self.handle_api_job_detail)
        self.app.router.add_get("/api/stats", self.handle_api_stats)
        self.app.router.add_get("/api/domains", self.handle_api_domains)
        self.app.router.add_get("/api/sources", self.handle_api_sources)
        self.app.router.add_get("/api/status", self.handle_api_status)
        self.app.router.add_post("/api/links/validate", self.handle_api_validate_link)
        self.app.router.add_post("/api/scrape", self.handle_api_scrape)

    async def handle_index(self, request: web.Request) -> web.Response:
        """Serve the main tactical dashboard single-page app."""
        index_path = BASE_DIR / "static" / "index.html"
        if not index_path.exists():
            return web.Response(text="Dashboard index.html not found.", status=404)
        return web.FileResponse(index_path)

    async def handle_api_jobs(self, request: web.Request) -> web.Response:
        """Query paginated, filtered, and sorted jobs."""
        params = request.query
        search = params.get("search", params.get("q", "")).strip()
        job_type = params.get("type", "").strip()
        domain = params.get("domain", "").strip()
        source = params.get("source", "").strip()
        sort_by = params.get("sort", "newest").strip()
        location_scope = params.get("location_scope", "all").strip()
        target_only = params.get("target_only", "").lower().strip() in ("1", "true", "yes")

        # Remote filter handling
        remote_val = params.get("remote", "").lower().strip()
        remote: Optional[bool] = None
        if remote_val in ("1", "true", "yes"):
            remote = True
        elif remote_val in ("0", "false", "no"):
            remote = False

        # Pagination params
        try:
            page = max(1, int(params.get("page", 1)))
        except ValueError:
            page = 1

        try:
            page_size = min(100, max(1, int(params.get("page_size", 24))))
        except ValueError:
            page_size = 24

        result = self.db.get_jobs_filtered(
            search=search,
            job_type=job_type,
            domain=domain,
            remote=remote,
            source=source,
            sort_by=sort_by,
            location_scope=location_scope,
            target_only=target_only,
            page=page,
            page_size=page_size
        )
        return web.json_response(result)

    async def handle_api_job_detail(self, request: web.Request) -> web.Response:
        """Get single job details by ID."""
        job_id = request.match_info.get("id", "")
        job = self.db.get_job_by_id(job_id)
        if not job:
            return web.json_response({"error": "Job not found"}, status=404)
        return web.json_response(job)

    async def handle_api_stats(self, request: web.Request) -> web.Response:
        """Get comprehensive statistics for the telemetry HUD."""
        stats = self.db.get_detailed_stats()
        stats["is_scraping"] = self.is_scraping
        stats["last_scrape_summary"] = self.last_scrape_stats
        return web.json_response(stats)

    async def handle_api_domains(self, request: web.Request) -> web.Response:
        """Get list of domain tags with frequencies."""
        domains = self.db.get_domain_counts()
        return web.json_response({"domains": domains})

    async def handle_api_sources(self, request: web.Request) -> web.Response:
        """Get live ingestion metrics per feeder source."""
        sources = self.db.get_sources_stats()
        return web.json_response({"sources": sources})

    async def handle_api_validate_link(self, request: web.Request) -> web.Response:
        """Validate live HTTP status for an application link with fallback routes."""
        try:
            body = await request.json()
            url = body.get("url", "")
            title = body.get("title", "")
            company = body.get("company", "")
        except Exception:
            return web.json_response({"error": "Invalid request body"}, status=400)

        from database import generate_application_routes
        routes = generate_application_routes(title, company, url)

        is_live = False
        status_code = 0
        import aiohttp
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.head(routes["direct_url"], timeout=aiohttp.ClientTimeout(total=3), allow_redirects=True) as resp:
                    status_code = resp.status
                    is_live = status_code < 400
        except Exception:
            is_live = False

        return web.json_response({
            "url": routes["direct_url"],
            "is_live": is_live,
            "status_code": status_code,
            "routes": routes
        })

    async def handle_api_status(self, request: web.Request) -> web.Response:
        """Get backend engine status."""
        stats = self.db.get_stats()
        db_file = Path(self.db.db_path)
        db_size_mb = round(db_file.stat().st_size / (1024 * 1024), 2) if db_file.exists() else 0
        return web.json_response({
            "status": "online",
            "is_scraping": self.is_scraping,
            "db_size_mb": db_size_mb,
            "total_records": stats.get("total", 0),
            "internships": stats.get("internships", 0),
            "host": self.host,
            "port": self.port,
            "last_scrape_results": self.last_scrape_stats
        })

    async def handle_api_scrape(self, request: web.Request) -> web.Response:
        """Trigger an on-demand scrape job in background."""
        if self.is_scraping:
            return web.json_response({
                "status": "busy",
                "message": "A scrape cycle is already active."
            }, status=409)

        # Launch background task
        asyncio.create_task(self._execute_scrape())
        return web.json_response({
            "status": "initiated",
            "message": "Scrape cycle started asynchronously."
        })

    async def _execute_scrape(self):
        """Asynchronously run scraper engine and update metrics."""
        self.is_scraping = True
        logger.info("Triggered on-demand scrape job...")
        try:
            async with ScraperEngine(self.config_path, self.db) as scraper:
                counts = await scraper.scrape_all()
                self.last_scrape_stats = counts
                logger.info(f"On-demand scrape finished: {counts}")
        except Exception as e:
            logger.error(f"Error during on-demand scrape: {e}")
            self.last_scrape_stats = {"error": str(e)}
        finally:
            self.is_scraping = False

    def run(self):
        """Start the web server."""
        print(f"\n========================================================")
        print(f"🛡️  CyberSec Job Scraper - Tactical Web Dashboard")
        print(f"📡  Running on: http://{self.host}:{self.port}")
        print(f"Press Ctrl+C to stop.")
        print(f"========================================================\n")
        web.run_app(self.app, host=self.host, port=self.port, access_log=None)


def start_server(host: str = "0.0.0.0", port: int = 8080, db_path: str = "jobs.db", config_path: str = "config.yaml"):
    server = CyberSecWebServer(db_path=db_path, config_path=config_path, host=host, port=port)
    server.run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CyberSec Tactical Job Dashboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--db", default="jobs.db", help="Path to SQLite database")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    start_server(host=args.host, port=args.port, db_path=args.db, config_path=args.config)
