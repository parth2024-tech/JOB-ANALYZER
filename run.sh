#!/bin/bash
# CyberSec Job Scraper - Setup & Run Script
# Usage: ./run.sh [command]
# Commands: setup, run, daemon, test, stats, help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

show_help() {
    cat << EOF
🔐 CyberSecurity Job & Internship Scraper
=========================================
FREE • GLOBAL • COMPREHENSIVE

USAGE:
    ./run.sh [COMMAND]

COMMANDS:
    setup       Create venv and install dependencies
    run         Run scraper once
    daemon      Run continuously (every 2 hours)
    test        Test run (no Telegram notifications)
    web [port]  Start interactive web dashboard (default: 8080)
    stats       Show database statistics
    help        Show this help

EXAMPLES:
    ./run.sh setup
    ./run.sh run
    ./run.sh web
    ./run.sh web 8080
    ./run.sh daemon
    ./run.sh test
    ./run.sh stats

ENVIRONMENT:
    TELEGRAM_BOT_TOKEN   Your bot token from @BotFather
    (Optional - can also be set in config.yaml)

CRON EXAMPLE (run at 6 AM and 6 PM daily):
    0 6,18 * * * /home/thor/Desktop/linkedin/run.sh run

SOURCES COVERED:
    ✅ RSS Feeds: InfoSec-Jobs, RemoteSec, CyberSecurityJobSite, OWASP
    ✅ GitHub: SwiftCoders Cybersecurity-Jobs, FuzzySecurity CS-Jobs
    ✅ APIs: Hacker News Hiring, ArbeitNow, RemoteOK Security
    ✅ ATS Boards: CrowdStrike, Cloudflare, Mandiant, Palo Alto, Tenable, Rapid7, Snyk
    ✅ Keywords: Offensive, Defensive, GRC, Cloud, AppSec, Crypto, Forensics, Internships
EOF
}

setup_venv() {
    echo "🔧 Setting up virtual environment..."
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
    echo "📦 Installing dependencies..."
    "$PIP" install --upgrade pip
    "$PIP" install -r requirements.txt
    echo "✅ Setup complete!"
}

run_scraper() {
    if [ ! -f "$PYTHON" ]; then
        echo "❌ Virtual environment not found. Run: ./run.sh setup"
        exit 1
    fi
    "$PYTHON" main.py "$@"
}

case "${1:-help}" in
    setup)
        setup_venv
        ;;
    run)
        run_scraper
        ;;
    daemon)
        run_scraper --daemon
        ;;
    test)
        run_scraper --test
        ;;
    web)
        run_scraper --web --port "${2:-8080}"
        ;;
    stats)
        run_scraper --stats
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "❌ Unknown command: $1"
        show_help
        exit 1
        ;;
esac