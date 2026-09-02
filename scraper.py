import asyncio
import aiohttp
import feedparser
import re
import json
import random
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
from dataclasses import dataclass
import yaml
from pathlib import Path

from database import JobEntry, JobDatabase, is_strictly_cyber_job, detect_seniority, extract_skills


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


@dataclass
class SourceConfig:
    name: str
    url: str
    type: str


class ScraperEngine:
    def __init__(self, config_path: str = "config.yaml", db: Optional[JobDatabase] = None):
        self.config = self._load_config(config_path)
        self.db = db or JobDatabase()
        self.session: Optional[aiohttp.ClientSession] = None
        self.keywords = self.config.get("keywords", {}).get("domains", [])
        # Semaphore: max 8 concurrent requests
        self._sem = asyncio.Semaphore(8)

    def _load_config(self, path: str) -> Dict:
        with open(path) as f:
            return yaml.safe_load(f)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(ssl=False, limit=20, limit_per_host=3)
        timeout = aiohttp.ClientTimeout(total=20)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": random.choice(USER_AGENTS)}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch(self, url: str, retries: int = 3) -> Optional[str]:
        """Fetch URL with exponential-backoff retries and UA rotation."""
        async with self._sem:
            for attempt in range(retries):
                try:
                    hdrs = {"User-Agent": random.choice(USER_AGENTS)}
                    async with self.session.get(url, headers=hdrs, allow_redirects=True) as resp:
                        if resp.status == 200:
                            return await resp.text(errors="replace")
                        elif resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", 5))
                            await asyncio.sleep(retry_after)
                        elif resp.status in (403, 404, 410):
                            return None  # No point retrying
                        else:
                            print(f"HTTP {resp.status} for {url}")
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"Fetch error {url}: {e}")

                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
        return None

    async def scrape_all(self) -> Dict[str, int]:
        """Run ALL scrapers concurrently and return counts per source."""
        tasks = []
        sources_cfg = self.config.get("sources", {})

        for src in sources_cfg.get("rss_feeds", []):
            tasks.append(self._run_source(self.scrape_rss, SourceConfig(**src)))

        for src in sources_cfg.get("github_repos", []):
            if src.get("type") == "github_api_dir":
                tasks.append(self._run_source(self.scrape_github_api_dir, SourceConfig(**src)))
            else:
                tasks.append(self._run_source(self.scrape_github_markdown, SourceConfig(**src)))

        for src in sources_cfg.get("json_apis", []):
            tasks.append(self._run_source(self.scrape_json_api, SourceConfig(**src)))

        for src in sources_cfg.get("ats_boards", []):
            tasks.append(self._run_source(self.scrape_ats_board, SourceConfig(**src)))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results = {}
        for result in results_list:
            if isinstance(result, dict):
                results.update(result)
            elif isinstance(result, Exception):
                print(f"Source error: {result}")

        return results

    async def _run_source(self, method, src: SourceConfig) -> Dict[str, int]:
        """Run a single source scraper, log results to DB."""
        start = datetime.utcnow().isoformat()
        new_jobs = 0
        total_fetched = 0
        status = "ok"
        error = ""
        try:
            result = await method(src)
            if isinstance(result, tuple):
                new_jobs, total_fetched = result
            else:
                new_jobs = result or 0
                total_fetched = new_jobs
        except Exception as e:
            status = "error"
            error = str(e)
            print(f"[ERROR] {src.name}: {e}")
        finally:
            try:
                self.db.log_scrape_run(src.name, new_jobs, total_fetched, status, error)
            except Exception:
                pass
        return {src.name: new_jobs}

    # ============ RSS Scraper ============
    async def scrape_rss(self, src: SourceConfig) -> Tuple[int, int]:
        print(f"[RSS] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0, 0

        feed = feedparser.parse(content)
        total = len(feed.entries)
        count = 0

        for entry in feed.entries:
            job = self._parse_rss_entry(entry, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[RSS] {src.name}: {count}/{total} new cyber jobs")
        return count, total

    def _parse_rss_entry(self, entry, src: SourceConfig) -> Optional[JobEntry]:
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            description = entry.get("summary", entry.get("description", ""))

            soup = BeautifulSoup(description, "html.parser")
            description = soup.get_text()[:5000]

            company = ""
            if "author" in entry:
                company = entry.author
            elif "publisher" in entry:
                company = entry.publisher
            else:
                parts = title.split(" at ")
                if len(parts) > 1:
                    company = parts[-1].split(" (")[0].strip()
                else:
                    company = "Unknown"

            location = entry.get("location", "Remote")
            remote = "remote" in location.lower() or "anywhere" in location.lower()
            posted = entry.get("published", entry.get("updated", ""))

            return JobEntry(
                id=f"rss_{src.name}_{hash(link)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description=description,
                apply_url=link,
                posted_date=posted,
            )
        except Exception as e:
            print(f"RSS parse error: {e}")
            return None

    # ============ GitHub API Directory Scraper ============
    async def scrape_github_api_dir(self, src: SourceConfig) -> Tuple[int, int]:
        print(f"[GitHub API] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0, 0

        try:
            files = json.loads(content)
        except json.JSONDecodeError:
            return 0, 0

        md_files = [f for f in files if isinstance(f, dict) and f.get("name", "").endswith(".md")]
        total = len(md_files)
        count = 0

        # Fetch all markdown files concurrently
        async def fetch_and_parse(file_info):
            download_url = file_info.get("download_url")
            if not download_url:
                return False
            md_content = await self.fetch(download_url)
            if not md_content:
                return False
            job = self._parse_github_job_markdown(md_content, src, file_info.get("name", ""))
            return job and self.db.insert_job(job, self.keywords)

        results = await asyncio.gather(*[fetch_and_parse(f) for f in md_files], return_exceptions=True)
        count = sum(1 for r in results if r is True)

        print(f"[GitHub API] {src.name}: {count}/{total} new cyber jobs")
        return count, total

    def _parse_github_job_markdown(self, content: str, src: SourceConfig, filename: str) -> Optional[JobEntry]:
        try:
            lines = content.strip().split("\n")
            title = company = apply_url = ""
            location = "Remote"
            description = ""

            in_table = False
            for line in lines:
                line = line.strip()
                if line.startswith("| Field | Details |"):
                    in_table = True
                    continue
                if in_table and line.startswith("|---"):
                    continue
                if in_table and line.startswith("| "):
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 2:
                        field, value = parts[0].strip(), parts[1].strip()
                        if field == "Company":
                            m = re.search(r"\[([^\]]+)\]", value)
                            company = m.group(1) if m else value
                        elif field == "Location":
                            location = value
                        elif field == "Apply":
                            m = re.search(r"\((https?://[^)]+)\)", value)
                            apply_url = m.group(1) if m else value
                elif line.startswith("# "):
                    title = line[2:].strip()

            if not title:
                name = filename.replace(".md", "")
                parts = name.split("-")
                if len(parts) > 1:
                    company = parts[0].replace("-", " ").title()
                    title = " ".join(parts[1:]).replace("-", " ").title()
                else:
                    title = name.replace("-", " ").title()

            for i, line in enumerate(lines):
                if line.startswith("## About This Role") and i + 1 < len(lines):
                    description = lines[i + 1].strip()
                    break

            if not title or not company:
                return None

            return JobEntry(
                id=f"github_api_{src.name}_{hash(filename)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote="remote" in location.lower(),
                job_type="",
                domain_tags=[],
                description=description[:5000],
                apply_url=apply_url,
            )
        except Exception as e:
            print(f"GitHub markdown parse error: {e}")
            return None

    # ============ GitHub Markdown Scraper ============
    async def scrape_github_markdown(self, src: SourceConfig) -> Tuple[int, int]:
        print(f"[GitHub] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0, 0

        lines = content.split("\n")
        total = len(lines)
        count = 0

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            job = self._parse_markdown_line(line, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[GitHub] {src.name}: {count} new cyber jobs")
        return count, total

    def _parse_markdown_line(self, line: str, src: SourceConfig) -> Optional[JobEntry]:
        try:
            line_lower = line.lower()
            skip_patterns = [
                "back to top", "back to the top", "resume template", "cover letter",
                "openings tracker", "when big tech", "contribute by submitting",
                "contribution guidelines", "use this repo to share", "updated daily by",
                "coder quad", "simplify.jobs", "github.com/simplifyjobs",
            ]
            if any(p in line_lower for p in skip_patterns):
                return None

            if re.match(r"^[\U0001f300-\U0001faff]\s+\*{2,}\s+\(\d+\)", line):
                return None

            md_link_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
            if md_link_match:
                title = md_link_match.group(1).strip()
                url = md_link_match.group(2).strip()
                remaining = line.replace(md_link_match.group(0), "")
            else:
                bold_match = re.search(r"\*\*([^*]+)\*\*", line)
                if bold_match:
                    title = bold_match.group(1).strip()
                    url_match = re.search(r"https?://\S+", line)
                    url = url_match.group(0) if url_match else ""
                    remaining = line.replace(bold_match.group(0), "")
                else:
                    return None

            title_lower = title.lower()
            if title_lower in ["back to top", "other", "hardware engineering", "quantitative finance",
                                "data science, ai & machine learning", "product management",
                                "software engineering", "resume template", "openings tracker",
                                "issue", "simplify"]:
                return None

            parts = [p.strip() for p in remaining.split("|")]
            company = parts[0] if parts else "Unknown"
            location = parts[1] if len(parts) > 1 else "Remote"

            if url.startswith("#") or "github.com/SimplifyJobs/New-Grad-Positions" in url:
                return None

            return JobEntry(
                id=f"github_{src.name}_{hash(title+url)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote="remote" in location.lower(),
                job_type="",
                domain_tags=[],
                description="",
                apply_url=url,
            )
        except Exception as e:
            print(f"Markdown parse error: {e}")
            return None

    # ============ JSON API Scraper ============
    async def scrape_json_api(self, src: SourceConfig) -> Tuple[int, int]:
        print(f"[JSON API] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0, 0

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return 0, 0

        jobs_raw = self._extract_jobs_from_json(data, src.type)
        total = len(jobs_raw)
        count = 0

        for job_data in jobs_raw:
            job = self._normalize_json_job(job_data, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[JSON API] {src.name}: {count}/{total} new cyber jobs")
        return count, total

    def _extract_jobs_from_json(self, data: Any, api_type: str) -> List[Dict]:
        if isinstance(data, list):
            return data
        for key in ["jobs", "data", "results", "items", "positions", "SearchResult", "search_result"]:
            if isinstance(data, dict) and key in data:
                val = data[key]
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):
                    # USAJobs nests deeper
                    for subkey in ["SearchResultItems", "items", "results"]:
                        if subkey in val and isinstance(val[subkey], list):
                            return val[subkey]
        return [data] if isinstance(data, dict) else []

    def _normalize_json_job(self, job_data: Dict, src: SourceConfig) -> Optional[JobEntry]:
        try:
            title = job_data.get("title", job_data.get("name", job_data.get("position",
                    job_data.get("MatchedObjectDescriptor", {}).get("PositionTitle", ""))))
            if isinstance(title, dict):
                title = str(title)

            company = job_data.get("company", job_data.get("company_name",
                       job_data.get("MatchedObjectDescriptor", {}).get("OrganizationName", src.name)))

            location_raw = job_data.get("location", job_data.get("location_name",
                           job_data.get("MatchedObjectDescriptor", {}).get("PositionLocationDisplay", "Remote")))
            if isinstance(location_raw, dict):
                location = location_raw.get("name", "Remote")
            else:
                location = location_raw or "Remote"

            url = job_data.get("apply_url", job_data.get("url", job_data.get("absolute_url",
                  job_data.get("MatchedObjectDescriptor", {}).get("ApplyURI", [""])[0]
                  if isinstance(job_data.get("MatchedObjectDescriptor", {}).get("ApplyURI"), list) else "")))

            description = job_data.get("description", job_data.get("content",
                          job_data.get("MatchedObjectDescriptor", {}).get("UserArea", {})
                          .get("Details", {}).get("JobSummary", "")))
            if description:
                soup = BeautifulSoup(str(description), "html.parser")
                description = soup.get_text()[:5000]

            remote = job_data.get("remote", False)
            if isinstance(remote, str):
                remote = "remote" in remote.lower()

            posted = job_data.get("created_at", job_data.get("updated_at", job_data.get("date",
                     job_data.get("MatchedObjectDescriptor", {}).get("PublicationStartDate", ""))))

            return JobEntry(
                id=f"json_{src.name}_{hash(str(job_data.get('id', str(title)+str(company))))}",
                source=src.name,
                source_url=src.url,
                title=str(title),
                company=str(company),
                location=str(location),
                remote=bool(remote),
                job_type="",
                domain_tags=[],
                description=str(description),
                apply_url=str(url),
                posted_date=str(posted),
            )
        except Exception as e:
            print(f"JSON normalize error: {e}")
            return None

    # ============ ATS Board Scraper (Greenhouse etc) ============
    async def scrape_ats_board(self, src: SourceConfig) -> Tuple[int, int]:
        print(f"[ATS] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0, 0

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return 0, 0

        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        total = len(jobs)
        count = 0

        for job_data in jobs:
            if not isinstance(job_data, dict):
                continue

            title = job_data.get("title", "")
            if not is_strictly_cyber_job(title):
                continue

            location_data = job_data.get("location")
            if isinstance(location_data, dict):
                location = location_data.get("name", "Remote")
            else:
                location = location_data or "Remote"

            remote = False
            metadata = job_data.get("metadata")
            if metadata and isinstance(metadata, list):
                for meta in metadata:
                    if isinstance(meta, dict) and meta.get("value", "").lower() == "remote":
                        remote = True
                        break
            if not remote:
                remote = "remote" in location.lower()

            company_name = src.name.replace(" Greenhouse", "").replace(" ATS", "").strip()

            job = JobEntry(
                id=f"ats_{src.name}_{job_data.get('id', hash(title))}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company_name,
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description=str(job_data.get("content", job_data.get("description", "")))[:5000],
                apply_url=job_data.get("absolute_url", job_data.get("apply_url", "")),
                posted_date=job_data.get("updated_at", job_data.get("created_at", "")),
            )

            if self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[ATS] {src.name}: {count}/{total} new security jobs")
        return count, total


async def main():
    async with ScraperEngine() as scraper:
        results = await scraper.scrape_all()
        print("\n=== SCRAPING COMPLETE ===")
        total_new = 0
        for source, count in results.items():
            if count > 0:
                print(f"  {source}: {count} new jobs")
            total_new += count
        print(f"\nTotal new jobs: {total_new}")
        print(f"Database stats: {scraper.db.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())
