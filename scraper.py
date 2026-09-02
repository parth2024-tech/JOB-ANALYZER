import asyncio
import aiohttp
import feedparser
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from dataclasses import dataclass
import yaml
from pathlib import Path

from database import JobEntry, JobDatabase


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

    def _load_config(self, path: str) -> Dict:
        with open(path) as f:
            return yaml.safe_load(f)

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch(self, url: str) -> Optional[str]:
        """Fetch URL with retry logic."""
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    print(f"HTTP {resp.status} for {url}")
                    return None
        except Exception as e:
            print(f"Fetch error {url}: {e}")
            return None

    async def scrape_all(self) -> Dict[str, int]:
        """Run all scrapers and return counts per source."""
        results = {}

        # RSS Feeds
        for src in self.config.get("sources", {}).get("rss_feeds", []):
            count = await self.scrape_rss(SourceConfig(**src))
            results[src["name"]] = count

        # GitHub Markdown Lists
        for src in self.config.get("sources", {}).get("github_repos", []):
            if src.get("type") == "github_api_dir":
                count = await self.scrape_github_api_dir(SourceConfig(**src))
            else:
                count = await self.scrape_github_markdown(SourceConfig(**src))
            results[src["name"]] = count

        # JSON APIs
        for src in self.config.get("sources", {}).get("json_apis", []):
            count = await self.scrape_json_api(SourceConfig(**src))
            results[src["name"]] = count

        # ATS Boards
        for src in self.config.get("sources", {}).get("ats_boards", []):
            count = await self.scrape_ats_board(SourceConfig(**src))
            results[src["name"]] = count

        return results

    # ============ RSS Scraper ============
    async def scrape_rss(self, src: SourceConfig) -> int:
        print(f"[RSS] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0

        feed = feedparser.parse(content)
        count = 0

        for entry in feed.entries:
            job = self._parse_rss_entry(entry, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[RSS] {src.name}: {count} new jobs")
        return count

    def _parse_rss_entry(self, entry, src: SourceConfig) -> Optional[JobEntry]:
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            description = entry.get("summary", entry.get("description", ""))

            # Clean HTML from description
            soup = BeautifulSoup(description, "html.parser")
            description = soup.get_text()[:5000]

            # Extract company - try various fields
            company = ""
            if "author" in entry:
                company = entry.author
            elif "publisher" in entry:
                company = entry.publisher
            else:
                # Try to extract from title
                parts = title.split(" at ")
                if len(parts) > 1:
                    company = parts[-1].split(" (")[0].strip()
                else:
                    company = "Unknown"

            # Location
            location = entry.get("location", "Remote")
            remote = "remote" in location.lower() or "anywhere" in location.lower()

            # Posted date
            posted = entry.get("published", entry.get("updated", ""))

            job = JobEntry(
                id=f"rss_{src.name}_{hash(link)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                job_type="",  # Will be classified
                domain_tags=[],  # Will be classified
                description=description,
                apply_url=link,
                posted_date=posted,
            )
            return job
        except Exception as e:
            print(f"RSS parse error: {e}")
            return None

    # ============ GitHub Markdown Scraper ============
    async def scrape_github_markdown(self, src: SourceConfig) -> int:
        print(f"[GitHub] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0

        count = 0
        # Pattern: [Title](URL) - Company | Location
        # or **Title** - Company | Location | URL
        lines = content.split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            job = self._parse_markdown_line(line, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[GitHub] {src.name}: {count} new jobs")
        return count

    # ============ GitHub API Directory Scraper ============
    async def scrape_github_api_dir(self, src: SourceConfig) -> int:
        """Scrape jobs from GitHub API directory listing (e.g., NotifyYouInc 2026-Cybersecurity-Jobs jobs/ dir)."""
        print(f"[GitHub API] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0

        try:
            files = json.loads(content)
        except json.JSONDecodeError:
            print(f"Invalid JSON from {src.url}")
            return 0

        count = 0
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            if file_info.get("name", "").endswith(".md"):
                # Fetch the individual markdown file
                download_url = file_info.get("download_url")
                if not download_url:
                    continue
                md_content = await self.fetch(download_url)
                if not md_content:
                    continue
                job = self._parse_github_job_markdown(md_content, src, file_info.get("name", ""))
                if job and self.db.insert_job(job, self.keywords):
                    count += 1

        print(f"[GitHub API] {src.name}: {count} new jobs")
        return count

    def _parse_github_job_markdown(self, content: str, src: SourceConfig, filename: str) -> Optional[JobEntry]:
        """Parse a single job markdown file from NotifyYouInc format (markdown table)."""
        try:
            lines = content.strip().split("\n")
            title = ""
            company = ""
            location = "Remote"
            apply_url = ""
            description = ""

            # Parse markdown table format
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
                        field = parts[0].strip()
                        value = parts[1].strip()
                        if field == "Company":
                            # Extract company name from markdown link
                            import re
                            m = re.search(r"\[([^\]]+)\]", value)
                            company = m.group(1) if m else value
                        elif field == "Location":
                            location = value
                        elif field == "Apply":
                            # Extract URL from markdown link
                            m = re.search(r"\((https?://[^)]+)\)", value)
                            apply_url = m.group(1) if m else value
                elif line.startswith("# "):
                    # Title from first heading
                    title = line[2:].strip()

            # If no title found, try to extract from filename
            if not title:
                name = filename.replace(".md", "")
                # filename like: "company-role-description.md"
                parts = name.split("-")
                if len(parts) > 1:
                    company = parts[0].replace("-", " ").title()
                    title = " ".join(parts[1:]).replace("-", " ").title()
                else:
                    title = name.replace("-", " ").title()

            # Try to extract description from "## About This Role" section
            for i, line in enumerate(lines):
                if line.startswith("## About This Role") and i + 1 < len(lines):
                    description = lines[i + 1].strip()
                    break

            if not title or not company:
                return None

            remote = "remote" in location.lower()

            job = JobEntry(
                id=f"github_api_{src.name}_{hash(filename)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description=description[:5000],
                apply_url=apply_url,
            )
            return job
        except Exception as e:
            print(f"GitHub API markdown parse error: {e}")
            return None

    def _parse_markdown_line(self, line: str, src: SourceConfig) -> Optional[JobEntry]:
        try:
            # Skip obvious non-job lines
            line_lower = line.lower()
            skip_patterns = [
                "back to top", "back to the top",
                "resume template", "cover letter",
                "openings tracker", "when big tech",
                "contribute by submitting",
                "contribution guidelines",
                "use this repo to share",
                "updated daily by",
                "coder quad",
                "simplify.jobs",
                "github.com/simplifyjobs",
            ]
            if any(pattern in line_lower for pattern in skip_patterns):
                return None

            # Skip lines that are just section headers with emoji counts like "💻 **** (245)"
            if re.match(r"^[\U0001f300-\U0001faff]\s+\*{2,}\s+\(\d+\)", line):
                return None

            # Skip lines that are just emoji headers like "💻 Software Engineering @ 💻 **** (245)"
            if re.match(r"^[\U0001f300-\U0001faff]\s+\w+", line) and "@" in line and "****" in line:
                return None

            # Try [Title](URL) pattern
            md_link_match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", line)
            if md_link_match:
                title = md_link_match.group(1).strip()
                url = md_link_match.group(2).strip()
                remaining = line.replace(md_link_match.group(0), "")
            else:
                # Try **Title** pattern
                bold_match = re.search(r"\*\*([^*]+)\*\*", line)
                if bold_match:
                    title = bold_match.group(1).strip()
                    # Find URL in line
                    url_match = re.search(r"https?://\S+", line)
                    url = url_match.group(0) if url_match else ""
                    remaining = line.replace(bold_match.group(0), "")
                else:
                    return None

            # Skip if title looks like a section header or navigation
            title_lower = title.lower()
            if title_lower in ["back to top", "other", "hardware engineering", "quantitative finance",
                                "data science, ai & machine learning", "product management",
                                "software engineering", "resume template", "openings tracker",
                                "issue", "simplify"]:
                return None

            # Extract company/location from remaining text
            parts = [p.strip() for p in remaining.split("|")]

            company = parts[0] if parts else "Unknown"
            location = parts[1] if len(parts) > 1 else "Remote"
            remote = "remote" in location.lower()

            # Skip if URL is just a fragment anchor or points to the repo itself
            if url.startswith("#") or "github.com/SimplifyJobs/New-Grad-Positions" in url:
                return None

            job = JobEntry(
                id=f"github_{src.name}_{hash(title+url)}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description="",
                apply_url=url,
            )
            return job
        except Exception as e:
            print(f"Markdown parse error: {e}")
            return None

    # ============ JSON API Scraper ============
    async def scrape_json_api(self, src: SourceConfig) -> int:
        print(f"[JSON API] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            print(f"Invalid JSON from {src.url}")
            return 0

        count = 0
        jobs = self._extract_jobs_from_json(data, src.type)

        for job_data in jobs:
            job = self._normalize_json_job(job_data, src)
            if job and self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[JSON API] {src.name}: {count} new jobs")
        return count

    def _extract_jobs_from_json(self, data: Any, api_type: str) -> List[Dict]:
        """Extract job list from various JSON API structures."""
        if api_type == "hn_hiring":
            # Hacker News hiring thread - fetch comments recursively
            return []
        elif api_type == "json_api":
            # Generic: try common keys
            if isinstance(data, list):
                return data
            for key in ["jobs", "data", "results", "items", "positions"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data] if isinstance(data, dict) else []
        elif api_type == "ats_json":
            # Greenhouse/ATS format
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "jobs" in data:
                return data["jobs"]
            return []
        return []

    def _normalize_json_job(self, job_data: Dict, src: SourceConfig) -> Optional[JobEntry]:
        try:
            # Common field mappings
            title = job_data.get("title", job_data.get("name", job_data.get("position", "")))
            company = job_data.get("company", job_data.get("company_name", src.name))
            location = job_data.get("location", job_data.get("location_name", "Remote"))
            url = job_data.get("apply_url", job_data.get("url", job_data.get("absolute_url", "")))
            description = job_data.get("description", job_data.get("content", ""))

            # Clean HTML
            if description:
                soup = BeautifulSoup(description, "html.parser")
                description = soup.get_text()[:5000]

            remote = job_data.get("remote", False)
            if isinstance(remote, str):
                remote = "remote" in remote.lower()

            # Posted date
            posted = job_data.get("created_at", job_data.get("updated_at", job_data.get("date", "")))

            job = JobEntry(
                id=f"json_{src.name}_{hash(str(job_data.get('id', title+company)))}",
                source=src.name,
                source_url=src.url,
                title=title,
                company=company,
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description=description,
                apply_url=url,
                posted_date=posted,
            )
            return job
        except Exception as e:
            print(f"JSON normalize error: {e}")
            return None

    # ============ ATS Board Scraper ============
    async def scrape_ats_board(self, src: SourceConfig) -> int:
        print(f"[ATS] Fetching {src.name}...")
        content = await self.fetch(src.url)
        if not content:
            return 0

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return 0

        # Greenhouse format
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        count = 0

        for job_data in jobs:
            if not isinstance(job_data, dict):
                continue

            # Filter for security-related roles
            title = job_data.get("title", "").lower()
            if not any(kw in title for kw in ["security", "sec ", "infosec", "cyber", "soc", "appsec",
                                                "pentest", "vulnerab", "threat", "compliance", "grc",
                                                "crypto", "forens", "incident", "malware", "red team",
                                                "blue team", "cloud sec", "kubernetes", "aws", "azure"]):
                continue

            # Handle location - can be dict or string
            location_data = job_data.get("location")
            if isinstance(location_data, dict):
                location = location_data.get("name", "Remote")
            else:
                location = location_data or "Remote"

            # Handle remote - check metadata first, then location
            remote = False
            metadata = job_data.get("metadata")
            if metadata and isinstance(metadata, list) and len(metadata) > 0:
                remote_val = metadata[0].get("value", "")
                remote = remote_val.lower() == "remote"
            else:
                remote = "remote" in location.lower()

            job = JobEntry(
                id=f"ats_{src.name}_{job_data.get('id', hash(job_data.get('title','')))}",
                source=src.name,
                source_url=src.url,
                title=job_data.get("title", ""),
                company=src.name.replace(" Greenhouse", "").replace(" ATS", ""),
                location=location,
                remote=remote,
                job_type="",
                domain_tags=[],
                description=job_data.get("content", job_data.get("description", ""))[:5000],
                apply_url=job_data.get("absolute_url", job_data.get("apply_url", "")),
                posted_date=job_data.get("updated_at", job_data.get("created_at", "")),
            )
            if self.db.insert_job(job, self.keywords):
                count += 1

        print(f"[ATS] {src.name}: {count} new security jobs")
        return count


async def main():
    async with ScraperEngine() as scraper:
        results = await scraper.scrape_all()
        print("\n=== SCRAPING COMPLETE ===")
        for source, count in results.items():
            print(f"  {source}: {count} new jobs")
        print(f"\nDatabase stats: {scraper.db.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())