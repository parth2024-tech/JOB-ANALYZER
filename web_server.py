#!/usr/bin/env python3
"""
CyberSecurity Job Scraper - Web Server & REST API Backend
Provides real-time API endpoints and serves the Cyber Tactical Web Dashboard.

New in v3:
- CORS middleware
- Response caching (TTLCache) for stats/domains/sources
- ETag + Cache-Control headers
- WebSocket /ws endpoint for real-time job push
- APScheduler auto-scrape every 4h
- New endpoints: /api/jobs/new, /api/scrape/history, /api/applications, /api/search/suggestions, /api/export/csv
"""

import asyncio
import csv
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Set
from aiohttp import web, WSMsgType
import aiohttp
from cachetools import TTLCache
from loguru import logger

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from database import JobDatabase
from scraper import ScraperEngine
from scheduler import JobScheduler

# Simple in-memory caches
_stats_cache = TTLCache(maxsize=1, ttl=30)
_domains_cache = TTLCache(maxsize=1, ttl=60)
_sources_cache = TTLCache(maxsize=1, ttl=60)
_history_cache = TTLCache(maxsize=1, ttl=30)


class CyberSecWebServer:
    def __init__(self, db_path: str = "jobs.db", config_path: str = "config.yaml",
                 host: str = "0.0.0.0", port: int = 8080):
        self.db = JobDatabase(db_path)
        self.config_path = config_path
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[self._cors_middleware, self._cache_control_middleware])
        self.is_scraping = False
        self.last_scrape_stats = {}
        self.last_scrape_at: Optional[str] = None
        # WebSocket subscriber set
        self._ws_clients: Set[web.WebSocketResponse] = set()
        # Scheduler
        self.scheduler = JobScheduler(self)
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/ws", self.handle_ws)

        static_dir = BASE_DIR / "static"
        static_dir.mkdir(exist_ok=True)
        self.app.router.add_static("/static/", path=str(static_dir), name="static")

        # Core job endpoints
        self.app.router.add_get("/api/jobs", self.handle_api_jobs)
        self.app.router.add_get("/api/jobs/new", self.handle_api_jobs_new)
        self.app.router.add_get("/api/jobs/{id}", self.handle_api_job_detail)

        # Stats & metadata
        self.app.router.add_get("/api/stats", self.handle_api_stats)
        self.app.router.add_get("/api/domains", self.handle_api_domains)
        self.app.router.add_get("/api/sources", self.handle_api_sources)
        self.app.router.add_get("/api/status", self.handle_api_status)

        # Search autocomplete
        self.app.router.add_get("/api/company-categories", self.handle_api_company_categories)
        self.app.router.add_get("/api/search/suggestions", self.handle_api_suggestions)

        # History
        self.app.router.add_get("/api/scrape/history", self.handle_api_scrape_history)

        # Applications tracker
        self.app.router.add_get("/api/applications", self.handle_api_applications)
        self.app.router.add_post("/api/applications/{id}/apply", self.handle_api_apply)
        self.app.router.add_delete("/api/applications/{id}", self.handle_api_unapply)

        # Export
        self.app.router.add_get("/api/export/csv", self.handle_api_export_csv)

        # Link validation
        self.app.router.add_post("/api/links/validate", self.handle_api_validate_link)

        # Scrape trigger
        self.app.router.add_post("/api/scrape", self.handle_api_scrape)

        # Startup / shutdown hooks
        self.app.on_startup.append(self._on_startup)
        self.app.on_shutdown.append(self._on_shutdown)

    async def _on_startup(self, app):
        logger.info("Starting auto-scrape scheduler...")
        self.scheduler.start(interval_hours=4)

    async def _on_shutdown(self, app):
        logger.info("Shutting down scheduler and WebSocket clients...")
        self.scheduler.stop()
        for ws in list(self._ws_clients):
            await ws.close()

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        if request.method == "OPTIONS":
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            })
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @web.middleware
    async def _cache_control_middleware(self, request: web.Request, handler):
        response = await handler(request)
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        elif request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    async def handle_index(self, request: web.Request) -> web.Response:
        index_path = BASE_DIR / "static" / "index.html"
        if not index_path.exists():
            return web.Response(text="Dashboard index.html not found.", status=404)
        return web.FileResponse(index_path)

    # ========== WebSocket ==========
    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._ws_clients.add(ws)
        logger.info(f"WebSocket client connected. Total: {len(self._ws_clients)}")
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
                elif msg.type == WSMsgType.TEXT:
                    # Ping/pong support
                    if msg.data == "ping":
                        await ws.send_str("pong")
        finally:
            self._ws_clients.discard(ws)
            logger.info(f"WebSocket client disconnected. Total: {len(self._ws_clients)}")
        return ws

    async def _broadcast_ws(self, event: str, data: dict):
        """Broadcast a JSON event to all connected WebSocket clients."""
        if not self._ws_clients:
            return
        payload = json.dumps({"event": event, "data": data})
        dead = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    # ========== Core Job Endpoints ==========
    async def handle_api_jobs(self, request: web.Request) -> web.Response:
        params = request.query
        search = params.get("search", params.get("q", "")).strip()
        job_type = params.get("type", "").strip()
        domain = params.get("domain", "").strip()
        source = params.get("source", "").strip()
        seniority = params.get("seniority", "").strip()
        sort_by = params.get("sort", "newest").strip()
        location_scope = params.get("location_scope", "all").strip()
        target_only = params.get("target_only", "").lower().strip() in ("1", "true", "yes")
        company_category = params.get("company_category", "").strip()
        min_salary_lpa = None
        try:
            val = params.get("min_salary_lpa", "").strip()
            if val:
                min_salary_lpa = float(val)
        except ValueError:
            min_salary_lpa = None

        remote_val = params.get("remote", "").lower().strip()
        remote: Optional[bool] = None
        if remote_val in ("1", "true", "yes"):
            remote = True
        elif remote_val in ("0", "false", "no"):
            remote = False

        try:
            page = max(1, int(params.get("page", 1)))
        except ValueError:
            page = 1
        try:
            page_size = min(100, max(1, int(params.get("page_size", 24))))
        except ValueError:
            page_size = 24

        result = self.db.get_jobs_filtered(
            search=search, job_type=job_type, domain=domain, remote=remote,
            source=source, seniority=seniority, company_category=company_category,
            min_salary_lpa=min_salary_lpa, sort_by=sort_by,
            location_scope=location_scope, target_only=target_only,
            page=page, page_size=page_size
        )
        return web.json_response(result)

    async def handle_api_jobs_new(self, request: web.Request) -> web.Response:
        """Poll for jobs newer than a given timestamp."""
        since = request.query.get("since", "")
        if not since:
            return web.json_response({"error": "since param required (ISO timestamp)"}, status=400)
        try:
            limit = min(100, int(request.query.get("limit", 50)))
        except ValueError:
            limit = 50
        jobs = self.db.get_new_jobs(since, limit)
        count = self.db.get_new_jobs_count_since(since)
        return web.json_response({"new_count": count, "items": jobs})

    async def handle_api_job_detail(self, request: web.Request) -> web.Response:
        job_id = request.match_info.get("id", "")
        job = self.db.get_job_by_id(job_id)
        if not job:
            return web.json_response({"error": "Job not found"}, status=404)
        return web.json_response(job)

    # ========== Stats & Metadata ==========
    async def handle_api_stats(self, request: web.Request) -> web.Response:
        cached = _stats_cache.get("stats")
        if cached is None:
            stats = self.db.get_detailed_stats()
            _stats_cache["stats"] = stats
        else:
            stats = cached
        stats = dict(stats)
        stats["is_scraping"] = self.is_scraping
        stats["last_scrape_summary"] = self.last_scrape_stats
        stats["scheduler"] = self.scheduler.get_status()
        stats["job_history"] = self.db.get_jobs_history_by_day(30)
        return web.json_response(stats)

    async def handle_api_domains(self, request: web.Request) -> web.Response:
        cached = _domains_cache.get("domains")
        if cached is None:
            domains = self.db.get_domain_counts()
            _domains_cache["domains"] = domains
        else:
            domains = cached
        return web.json_response({"domains": domains})

    async def handle_api_sources(self, request: web.Request) -> web.Response:
        cached = _sources_cache.get("sources")
        if cached is None:
            sources = self.db.get_sources_stats()
            _sources_cache["sources"] = sources
        else:
            sources = cached
        return web.json_response({"sources": sources})

    async def handle_api_status(self, request: web.Request) -> web.Response:
        stats = self.db.get_stats()
        db_file = Path(self.db.db_path)
        db_size_mb = round(db_file.stat().st_size / (1024 * 1024), 2) if db_file.exists() else 0
        return web.json_response({
            "status": "online",
            "version": "3.0.0",
            "is_scraping": self.is_scraping,
            "db_size_mb": db_size_mb,
            "total_records": stats.get("total", 0),
            "internships": stats.get("internships", 0),
            "ws_clients": len(self._ws_clients),
            "scheduler": self.scheduler.get_status(),
            "last_scrape_results": self.last_scrape_stats
        })

    # ========== Company Categories ==========
    async def handle_api_company_categories(self, request: web.Request) -> web.Response:
        categories = [
            {"id": "all", "label": "All Categories", "icon": "🌐"},
            {"id": "vendor", "label": "Product / Vendor", "icon": "🏭"},
            {"id": "mssp", "label": "MSSP / MDR", "icon": "🛡️"},
            {"id": "consulting", "label": "Consulting & Advisory", "icon": "🏢"},
            {"id": "indian_it", "label": "Indian IT Services", "icon": "🇮🇳"},
            {"id": "government", "label": "Government & Defence", "icon": "🏛️"},
            {"id": "other", "label": "Enterprise / Other", "icon": "💼"},
        ]
        stats = self.db.get_detailed_stats()
        cat_counts = stats.get("by_company_category", {})
        for cat in categories:
            if cat["id"] == "all":
                cat["count"] = stats.get("total", 0)
            else:
                cat["count"] = cat_counts.get(cat["id"], 0)
        return web.json_response({"categories": categories})

    # ========== Search Suggestions ==========
    async def handle_api_suggestions(self, request: web.Request) -> web.Response:
        q = request.query.get("q", "").strip()
        if len(q) < 2:
            return web.json_response({"titles": [], "companies": []})
        suggestions = self.db.get_search_suggestions(q)
        return web.json_response(suggestions)

    # ========== Scrape History ==========
    async def handle_api_scrape_history(self, request: web.Request) -> web.Response:
        cached = _history_cache.get("history")
        if cached is None:
            history = self.db.get_scrape_history(limit=200)
            _history_cache["history"] = history
        else:
            history = cached
        return web.json_response({"history": history})

    # ========== Application Tracker ==========
    async def handle_api_applications(self, request: web.Request) -> web.Response:
        apps = self.db.get_applications()
        return web.json_response({"items": apps, "total": len(apps)})

    async def handle_api_apply(self, request: web.Request) -> web.Response:
        job_id = request.match_info.get("id", "")
        try:
            body = await request.json()
            notes = body.get("notes", "")
        except Exception:
            notes = ""
        success = self.db.mark_applied(job_id, notes)
        if not success:
            return web.json_response({"error": "Could not mark as applied"}, status=400)
        return web.json_response({"status": "applied", "job_id": job_id})

    async def handle_api_unapply(self, request: web.Request) -> web.Response:
        job_id = request.match_info.get("id", "")
        self.db.unmark_applied(job_id)
        return web.json_response({"status": "removed", "job_id": job_id})

    # ========== CSV Export ==========
    async def handle_api_export_csv(self, request: web.Request) -> web.Response:
        params = request.query
        result = self.db.get_jobs_filtered(
            search=params.get("search", ""),
            job_type=params.get("type", ""),
            domain=params.get("domain", ""),
            seniority=params.get("seniority", ""),
            location_scope=params.get("location_scope", "all"),
            page=1, page_size=5000
        )
        items = result.get("items", [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Title", "Company", "Company Category", "Location", "Job Type", "Seniority",
            "Salary", "Salary Min LPA", "Salary Max LPA", "Remote",
            "Domain Tags", "Skills", "Direct Apply URL", "Google Jobs URL",
            "LinkedIn URL", "Is India", "Is Target Match", "Source", "Discovered At"
        ])
        for job in items:
            routes = job.get("application_routes", {})
            writer.writerow([
                job.get("title", ""),
                job.get("company", ""),
                job.get("company_category", "other"),
                job.get("location", ""),
                job.get("job_type", ""),
                job.get("seniority_level", ""),
                job.get("salary_display", ""),
                job.get("salary_inr_lpa_min") or "",
                job.get("salary_inr_lpa_max") or "",
                "Yes" if job.get("remote") else "No",
                ", ".join(job.get("domain_tags", [])),
                ", ".join(job.get("skills_required", [])),
                routes.get("direct_url", ""),
                routes.get("google_jobs_url", ""),
                routes.get("linkedin_jobs_url", ""),
                "Yes" if job.get("is_india") else "No",
                "Yes" if job.get("is_target_match") else "No",
                job.get("source", ""),
                job.get("discovered_at", ""),
            ])

        csv_content = output.getvalue()
        return web.Response(
            body=csv_content.encode("utf-8"),
            content_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cybersec_jobs.csv"}
        )

    # ========== Link Validation ==========
    async def handle_api_validate_link(self, request: web.Request) -> web.Response:
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
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.head(
                    routes["direct_url"], timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=True
                ) as resp:
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

    # ========== Scrape Trigger ==========
    async def handle_api_scrape(self, request: web.Request) -> web.Response:
        if self.is_scraping:
            return web.json_response({
                "status": "busy",
                "message": "A scrape cycle is already active."
            }, status=409)
        asyncio.create_task(self._execute_scrape())
        return web.json_response({
            "status": "initiated",
            "message": "Scrape cycle started asynchronously."
        })

    async def _execute_scrape(self):
        """Asynchronously run scraper engine, update metrics, and push WS event."""
        self.is_scraping = True
        # Invalidate caches
        _stats_cache.clear()
        _sources_cache.clear()
        _history_cache.clear()

        jobs_before = self.db.get_stats().get("total", 0)
        logger.info("Starting scrape cycle...")
        await self._broadcast_ws("scrape_started", {"message": "Scrape cycle started"})

        try:
            async with ScraperEngine(self.config_path, self.db) as scraper:
                counts = await scraper.scrape_all()
                self.last_scrape_stats = counts
                self.last_scrape_at = __import__("datetime").datetime.utcnow().isoformat()
                logger.info(f"Scrape finished: {counts}")
        except Exception as e:
            logger.error(f"Error during scrape: {e}")
            self.last_scrape_stats = {"error": str(e)}
        finally:
            self.is_scraping = False
            # Invalidate caches again after data changes
            _stats_cache.clear()
            _sources_cache.clear()
            _history_cache.clear()
            _domains_cache.clear()

        jobs_after = self.db.get_stats().get("total", 0)
        new_count = jobs_after - jobs_before
        await self._broadcast_ws("scrape_complete", {
            "new_jobs": new_count,
            "total": jobs_after,
            "sources": self.last_scrape_stats
        })
        logger.info(f"Scrape complete. +{new_count} new jobs ({jobs_after} total)")

    def run(self):
        print(f"\n{'='*60}")
        print(f"🛡️  CyberSec Job Scraper v3 — Tactical Web Dashboard")
        print(f"📡  http://{self.host}:{self.port}")
        print(f"🔄  Auto-scrape: every 4 hours")
        print(f"📊  WebSocket: ws://{self.host}:{self.port}/ws")
        print(f"Press Ctrl+C to stop.")
        print(f"{'='*60}\n")
        web.run_app(self.app, host=self.host, port=self.port, access_log=None)


def start_server(host: str = "0.0.0.0", port: int = 8080,
                 db_path: str = "jobs.db", config_path: str = "config.yaml"):
    server = CyberSecWebServer(db_path=db_path, config_path=config_path, host=host, port=port)
    server.run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CyberSec Tactical Job Dashboard v3")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", default="jobs.db")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    start_server(host=args.host, port=args.port, db_path=args.db, config_path=args.config)
