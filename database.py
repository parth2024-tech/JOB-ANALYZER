import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib


@dataclass
class JobEntry:
    id: str
    source: str
    source_url: str
    title: str
    company: str
    location: str
    remote: bool
    job_type: str  # "full-time", "internship", "contract", "part-time"
    domain_tags: List[str]  # e.g., ["offensive", "pentest", "internship"]
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "USD"
    description: str = ""
    apply_url: str = ""
    posted_date: Optional[str] = None
    discovered_at: str = ""
    hash: str = ""


class JobDatabase:
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    remote INTEGER DEFAULT 0,
                    job_type TEXT,
                    domain_tags TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    salary_currency TEXT DEFAULT 'USD',
                    description TEXT,
                    apply_url TEXT,
                    posted_date TEXT,
                    discovered_at TEXT NOT NULL,
                    hash TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hash ON jobs(hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_discovered ON jobs(discovered_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_company ON jobs(company)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_type ON jobs(job_type)
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _generate_hash(job: JobEntry) -> str:
        """Generate unique hash for deduplication."""
        key = f"{job.title}|{job.company}|{job.location}|{job.apply_url}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _classify_job_type(title: str, description: str) -> str:
        text = (title + " " + description).lower()
        # Use word boundaries to avoid false positives like "intern" in "officer"
        if any(re.search(rf'\b{re.escape(k)}\b', text) for k in ["intern", "trainee", "co-op", "coop", "apprentice"]):
            return "internship"
        if any(re.search(rf'\b{re.escape(k)}\b', text) for k in ["contract", "contractor", "freelance"]):
            return "contract"
        if any(re.search(rf'\b{re.escape(k)}\b', text) for k in ["part-time", "part time"]):
            return "part-time"
        return "full-time"

    @staticmethod
    def _extract_domain_tags(text: str, keywords: List[str]) -> List[str]:
        text_lower = text.lower()
        # Use word boundaries for accurate matching
        found = []
        for kw in keywords:
            kw_lower = kw.lower()
            if re.search(rf'\b{re.escape(kw_lower)}\b', text_lower):
                found.append(kw)
        return found

    def insert_job(self, job: JobEntry, keywords: List[str]) -> bool:
        """Insert job if not duplicate. Returns True if inserted."""
        job.discovered_at = datetime.utcnow().isoformat()
        job.hash = self._generate_hash(job)
        job.job_type = self._classify_job_type(job.title, job.description)
        job.domain_tags = self._extract_domain_tags(
            job.title + " " + job.description, keywords
        )

        with self._conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO jobs (
                        id, source, source_url, title, company, location, remote,
                        job_type, domain_tags, salary_min, salary_max, salary_currency,
                        description, apply_url, posted_date, discovered_at, hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.source, job.source_url, job.title, job.company,
                    job.location, int(job.remote), job.job_type,
                    json.dumps(job.domain_tags), job.salary_min, job.salary_max,
                    job.salary_currency, job.description, job.apply_url,
                    job.posted_date, job.discovered_at, job.hash
                ))
                return True
            except sqlite3.IntegrityError:
                return False

    def get_new_jobs(self, since: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM jobs WHERE discovered_at > ? ORDER BY discovered_at DESC LIMIT ?
            """, (since, limit)).fetchall()
            return [dict(row) for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            internships = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_type = 'internship'"
            ).fetchone()[0]
            by_type = conn.execute("""
                SELECT job_type, COUNT(*) as c FROM jobs GROUP BY job_type
            """).fetchall()
            by_domain = conn.execute("""
                SELECT domain_tags, COUNT(*) as c FROM jobs
            """).fetchall()
            return {
                "total": total,
                "internships": internships,
                "by_type": {r["job_type"]: r["c"] for r in by_type},
            }

    def get_job_by_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["domain_tags"] = json.loads(data.get("domain_tags") or "[]")
            except Exception:
                data["domain_tags"] = []
            return data

    def get_jobs_filtered(
        self,
        search: str = "",
        job_type: str = "",
        domain: str = "",
        remote: Optional[bool] = None,
        source: str = "",
        sort_by: str = "newest",
        page: int = 1,
        page_size: int = 24
    ) -> Dict[str, Any]:
        """Fetch paginated, filtered, and sorted jobs with total match count."""
        conditions = []
        params = []

        if search:
            search_pattern = f"%{search.strip()}%"
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ? OR description LIKE ?)")
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        if job_type and job_type != "all":
            conditions.append("job_type = ?")
            params.append(job_type)

        if domain and domain != "all":
            conditions.append("domain_tags LIKE ?")
            params.append(f"%{domain.strip()}%")

        if remote is not None:
            conditions.append("remote = ?")
            params.append(1 if remote else 0)

        if source and source != "all":
            conditions.append("source = ?")
            params.append(source)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Order by mapping
        sort_map = {
            "newest": "discovered_at DESC, id DESC",
            "oldest": "discovered_at ASC, id ASC",
            "title": "title ASC",
            "company": "company ASC"
        }
        order_clause = f"ORDER BY {sort_map.get(sort_by, 'discovered_at DESC, id DESC')}"

        offset = max(0, (page - 1) * page_size)

        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM jobs {where_clause}", tuple(params)).fetchone()[0]

            query = f"SELECT * FROM jobs {where_clause} {order_clause} LIMIT ? OFFSET ?"
            query_params = list(params) + [page_size, offset]
            rows = conn.execute(query, tuple(query_params)).fetchall()

            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["domain_tags"] = json.loads(item.get("domain_tags") or "[]")
                except Exception:
                    item["domain_tags"] = []
                items.append(item)

            total_pages = (total + page_size - 1) // page_size if total > 0 else 1

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """Compute live telemetry for the web dashboard."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if total == 0:
                return {
                    "total": 0, "internships": 0, "remote": 0, "remote_pct": 0,
                    "by_type": {}, "by_source": {}, "top_companies": [],
                    "top_domains": {}, "last_scraped": None
                }

            internships = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_type = 'internship'"
            ).fetchone()[0]

            remote_count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE remote = 1"
            ).fetchone()[0]

            by_type_rows = conn.execute(
                "SELECT job_type, COUNT(*) as c FROM jobs GROUP BY job_type ORDER BY c DESC"
            ).fetchall()
            by_type = {r["job_type"]: r["c"] for r in by_type_rows}

            by_source_rows = conn.execute(
                "SELECT source, COUNT(*) as c FROM jobs GROUP BY source ORDER BY c DESC LIMIT 10"
            ).fetchall()
            by_source = {r["source"]: r["c"] for r in by_source_rows}

            top_companies_rows = conn.execute(
                "SELECT company, COUNT(*) as c FROM jobs WHERE company != 'Unknown' GROUP BY company ORDER BY c DESC LIMIT 10"
            ).fetchall()
            top_companies = [{"company": r["company"], "count": r["c"]} for r in top_companies_rows]

            last_row = conn.execute(
                "SELECT discovered_at FROM jobs ORDER BY discovered_at DESC LIMIT 1"
            ).fetchone()
            last_scraped = last_row[0] if last_row else None

            # Aggregate domain counts
            domain_counts = self.get_domain_counts()
            top_domains = {d["tag"]: d["count"] for d in domain_counts[:8]}

            return {
                "total": total,
                "internships": internships,
                "remote": remote_count,
                "remote_pct": round((remote_count / total) * 100, 1) if total > 0 else 0,
                "by_type": by_type,
                "by_source": by_source,
                "top_companies": top_companies,
                "top_domains": top_domains,
                "last_scraped": last_scraped
            }

    def get_domain_counts(self) -> List[Dict[str, Any]]:
        """Extract and aggregate frequencies of all domain tags."""
        tag_counts = {}
        with self._conn() as conn:
            rows = conn.execute("SELECT domain_tags FROM jobs WHERE domain_tags IS NOT NULL AND domain_tags != '[]'").fetchall()
            for row in rows:
                try:
                    tags = json.loads(row[0])
                    for t in tags:
                        if t and len(t) > 1:
                            tag_counts[t] = tag_counts.get(t, 0) + 1
                except Exception:
                    continue

        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        return [{"tag": k, "count": v} for k, v in sorted_tags]

    def close(self):
        pass  # Connections are per-operation


if __name__ == "__main__":
    db = JobDatabase("test_jobs.db")
    print("Database initialized:", db.get_stats())