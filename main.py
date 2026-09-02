#!/usr/bin/env python3
"""
CyberSecurity Job & Internship Scraper - Main Orchestrator

FREE, GLOBAL, COMPREHENSIVE cybersecurity job discovery across:
- RSS feeds from specialized security job boards
- GitHub curated markdown lists
- Public JSON APIs (Hacker News, ArbeitNow, RemoteOK)
- ATS boards of top security companies (Greenhouse public APIs)
- Automatic deduplication, classification, and Telegram alerting

Usage:
    python main.py           # Run once
    python main.py --daemon  # Run continuously with schedule
    python main.py --test    # Test run without Telegram
"""

import asyncio
import argparse
import os
import sys
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from scraper import ScraperEngine
from database import JobDatabase
from notifier import TelegramNotifier, load_config


class CyberSecJobScraper:
    def __init__(self, config_path: str = "config.yaml", test_mode: bool = False):
        self.config_path = config_path
        self.test_mode = test_mode
        self.db = JobDatabase()
        self.notifier = None
        self.running = True

        if not test_mode:
            tg_config = load_config(config_path)
            if tg_config.bot_token:
                self.notifier = TelegramNotifier(tg_config)
            else:
                print("⚠️  No Telegram bot token - running in test mode")
                self.test_mode = True

    async def run_once(self) -> Dict[str, int]:
        """Run one complete scraping cycle."""
        print(f"\n{'='*60}")
        print(f"🔍 CyberSec Job Scraper - {datetime.utcnow().isoformat()}")
        print(f"{'='*60}")

        async with ScraperEngine(self.config_path, self.db) as scraper:
            source_counts = await scraper.scrape_all()

        stats = self.db.get_stats()

        print(f"\n📊 Run Complete - Stats:")
        print(f"   Total Jobs: {stats['total']}")
        print(f"   Internships: {stats['internships']}")
        for jtype, count in stats['by_type'].items():
            print(f"   {jtype}: {count}")

        # Send notifications
        if self.notifier and not self.test_mode:
            # Get new jobs since last run (approximate: last 2 hours)
            since = (datetime.utcnow() - timedelta(hours=2)).isoformat()
            new_jobs = self.db.get_new_jobs(since, limit=50)

            if new_jobs:
                await self.notifier.send_job_alert(new_jobs)

            await self.notifier.send_summary(stats, source_counts)

        return source_counts

    async def run_daemon(self, interval_hours: int = 2):
        """Run continuously with scheduled intervals."""
        print(f"🤖 Starting daemon mode - scraping every {interval_hours} hours")
        print("Press Ctrl+C to stop\n")

        # Initial run
        await self.run_once()

        # Schedule periodic runs
        while self.running:
            try:
                # Sleep in small chunks to allow signal handling
                for _ in range(interval_hours * 3600 // 60):
                    if not self.running:
                        break
                    await asyncio.sleep(60)  # 1 minute chunks

                if self.running:
                    await self.run_once()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Daemon error: {e}")
                await asyncio.sleep(300)  # Wait 5 min on error

    def stop(self):
        self.running = False


async def async_main(args):
    scraper = CyberSecJobScraper(args.config, test_mode=args.test)

    if args.stats:
        stats = scraper.db.get_stats()
        print(f"\n📊 Database Statistics:")
        print(f"   Total Jobs: {stats['total']}")
        print(f"   Internships: {stats['internships']}")
        for jtype, count in stats['by_type'].items():
            print(f"   {jtype}: {count}")
        return

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        print("\n🛑 Shutdown signal received...")
        scraper.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    if args.daemon:
        await scraper.run_daemon(args.interval)
    else:
        await scraper.run_once()

    print("\n✅ Scraper finished")


def main():
    parser = argparse.ArgumentParser(description="CyberSecurity Job Scraper")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=2, help="Hours between runs (daemon)")
    parser.add_argument("--test", action="store_true", help="Test mode (no Telegram)")
    parser.add_argument("--stats", action="store_true", help="Show database stats and exit")
    parser.add_argument("--web", action="store_true", help="Start tactical web dashboard and REST API")
    parser.add_argument("--host", default="0.0.0.0", help="Web dashboard host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port (default: 8080)")

    args = parser.parse_args()

    if args.web:
        from web_server import start_server
        start_server(host=args.host, port=args.port, db_path="jobs.db", config_path=args.config)
        return

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()