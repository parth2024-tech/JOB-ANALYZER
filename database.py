import sqlite3
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib


# =========================================================================
# SALARY EXTRACTION & NORMALIZATION
# =========================================================================

# Approximate exchange rate (INR per USD) - update periodically
USD_TO_INR = 84.0
INR_LPA_DIVISOR = 100_000  # 1 Lakh = 100,000 INR

# Salary regex patterns (ordered: most specific first)
_LPA_RANGE_PAT = re.compile(
    r'(\d{1,3}(?:\.\d+)?)\s*[-–to]+\s*(\d{1,3}(?:\.\d+)?)\s*'
    r'(?:L|lakh|lakhs?|LPA|lpa|lac)\b',
    re.IGNORECASE
)
_LPA_SINGLE_PAT = re.compile(
    r'(\d{1,3}(?:\.\d+)?)\s*(?:LPA|lpa)\b|'  # explicit "LPA" suffix
    r'(\d{1,3}(?:\.\d+)?)\s*(?:L|lakh|lakhs?|lac)\b(?:\s*(?:per\s+annum|p\.?a\.?|CTC))',
    re.IGNORECASE
)
_INR_MONTHLY_PAT = re.compile(
    r'(?:INR|Rs\.?|₹)\s*(\d{1,6}(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(?:per\s+month|/\s*month|p\.?m\.?|monthly)',
    re.IGNORECASE
)
_INR_ANNUAL_PAT = re.compile(
    r'(?:INR|Rs\.?|₹)\s*(\d{1,10}(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(?:per\s+(?:year|annum)|/\s*yr|annual|p\.?a\.?|CTC)?',
    re.IGNORECASE
)
_USD_RANGE_PAT = re.compile(
    r'(?:\$|USD\s*)(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?\s*[-–to]+\s*'
    r'(?:\$|USD\s*)?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?\s*'
    r'(?:per\s+(?:year|yr|annum)|/\s*yr|annual|USD|usd)?',
    re.IGNORECASE
)
_USD_SINGLE_PAT = re.compile(
    r'(?:USD|usd|\$)\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]?\s*'
    r'(?:per\s+(?:year|yr|annum)|/\s*yr|annual)?',
    re.IGNORECASE
)


def _clean_num(s: str) -> float:
    """Remove commas, parse float."""
    return float(s.replace(",", "").strip())


def extract_salary(text: str) -> dict:
    """
    Extract salary information from job description or salary field text.
    Returns dict: { salary_inr_lpa_min, salary_inr_lpa_max, salary_display, currency }
    """
    if not text:
        return {}
    text = str(text)

    # 1. LPA range: "12-18 LPA", "8.5 to 15 Lakhs"
    m = _LPA_RANGE_PAT.search(text)
    if m:
        lo, hi = _clean_num(m.group(1)), _clean_num(m.group(2))
        return {
            "salary_inr_lpa_min": lo,
            "salary_inr_lpa_max": hi,
            "salary_display": f"₹{lo:.0f}L–₹{hi:.0f}L/yr",
            "currency": "INR"
        }

    # 2. LPA single: "15 LPA", "10 Lakhs CTC"
    m = _LPA_SINGLE_PAT.search(text)
    if m:
        val = _clean_num(next(g for g in m.groups() if g is not None))
        return {
            "salary_inr_lpa_min": val,
            "salary_inr_lpa_max": val,
            "salary_display": f"₹{val:.0f}L/yr",
            "currency": "INR"
        }


    # 3. INR monthly: "₹25,000/month" → annualize → LPA
    m = _INR_MONTHLY_PAT.search(text)
    if m:
        monthly = _clean_num(m.group(1))
        annual_lpa = (monthly * 12) / INR_LPA_DIVISOR
        return {
            "salary_inr_lpa_min": round(annual_lpa, 2),
            "salary_inr_lpa_max": round(annual_lpa, 2),
            "salary_display": f"₹{monthly/1000:.0f}k/mo (~₹{annual_lpa:.1f}L/yr)",
            "currency": "INR"
        }

    # 4. USD range: "$80,000 - $120,000" or "$80k-$120k"
    m = _USD_RANGE_PAT.search(text)
    if m:
        lo_str, hi_str = m.group(1), m.group(2)
        lo = _clean_num(lo_str)
        hi = _clean_num(hi_str)
        # Detect "k" suffix
        full_match = m.group(0).lower()
        if lo < 500:  # Likely in thousands
            lo, hi = lo * 1000, hi * 1000
        lo_inr_lpa = (lo * USD_TO_INR) / INR_LPA_DIVISOR
        hi_inr_lpa = (hi * USD_TO_INR) / INR_LPA_DIVISOR
        lo_k = int(lo / 1000)
        hi_k = int(hi / 1000)
        return {
            "salary_inr_lpa_min": round(lo_inr_lpa, 1),
            "salary_inr_lpa_max": round(hi_inr_lpa, 1),
            "salary_display": f"${lo_k}k–${hi_k}k (~₹{lo_inr_lpa:.0f}L–₹{hi_inr_lpa:.0f}L)",
            "currency": "USD"
        }

    # 5. USD single: "$95,000" or "USD 95000"
    m = _USD_SINGLE_PAT.search(text)
    if m:
        val = _clean_num(m.group(1))
        if val < 500:
            val = val * 1000
        val_inr_lpa = (val * USD_TO_INR) / INR_LPA_DIVISOR
        val_k = int(val / 1000)
        return {
            "salary_inr_lpa_min": round(val_inr_lpa, 1),
            "salary_inr_lpa_max": round(val_inr_lpa, 1),
            "salary_display": f"${val_k}k (~₹{val_inr_lpa:.0f}L/yr)",
            "currency": "USD"
        }

    return {}


# =========================================================================
# COMPANY CATEGORY CLASSIFICATION
# =========================================================================

_VENDOR_COMPANIES = {
    "crowdstrike", "sentinelone", "palo alto networks", "paloaltonetworks",
    "zscaler", "cloudflare", "sophos", "qualys", "tenable", "rapid7",
    "snyk", "lacework", "wiz", "vectra", "vectra ai", "abnormal security",
    "axonius", "orca security", "darktrace", "cyberark", "beyondtrust",
    "sailpoint", "saviynt", "imperva", "proofpoint", "mimecast", "forcepoint",
    "fortinet", "checkpoint", "cisco", "f5", "barracuda", "trellix", "mcafee",
    "symantec", "broadcom security", "bitdefender", "kaspersky", "eset",
    "cybereason", "nozomi networks", "claroty", "dragos", "armis",
    "pentera", "recorded future", "drata", "vanta", "secureframe",
    "threatlocker", "hackerone", "bugcrowd", "netspi", "intigriti",
    "synack", "cobalt", "cobalt.io", "detectify", "bishop fox", "bishopfox",
    "offensive security", "offsec", "exabeam", "securonix", "logrhythm",
    "sumo logic", "splunk", "ibm qradar", "microsoft sentinel",
    "elastic security", "datadog security", "huntress", "corelight",
    "stairwell", "expel", "red canary", "blumira"
}

_MSSP_COMPANIES = {
    "secureworks", "arctic wolf", "herjavec", "optiv", "ntt security",
    "trustwave", "verizon business", "orange cyberdefense", "atos security",
    "barrracuda", "ciphertechs", "coalfire", "kudelski security",
    "herjavec group", "vigilant", "pricewaterhousecoopers security",
    "seconize", "sequretek", "lucideus", "indusface", "webwerks",
    "cybersuraksha", "tata tele business services", "ttbs",
    "sisa", "instasafe", "kratikal", "aujas", "appviewx",
    "suma soft", "novac technology", "briskinfosec", "iarmor",
    "fidelis cybersecurity", "cipher", "netsync"
}

_CONSULTING_BIG4 = {
    "deloitte", "pwc", "pricewaterhousecoopers", "kpmg", "ey",
    "ernst & young", "ernst young", "accenture", "capgemini",
    "ibm", "ibm consulting", "ibm global services", "bcg",
    "booz allen hamilton", "booz allen", "leidos", "saic",
    "mantech", "cognizant", "mindtree", "mphasis", "hexaware",
    "infosys bpm"
}

_INDIAN_IT = {
    "tata consultancy", "tcs", "wipro", "infosys", "hcl", "hcltech",
    "hcl technologies", "ltimindtree", "lti", "mindtree",
    "tech mahindra", "techmahindra", "mphasis", "hexaware",
    "persistent systems", "cyient", "sonata software", "niit technologies",
    "mastech", "zensar", "birlasoft", "tata elxsi", "l&t technology",
    "larsen toubro", "l&t infotech", "nagarro", "sasken", "kellton tech"
}

_GOVERNMENT = {
    "cert-in", "cert in", "drdo", "nic", "ncsc", "cisa", "nsa", "dod",
    "isro", "bel", "hal", "defence research", "department of defence",
    "ministry of defence", "government of india", "indian navy",
    "indian army", "indian air force", "central government", "state government",
    "national informatics", "cdac", "c-dac", "iit", "nit",
    "dsci", "nasscom", "nciipc"
}


def classify_company(company_name: str) -> str:
    """
    Classify company into a category string.
    Returns: 'vendor', 'mssp', 'consulting', 'indian_it', 'government', or 'other'
    """
    if not company_name:
        return "other"
    name_lower = company_name.lower().strip()

    # Match against sets (exact or partial substring)
    if any(v in name_lower or name_lower in v for v in _VENDOR_COMPANIES):
        return "vendor"
    if any(m in name_lower or name_lower in m for m in _MSSP_COMPANIES):
        return "mssp"
    if any(c in name_lower or name_lower in c for c in _INDIAN_IT):
        return "indian_it"
    if any(c in name_lower or name_lower in c for c in _CONSULTING_BIG4):
        return "consulting"
    if any(g in name_lower or name_lower in g for g in _GOVERNMENT):
        return "government"
    return "other"



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
    domain_tags: List[str]
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "USD"
    description: str = ""
    apply_url: str = ""
    posted_date: Optional[str] = None
    discovered_at: str = ""
    hash: str = ""
    seniority_level: str = ""   # junior / mid / senior / lead / manager
    skills_required: str = "[]" # JSON list of extracted skills


INDIA_LOCATIONS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune",
    "delhi", "noida", "gurgaon", "gurugram", "chennai", "kolkata",
    "ahmedabad", "jaipur", "kochi", "cochin", "indore", "chandigarh",
    "trivandrum", "thiruvananthapuram", "bhubaneswar", "coimbatore",
    "lucknow", "surat", "nagpur", "patna", "bhopal", "visakhapatnam",
    "vadodara", "agra", "nashik", "faridabad", "meerut", "rajkot",
    "kalyan", "vasai", "pimpri", "thane", "navi mumbai"
]

CYBER_TITLE_PATTERNS = [
    r'\b(cyber|cybersecurity|infosec|appsec|devsecops|secops)\b',
    r'\b(information security|it security|cloud security|network security|systems? security)\b',
    r'\b(product security|application security|software security|data security)\b',
    r'\b(security engineer|security analyst|security architect|security consultant|security specialist)\b',
    r'\b(security researcher|security operations|security manager|security director|security lead)\b',
    r'\b(security intern|security trainee|cyber intern|infosec intern)\b',
    r'\b(soc|siem|soar)\b',
    r'\b(pentest|pentester|penetration test\w*)\b',
    r'\b(red team|blue team|purple team)\b',
    r'\b(threat\s*(intel|hunt|research|detect|analyst))\b',
    r'\b(malware|reverse engineer\w*)\b',
    r'\b(vulnerability|vulnerabilities)\b',
    r'\b(incident\s*(response|responder|handler))\b',
    r'\b(forensic|forensics|dfir)\b',
    r'\b(cryptograph\w*)\b',
    r'\b(identity\s*(&|and)?\s*access|iam\s*engineer|iam\s*analyst)\b',
    r'\b(grc\s*(analyst|engineer|specialist|consultant)?)\b',
    r'\b(ciso|chief information security officer|iso\s*27001|soc\s*2\s*compliance)\b',
    r'\b(bug bounty|ethical hack\w*)\b',
    r'\b(zero trust|cnapp|edr|xdr)\b',
    r'\bsecurity\b'
]

PHYSICAL_SECURITY_EXCLUSIONS = [
    r'^(security officer|security guard|patrol officer|armed security)$',
    r'\b(security guard|patrol officer|loss prevention)\b'
]

NON_CYBER_TITLE_EXCLUSIONS = [
    r'\b(accountant|accounting|buchhalt\w*)\b',
    r'\b(social media|content creator|copywriter)\b',
    r'\b(sales manager|account executive|vertrieb|sales rep\w*)\b',
    r'\b(marketing|seo|growth marketer)\b',
    r'\b(recruiter|recruiting|talent acquisition|personalberat\w*)\b',
    r'\b(nurse|physio|arzt|krankenpflege|bauphysi\w*)\b',
    r'\b(civil engineer|mechanical engineer|maschinenbau|bauleiter)\b',
    r'\b(real estate|immobilien)\b',
    r'\b(graphic designer|product designer)\b',
    r'\b(warehouse|driver|koch|gastronomie|hotel)\b'
]

SENIORITY_PATTERNS = {
    "junior":  [r'\b(junior|jr\.?|entry[\s-]level|associate|graduate|new\s*grad|intern|trainee|co[\s-]?op)\b'],
    "mid":     [r'\b(mid[\s-]level|intermediate|ii|2)\b'],
    "senior":  [r'\b(senior|sr\.?|iii|3|experienced)\b'],
    "lead":    [r'\b(lead|principal|staff|tech\s*lead|team\s*lead)\b'],
    "manager": [r'\b(manager|director|head\s*of|vp\s*of|vice\s*president|ciso|chief)\b']
}

SKILLS_KEYWORDS = [
    "python", "go", "golang", "rust", "java", "c\\+\\+", "kubernetes", "docker",
    "terraform", "aws", "azure", "gcp", "splunk", "elastic", "sigma", "yara",
    "burp suite", "metasploit", "nessus", "nmap", "wireshark", "ida pro",
    "ghidra", "radare2", "nuclei", "oscp", "ceh", "cissp", "cism", "cisa",
    "comptia security\\+", "comptia", "penetration testing", "owasp",
    "siem", "soar", "edr", "xdr", "threat hunting", "malware analysis",
    "reverse engineering", "incident response", "forensics", "dfir",
    "threat intelligence", "vulnerability management", "cloud security",
    "zero trust", "iam", "oauth", "saml", "active directory", "ldap",
    "linux", "windows server", "powershell", "bash", "api security",
    "devsecops", "ci/cd security", "supply chain security"
]


def is_strictly_cyber_job(title: str, description: str = "") -> bool:
    if not title:
        return False
    t = title.lower().strip()
    for exc in PHYSICAL_SECURITY_EXCLUSIONS:
        if re.search(exc, t):
            return False
    for exc in NON_CYBER_TITLE_EXCLUSIONS:
        if re.search(exc, t):
            return False
    for p in CYBER_TITLE_PATTERNS:
        if re.search(p, t):
            return True
    return False


def is_india_location(location: Optional[str]) -> bool:
    if not location:
        return False
    loc = location.lower().strip()
    if re.search(r'\b(india|ind)\b', loc):
        if 'indiana' in loc or 'indianapolis' in loc:
            pass
        else:
            return True
    for c in INDIA_LOCATIONS:
        if re.search(rf'\b{re.escape(c)}\b', loc):
            return True
    return False


def is_target_opportunity(location: Optional[str], remote: Any, job_type: Optional[str], title: str = "") -> bool:
    if title and not is_strictly_cyber_job(title):
        return False
    if is_india_location(location):
        return True
    loc_str = (location or "").lower()
    is_rem = bool(remote) or ("remote" in loc_str or "anywhere" in loc_str or "online" in loc_str)
    is_intern = (job_type or "").lower() == "internship" or "intern" in (title or "").lower()
    return is_rem and is_intern


def detect_seniority(title: str) -> str:
    t = title.lower()
    for level, patterns in SENIORITY_PATTERNS.items():
        for p in patterns:
            if re.search(p, t):
                return level
    return "mid"


def extract_skills(description: str) -> List[str]:
    if not description:
        return []
    text = description.lower()
    found = []
    for skill in SKILLS_KEYWORDS:
        if re.search(rf'\b{skill}\b', text) and skill not in found:
            found.append(skill)
    return found[:15]


def sanitize_apply_url(url: Optional[str], title: str = "", company: str = "") -> str:
    if not url or not url.strip() or url.strip() == "#":
        q = urllib.parse.quote_plus(f"{company} {title} careers security".strip())
        return f"https://www.google.com/search?q={q}"
    clean_url = url.strip()
    clean_url = clean_url.replace("arbeitnow.co.uk", "arbeitnow.com")
    if "?" in clean_url:
        parts = clean_url.split("?", 1)
        base, qs = parts[0], parts[1]
        try:
            params = urllib.parse.parse_qsl(qs, keep_blank_values=True)
            seen = set()
            unique_params = []
            for k, v in params:
                if (k, v) not in seen:
                    seen.add((k, v))
                    unique_params.append((k, v))
            clean_url = base + ("?" + urllib.parse.urlencode(unique_params) if unique_params else "")
        except Exception:
            pass
    return clean_url


def generate_application_routes(title: str, company: str, apply_url: Optional[str]) -> Dict[str, str]:
    direct = sanitize_apply_url(apply_url, title, company)
    t_clean = re.sub(r"\(.*?\)", "", title or "").replace("at " + company, "").strip()
    c_clean = company if company and company != "Unknown" else ""
    google_q = urllib.parse.quote_plus(f"{c_clean} {t_clean} careers security".strip())
    linkedin_q = urllib.parse.quote_plus(f"{t_clean} {c_clean}".strip())
    company_q = urllib.parse.quote_plus(f"{c_clean} cybersecurity careers jobs".strip())
    return {
        "direct_url": direct,
        "google_jobs_url": f"https://www.google.com/search?q={google_q}",
        "linkedin_jobs_url": f"https://www.linkedin.com/jobs/search/?keywords={linkedin_q}",
        "company_careers_url": f"https://www.google.com/search?q={company_q}"
    }


class JobDatabase:
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            # Enable WAL mode for concurrent reads + writes
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("PRAGMA cache_size=10000")

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
                    hash TEXT NOT NULL UNIQUE,
                    seniority_level TEXT DEFAULT 'mid',
                    skills_required TEXT DEFAULT '[]'
                )
            """)

            # Add new columns to existing table if upgrading
            for col, coldef in [
                ("seniority_level", "TEXT DEFAULT 'mid'"),
                ("skills_required", "TEXT DEFAULT '[]'"),
                ("salary_display", "TEXT DEFAULT ''"),
                ("salary_inr_lpa_min", "REAL DEFAULT NULL"),
                ("salary_inr_lpa_max", "REAL DEFAULT NULL"),
                ("company_category", "TEXT DEFAULT 'other'")
            ]:
                try:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coldef}")
                except Exception:
                    pass  # Column already exists

            # Scrape history tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrape_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    new_jobs INTEGER DEFAULT 0,
                    total_fetched INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'ok',
                    error TEXT
                )
            """)

            # Application tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    status TEXT DEFAULT 'applied'
                )
            """)

            # Sent alerts dedup table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    fingerprint TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
            """)

            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON jobs(hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_discovered ON jobs(discovered_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_company ON jobs(company)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_type ON jobs(job_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_seniority ON jobs(seniority_level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_location_type_remote ON jobs(location, job_type, remote)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_company_category ON jobs(company_category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_salary_lpa ON jobs(salary_inr_lpa_max)")

            # FTS5 virtual table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                    title, company, description, location,
                    content=jobs, content_rowid=rowid
                )
            """)

            # FTS triggers to keep FTS index in sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
                    INSERT INTO jobs_fts(rowid, title, company, description, location)
                    VALUES (new.rowid, new.title, new.company, new.description, new.location);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
                    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, location)
                    VALUES('delete', old.rowid, old.title, old.company, old.description, old.location);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE ON jobs BEGIN
                    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, location)
                    VALUES('delete', old.rowid, old.title, old.company, old.description, old.location);
                    INSERT INTO jobs_fts(rowid, title, company, description, location)
                    VALUES (new.rowid, new.title, new.company, new.description, new.location);
                END
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _generate_hash(job: JobEntry) -> str:
        key = f"{job.title}|{job.company}|{job.location}|{job.apply_url}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _classify_job_type(title: str, description: str) -> str:
        text = (title + " " + description).lower()
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
        found = []
        for kw in keywords:
            kw_lower = kw.lower()
            if re.search(rf'\b{re.escape(kw_lower)}\b', text_lower):
                found.append(kw)
        return found

    def insert_job(self, job: JobEntry, keywords: List[str]) -> bool:
        if not is_strictly_cyber_job(job.title, job.description):
            return False

        job.discovered_at = datetime.utcnow().isoformat()
        job.hash = self._generate_hash(job)
        job.job_type = self._classify_job_type(job.title, job.description)
        job.domain_tags = self._extract_domain_tags(job.title + " " + job.description, keywords)
        job.seniority_level = detect_seniority(job.title)
        skills = extract_skills(job.description)
        job.skills_required = json.dumps(skills)

        # Salary & company category extraction
        salary_info = extract_salary(f"{job.title} {job.description}")
        salary_display = salary_info.get("salary_display", "")
        salary_inr_lpa_min = salary_info.get("salary_inr_lpa_min")
        salary_inr_lpa_max = salary_info.get("salary_inr_lpa_max")
        company_category = classify_company(job.company)

        with self._conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO jobs (
                        id, source, source_url, title, company, location, remote,
                        job_type, domain_tags, salary_min, salary_max, salary_currency,
                        description, apply_url, posted_date, discovered_at, hash,
                        seniority_level, skills_required, salary_display,
                        salary_inr_lpa_min, salary_inr_lpa_max, company_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.source, job.source_url, job.title, job.company,
                    job.location, int(job.remote), job.job_type,
                    json.dumps(job.domain_tags), job.salary_min, job.salary_max,
                    job.salary_currency, job.description, job.apply_url,
                    job.posted_date, job.discovered_at, job.hash,
                    job.seniority_level, job.skills_required, salary_display,
                    salary_inr_lpa_min, salary_inr_lpa_max, company_category
                ))
                return True
            except sqlite3.IntegrityError:
                return False

    def log_scrape_run(self, source: str, new_jobs: int, total_fetched: int, status: str = "ok", error: str = "") -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO scrape_runs (source, run_at, new_jobs, total_fetched, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source, datetime.utcnow().isoformat(), new_jobs, total_fetched, status, error))

    def get_scrape_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM scrape_runs ORDER BY run_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_new_jobs(self, since: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM jobs WHERE discovered_at > ? ORDER BY discovered_at DESC LIMIT ?
            """, (since, limit)).fetchall()
            return [dict(row) for row in rows]

    def get_new_jobs_count_since(self, since: str) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs WHERE discovered_at > ?", (since,)).fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            internships = conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'internship'").fetchone()[0]
            by_type = conn.execute("SELECT job_type, COUNT(*) as c FROM jobs GROUP BY job_type").fetchall()
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
            try:
                data["skills_required"] = json.loads(data.get("skills_required") or "[]")
            except Exception:
                data["skills_required"] = []

            loc = data.get("location")
            rem = data.get("remote")
            jt = data.get("job_type")
            tit = data.get("title", "")
            comp = data.get("company", "")
            is_ind = is_india_location(loc)
            is_tgt = is_target_opportunity(loc, rem, jt, tit)

            data["is_india"] = is_ind
            data["is_target_match"] = is_tgt
            data["target_badge"] = "🇮🇳 India • Office / WFH" if is_ind else ("🌐 Global • Online Internship" if is_tgt else None)
            data["application_routes"] = generate_application_routes(tit, comp, data.get("apply_url"))
            data["apply_url"] = data["application_routes"]["direct_url"]

            # Check if applied
            applied_row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            data["applied"] = dict(applied_row) if applied_row else None
            return data

    def get_sources_stats(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT source, COUNT(*) as count, MAX(discovered_at) as last_seen
                FROM jobs
                GROUP BY source
                ORDER BY count DESC
            """).fetchall()
            return [
                {
                    "source": r["source"],
                    "count": r["count"],
                    "last_seen": r["last_seen"],
                    "status": "operational"
                }
                for r in rows
            ]

    def get_search_suggestions(self, q: str, limit: int = 10) -> Dict[str, List[str]]:
        q_pattern = f"%{q}%"
        with self._conn() as conn:
            title_rows = conn.execute(
                "SELECT DISTINCT title FROM jobs WHERE title LIKE ? LIMIT ?", (q_pattern, limit)
            ).fetchall()
            company_rows = conn.execute(
                "SELECT DISTINCT company FROM jobs WHERE company LIKE ? LIMIT ?", (q_pattern, limit)
            ).fetchall()
            return {
                "titles": [r[0] for r in title_rows],
                "companies": [r[0] for r in company_rows]
            }

    def mark_applied(self, job_id: str, notes: str = "") -> bool:
        with self._conn() as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO applications (job_id, applied_at, notes, status)
                    VALUES (?, ?, ?, 'applied')
                """, (job_id, datetime.utcnow().isoformat(), notes))
                return True
            except Exception:
                return False

    def unmark_applied(self, job_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
            return True

    def get_applications(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT j.*, a.applied_at, a.notes, a.status as app_status
                FROM applications a
                JOIN jobs j ON j.id = a.job_id
                ORDER BY a.applied_at DESC
            """).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["domain_tags"] = json.loads(item.get("domain_tags") or "[]")
                except Exception:
                    item["domain_tags"] = []
                try:
                    item["skills_required"] = json.loads(item.get("skills_required") or "[]")
                except Exception:
                    item["skills_required"] = []
                item["application_routes"] = generate_application_routes(
                    item.get("title", ""), item.get("company", ""), item.get("apply_url")
                )
                items.append(item)
            return items

    def is_alert_sent(self, fingerprint: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM sent_alerts WHERE fingerprint = ?", (fingerprint,)).fetchone()
            return row is not None

    def mark_alert_sent(self, fingerprint: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO sent_alerts (fingerprint, sent_at)
                VALUES (?, ?)
            """, (fingerprint, datetime.utcnow().isoformat()))

    def get_jobs_history_by_day(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get job discovery counts grouped by day for the timeline chart."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT DATE(discovered_at) as day, COUNT(*) as count
                FROM jobs
                WHERE discovered_at >= DATE('now', ?)
                GROUP BY DATE(discovered_at)
                ORDER BY day ASC
            """, (f'-{days} days',)).fetchall()
            return [{"day": r["day"], "count": r["count"]} for r in rows]

    def get_jobs_filtered(
        self,
        search: str = "",
        job_type: str = "",
        domain: str = "",
        remote: Optional[bool] = None,
        source: str = "",
        seniority: str = "",
        company_category: str = "",
        min_salary_lpa: Optional[float] = None,
        sort_by: str = "newest",
        location_scope: str = "all",
        target_only: bool = False,
        page: int = 1,
        page_size: int = 24
    ) -> Dict[str, Any]:
        conditions = []
        params = []

        if search:
            # Try FTS5 first (fast), fallback to LIKE
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ? OR description LIKE ?)")
            search_pattern = f"%{search.strip()}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        if job_type and job_type != "all":
            conditions.append("job_type = ?")
            params.append(job_type)

        if seniority and seniority != "all":
            conditions.append("seniority_level = ?")
            params.append(seniority)

        if company_category and company_category != "all":
            conditions.append("company_category = ?")
            params.append(company_category)

        if min_salary_lpa is not None and min_salary_lpa > 0:
            conditions.append("salary_inr_lpa_max >= ?")
            params.append(min_salary_lpa)

        if domain and domain != "all":
            conditions.append("domain_tags LIKE ?")
            params.append(f"%{domain.strip()}%")

        if remote is not None:
            conditions.append("remote = ?")
            params.append(1 if remote else 0)

        if source and source != "all":
            conditions.append("source = ?")
            params.append(source)

        india_sql_conditions = " OR ".join([f"location LIKE '%{k}%'" for k in INDIA_LOCATIONS])
        india_sql = f"(({india_sql_conditions}) AND location NOT LIKE '%Indiana%' AND location NOT LIKE '%Indianapolis%')"
        remote_intern_sql = "((job_type = 'internship' OR title LIKE '%intern%') AND (remote = 1 OR location LIKE '%Remote%' OR location LIKE '%Online%'))"

        if target_only or location_scope == "target":
            conditions.append(f"({india_sql} OR {remote_intern_sql})")
        elif location_scope == "india":
            conditions.append(india_sql)
        elif location_scope == "global_remote_intern":
            conditions.append(f"(NOT {india_sql} AND {remote_intern_sql})")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sort_map = {
            "newest": "discovered_at DESC, id DESC",
            "oldest": "discovered_at ASC, id ASC",
            "title": "title ASC",
            "company": "company ASC",
            "salary_high": "salary_inr_lpa_max DESC, discovered_at DESC"
        }
        order_clause = f"ORDER BY {sort_map.get(sort_by, 'discovered_at DESC, id DESC')}"
        offset = max(0, (page - 1) * page_size)

        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM jobs {where_clause}", tuple(params)).fetchone()[0]
            query = f"SELECT * FROM jobs {where_clause} {order_clause} LIMIT ? OFFSET ?"
            rows = conn.execute(query, tuple(params) + (page_size, offset)).fetchall()

            items = []
            applied_ids = {r[0] for r in conn.execute("SELECT job_id FROM applications").fetchall()}

            for row in rows:
                item = dict(row)
                try:
                    item["domain_tags"] = json.loads(item.get("domain_tags") or "[]")
                except Exception:
                    item["domain_tags"] = []
                try:
                    item["skills_required"] = json.loads(item.get("skills_required") or "[]")
                except Exception:
                    item["skills_required"] = []

                loc = item.get("location")
                rem = item.get("remote")
                jt = item.get("job_type")
                tit = item.get("title", "")
                comp = item.get("company", "")
                is_ind = is_india_location(loc)
                is_tgt = is_target_opportunity(loc, rem, jt, tit)

                item["is_india"] = is_ind
                item["is_target_match"] = is_tgt
                item["target_badge"] = "🇮🇳 India • Office / WFH" if is_ind else ("🌐 Global • Online Internship" if is_tgt else None)
                item["application_routes"] = generate_application_routes(tit, comp, item.get("apply_url"))
                item["apply_url"] = item["application_routes"]["direct_url"]
                item["applied"] = item["id"] in applied_ids
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
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if total == 0:
                return {
                    "total": 0, "internships": 0, "remote": 0, "remote_pct": 0,
                    "target_count": 0, "india_count": 0, "global_remote_intern_count": 0,
                    "by_type": {}, "by_source": {}, "top_companies": [],
                    "top_domains": {}, "last_scraped": None,
                    "by_seniority": {}, "applied_count": 0
                }

            internships = conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'internship'").fetchone()[0]
            remote_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE remote = 1").fetchone()[0]

            india_sql_conditions = " OR ".join([f"location LIKE '%{k}%'" for k in INDIA_LOCATIONS])
            india_sql = f"(({india_sql_conditions}) AND location NOT LIKE '%Indiana%' AND location NOT LIKE '%Indianapolis%')"
            remote_intern_sql = "((job_type = 'internship' OR title LIKE '%intern%') AND (remote = 1 OR location LIKE '%Remote%' OR location LIKE '%Online%'))"

            india_count = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {india_sql}").fetchone()[0]
            global_remote_intern_count = conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE NOT {india_sql} AND {remote_intern_sql}"
            ).fetchone()[0]
            target_count = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {india_sql} OR {remote_intern_sql}").fetchone()[0]

            by_type = {r["job_type"]: r["c"] for r in conn.execute(
                "SELECT job_type, COUNT(*) as c FROM jobs GROUP BY job_type ORDER BY c DESC"
            ).fetchall()}

            by_seniority = {r["seniority_level"]: r["c"] for r in conn.execute(
                "SELECT seniority_level, COUNT(*) as c FROM jobs GROUP BY seniority_level ORDER BY c DESC"
            ).fetchall()}

            by_company_category = {r["company_category"]: r["c"] for r in conn.execute(
                "SELECT company_category, COUNT(*) as c FROM jobs GROUP BY company_category ORDER BY c DESC"
            ).fetchall()}

            salary_jobs_count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE salary_display IS NOT NULL AND salary_display != ''"
            ).fetchone()[0]

            by_source = {r["source"]: r["c"] for r in conn.execute(
                "SELECT source, COUNT(*) as c FROM jobs GROUP BY source ORDER BY c DESC LIMIT 10"
            ).fetchall()}

            top_companies = [{"company": r["company"], "count": r["c"]} for r in conn.execute(
                "SELECT company, COUNT(*) as c FROM jobs WHERE company != 'Unknown' GROUP BY company ORDER BY c DESC LIMIT 10"
            ).fetchall()]

            last_row = conn.execute("SELECT discovered_at FROM jobs ORDER BY discovered_at DESC LIMIT 1").fetchone()
            last_scraped = last_row[0] if last_row else None

            applied_count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

            domain_counts = self.get_domain_counts()
            top_domains = {d["tag"]: d["count"] for d in domain_counts[:8]}

            return {
                "total": total,
                "internships": internships,
                "remote": remote_count,
                "remote_pct": round((remote_count / total) * 100, 1) if total > 0 else 0,
                "target_count": target_count,
                "india_count": india_count,
                "global_remote_intern_count": global_remote_intern_count,
                "by_type": by_type,
                "by_seniority": by_seniority,
                "by_company_category": by_company_category,
                "salary_jobs_count": salary_jobs_count,
                "by_source": by_source,
                "top_companies": top_companies,
                "top_domains": top_domains,
                "last_scraped": last_scraped,
                "applied_count": applied_count
            }

    def get_domain_counts(self) -> List[Dict[str, Any]]:
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


    def backfill_enrichment(self) -> Dict[str, int]:
        """Backfill existing jobs with company category and salary extraction."""
        updated = 0
        with self._conn() as conn:
            rows = conn.execute("SELECT id, title, company, description, salary_display, company_category FROM jobs").fetchall()
            for r in rows:
                jid = r["id"]
                comp = r["company"]
                desc = r["description"] or ""
                current_disp = r["salary_display"] or ""
                current_cat = r["company_category"] or "other"

                new_cat = classify_company(comp)
                sal = extract_salary(desc) if not current_disp else {}

                updates = []
                params = []

                if new_cat != current_cat:
                    updates.append("company_category = ?")
                    params.append(new_cat)

                if sal:
                    updates.append("salary_display = ?")
                    params.append(sal.get("salary_display", ""))
                    updates.append("salary_inr_lpa_min = ?")
                    params.append(sal.get("salary_inr_lpa_min"))
                    updates.append("salary_inr_lpa_max = ?")
                    params.append(sal.get("salary_inr_lpa_max"))

                if updates:
                    params.append(jid)
                    conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", tuple(params))
                    updated += 1
        return {"updated": updated, "total": len(rows)}

    def vacuum(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA incremental_vacuum")

    def close(self):
        pass


if __name__ == "__main__":
    db = JobDatabase("test_jobs.db")
    print("Database initialized:", db.get_stats())
