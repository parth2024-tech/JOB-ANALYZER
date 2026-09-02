#!/usr/bin/env python3
"""
APScheduler-based background scheduler for automatic scraping every 4 hours.
Used by the web server for continuous auto-discovery.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from loguru import logger


class JobScheduler:
    def __init__(self, web_server):
        self.server = web_server
        self.interval_hours = 4
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_run_at: Optional[str] = None
        self.next_run_at: Optional[str] = None
        self._run_count = 0

    def start(self, interval_hours: int = 4):
        """Start background auto-scrape scheduler."""
        self.interval_hours = interval_hours
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        self._update_next_run()
        logger.info(f"Scheduler started: auto-scrape every {interval_hours}h. Next run: {self.next_run_at}")

    def stop(self):
        """Stop the scheduler gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Scheduler stopped.")

    def _update_next_run(self):
        next_dt = datetime.utcnow() + timedelta(hours=self.interval_hours)
        self.next_run_at = next_dt.isoformat()

    async def _scheduler_loop(self):
        """Main scheduler loop: sleep interval_hours then trigger scrape."""
        # Initial delay: run first scrape immediately on startup
        await asyncio.sleep(5)
        while self._running:
            if not self.server.is_scraping:
                logger.info(f"Scheduler triggered auto-scrape #{self._run_count + 1}")
                self.last_run_at = datetime.utcnow().isoformat()
                asyncio.create_task(self.server._execute_scrape())
                self._run_count += 1
            else:
                logger.info("Scheduler: scrape already running, skipping this cycle.")

            self._update_next_run()
            # Sleep in 60s chunks to allow clean cancellation
            sleep_seconds = self.interval_hours * 3600
            for _ in range(sleep_seconds // 60):
                if not self._running:
                    return
                await asyncio.sleep(60)

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "interval_hours": self.interval_hours,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "total_runs": self._run_count,
        }
