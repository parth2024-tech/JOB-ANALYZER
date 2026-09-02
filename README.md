# 🛡️ JOB-ANALYZER — Cybersecurity Intelligence & Opportunity Matrix

A comprehensive, **100% free** cybersecurity job & internship extraction engine paired with a **real-time Cyber Tactical Web Dashboard**.

Aggregates thousands of security opportunities globally across public ATS boards, RSS feeds, open APIs, and curated repositories without relying on rate-limited browser scraping.

---

## ⚡ Key Highlights

- **Multi-Source Aggregation**: Ingests positions from Greenhouse ATS endpoints (Cloudflare, Zscaler, Huntress, Tenable, Corelight, Datadog, Elastic), curated GitHub directories, specialized RSS feeds (WeWorkRemotely), and open JSON APIs (ArbeitNow, RemoteOK, Remotive).
- **Automated Deduplication**: Uses SHA-256 fingerprinting (`title|company|location|apply_url`) stored in an indexed SQLite database to ensure zero duplicate alerts.
- **Smart Triage & Tagging**: Automatically classifies positions into **Internships**, **Full-Time**, **Contract**, and tags specializations (Offensive/Pentest, SOC/Defensive, Cloud Sec, AppSec, GRC, Cryptography, Forensics).
- **Interactive Cyber Tactical Web Dashboard**: Single-page application styled with dark cyber HUD aesthetics, live Telemetry charts (Chart.js), instant search (`/` shortcut), bookmarks, CSV export, and on-demand scraping triggers.
- **Telegram Broadcaster**: Automated alerts sent directly to Telegram channels/bots.

---

## 🚀 Quickstart

### 1. Installation
Clone the repository and run automated setup:
```bash
./run.sh setup
```

### 2. Launch the Web Dashboard
Start the tactical web dashboard at `http://localhost:8080`:
```bash
./run.sh web 8080
```

### 3. Run Scraper
Scrape all configured sources once:
```bash
./run.sh run
```

### 4. Background Daemon / Cron
Run continuously every 2 hours:
```bash
./run.sh daemon
```
Or configure a cron job to run twice daily:
```bash
0 6,18 * * * /path/to/JOB-ANALYZER/run.sh run
```

---

## 📊 Web Dashboard & REST API Endpoints

The web server (`web_server.py`) provides both a web UI and a REST API:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Cyber Tactical Web Dashboard SPA |
| `GET` | `/api/jobs` | Paginated search, domain, type, and remote filters |
| `GET` | `/api/jobs/{id}` | Detailed role brief and application metadata |
| `GET` | `/api/stats` | Telemetry KPIs, role distribution, top specializations |
| `GET` | `/api/domains` | Categorized security domains with real-time counts |
| `GET` | `/api/status` | System health, database size, and scraping lock |
| `POST` | `/api/scrape` | Trigger on-demand scraper run in background |

---

## 🛠️ Project Structure

```
.
├── config.yaml          # Source configurations, Telegram settings, security domain keywords
├── database.py          # SQLite schema, SHA-256 deduplication, filtering & analytics queries
├── jobs.db              # Pre-indexed SQLite database (1,600+ roles)
├── main.py              # CLI orchestrator supporting one-shot, daemon, and web modes
├── notifier.py          # Asynchronous Telegram broadcaster
├── requirements.txt     # Python dependencies (aiohttp, beautifulsoup4, feedparser, etc.)
├── run.sh               # Turnkey shell runner (setup, run, daemon, test, web, stats)
├── scraper.py           # Asynchronous multi-channel scraper engine
├── web_server.py        # Asynchronous aiohttp REST API and web application server
└── static/
    ├── index.html       # Single-Page Web Dashboard interface
    ├── app.js           # Client-side controller (queries, bookmarks, CSV export, charts)
    └── style.css        # Tactical HUD design tokens, glassmorphism, and animations
```

---

## ⚙️ Configuration

Set your Telegram bot token in `config.yaml` or via environment variable:
```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
```
Customize sources, target companies, or domain keywords anytime in `config.yaml`.

