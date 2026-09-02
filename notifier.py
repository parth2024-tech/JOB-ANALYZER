import os
import asyncio
import hashlib
import aiohttp
from typing import List, Dict, Any
from dataclasses import dataclass
from loguru import logger


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


class TelegramNotifier:
    MAX_MSG_LEN = 4000  # Telegram hard limit is 4096, use 4000 for safety

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.bot_token}"

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram, respecting the 4000-char limit by chunking."""
        if not self.config.bot_token:
            logger.warning("No Telegram bot token configured. Skipping notification.")
            return False

        chunks = self._chunk_message(text)
        success = True
        for chunk in chunks:
            ok = await self._send_chunk(chunk, parse_mode)
            if not ok:
                success = False
            await asyncio.sleep(0.5)  # Avoid flooding
        return success

    def _chunk_message(self, text: str) -> List[str]:
        """Split text into <=4000 char chunks at paragraph boundaries."""
        if len(text) <= self.MAX_MSG_LEN:
            return [text]
        chunks = []
        while text:
            if len(text) <= self.MAX_MSG_LEN:
                chunks.append(text)
                break
            # Try to split at last newline before limit
            split_pos = text.rfind("\n", 0, self.MAX_MSG_LEN)
            if split_pos == -1:
                split_pos = self.MAX_MSG_LEN
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return chunks

    async def _send_chunk(self, text: str, parse_mode: str) -> bool:
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        retry_count = 3
        for attempt in range(retry_count):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            return True
                        elif resp.status == 429:
                            # Rate limited — respect Retry-After
                            retry_after = int(resp.headers.get("Retry-After", 10))
                            logger.warning(f"Telegram rate limited. Waiting {retry_after}s...")
                            await asyncio.sleep(retry_after)
                        else:
                            error = await resp.text()
                            logger.error(f"Telegram API error: {resp.status} - {error}")
                            return False
            except Exception as e:
                logger.error(f"Telegram send failed (attempt {attempt+1}): {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
        return False

    def _fingerprint(self, jobs: List[Dict[str, Any]]) -> str:
        """SHA-1 fingerprint of job IDs for dedup check."""
        ids = sorted(j.get("id", "") for j in jobs)
        return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]

    def format_india_alert(self, jobs: List[Dict[str, Any]]) -> str:
        lines = ["🇮🇳 <b>India Cybersecurity Opportunities</b>", ""]
        for i, job in enumerate(jobs[:8], 1):
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            location = job.get("location", "India")
            job_type = job.get("job_type", "full-time")
            seniority = job.get("seniority_level", "mid")
            apply_url = job.get("apply_url", "")
            routes = job.get("application_routes", {})
            direct = routes.get("direct_url", apply_url)

            type_emoji = "🎓" if job_type == "internship" else "💼"
            seniority_badge = {"junior": "🟢", "mid": "🔵", "senior": "🟡", "lead": "🟠", "manager": "🔴"}.get(seniority, "🔵")

            lines.append(
                f"{i}. {type_emoji} {seniority_badge} <b>{title}</b>\n"
                f"   🏢 {company} • 📍 {location}\n"
                f"   🔗 <a href='{direct}'>Apply Now</a>"
            )
        if len(jobs) > 8:
            lines.append(f"\n... and {len(jobs) - 8} more India jobs!")
        return "\n".join(lines)

    def format_global_intern_alert(self, jobs: List[Dict[str, Any]]) -> str:
        lines = ["🌐 <b>Global Online Cybersecurity Internships</b>", ""]
        for i, job in enumerate(jobs[:8], 1):
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            location = job.get("location", "Remote")
            apply_url = job.get("apply_url", "")
            routes = job.get("application_routes", {})
            direct = routes.get("direct_url", apply_url)
            lines.append(
                f"{i}. 🎓 <b>{title}</b>\n"
                f"   🌍 {company} • Remote\n"
                f"   🔗 <a href='{direct}'>Apply Now</a>"
            )
        if len(jobs) > 8:
            lines.append(f"\n... and {len(jobs) - 8} more remote internships!")
        return "\n".join(lines)

    def format_job_alert(self, jobs: List[Dict[str, Any]]) -> str:
        """Format general jobs into a Telegram message (handles all types)."""
        if not jobs:
            return ""
        lines = ["🔐 <b>New CyberSecurity Opportunities Found</b>", ""]
        for i, job in enumerate(jobs[:10], 1):
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            location = job.get("location", "Remote")
            job_type = job.get("job_type", "full-time")
            tags = job.get("domain_tags", [])
            apply_url = job.get("apply_url", "")
            source = job.get("source", "")
            seniority = job.get("seniority_level", "mid")
            routes = job.get("application_routes", {})
            direct = routes.get("direct_url", apply_url)

            type_emoji = "🎓" if job_type == "internship" else "💼"
            remote_emoji = "🌍" if job.get("remote") else "🏢"
            seniority_badge = {"junior": "🟢 Junior", "mid": "🔵 Mid", "senior": "🟡 Senior",
                               "lead": "🟠 Lead", "manager": "🔴 Manager"}.get(seniority, "🔵")
            tag_str = " ".join([f"#{t.replace(' ', '')}" for t in tags[:3]])

            from database import is_india_location, is_target_opportunity
            if is_india_location(location):
                scope_tag = "🇮🇳 <b>[India • Office/WFH]</b>\n   "
            elif is_target_opportunity(location, job.get("remote"), job_type):
                scope_tag = "🌐 <b>[Global • Online Internship]</b>\n   "
            else:
                scope_tag = ""

            lines.append(
                f"{i}. {type_emoji} <b>{title}</b>\n"
                f"   {scope_tag}{remote_emoji} {company} • {location}\n"
                f"   {seniority_badge} {tag_str}\n"
                f"   🔗 <a href='{direct}'>Apply Here</a> | {source}"
            )

        if len(jobs) > 10:
            lines.append(f"\n... and {len(jobs) - 10} more jobs!")
        lines.append(f"\n📊 Total new: {len(jobs)}")
        return "\n".join(lines)

    async def send_job_alert(self, jobs: List[Dict[str, Any]], db=None) -> bool:
        """Send formatted job alert with dedup check and India-priority split."""
        if not jobs:
            return True

        fingerprint = self._fingerprint(jobs)
        if db and db.is_alert_sent(fingerprint):
            logger.info("Alert already sent for this job batch — skipping dedup.")
            return True

        from database import is_india_location, is_target_opportunity
        india_jobs = [j for j in jobs if is_india_location(j.get("location"))]
        global_intern_jobs = [
            j for j in jobs
            if not is_india_location(j.get("location"))
            and is_target_opportunity(j.get("location"), j.get("remote"), j.get("job_type"))
        ]
        other_jobs = [
            j for j in jobs
            if not is_india_location(j.get("location"))
            and not is_target_opportunity(j.get("location"), j.get("remote"), j.get("job_type"))
        ]

        success = True
        if india_jobs:
            msg = self.format_india_alert(india_jobs)
            ok = await self.send_message(msg)
            success = success and ok

        if global_intern_jobs:
            msg = self.format_global_intern_alert(global_intern_jobs)
            ok = await self.send_message(msg)
            success = success and ok

        if other_jobs and (not india_jobs and not global_intern_jobs):
            msg = self.format_job_alert(other_jobs)
            ok = await self.send_message(msg)
            success = success and ok

        if db:
            db.mark_alert_sent(fingerprint)
        return success

    async def send_summary(self, stats: Dict[str, Any], source_counts: Dict[str, int]) -> bool:
        total = stats.get("total", 0)
        target = stats.get("target_count", 0)
        india = stats.get("india_count", 0)
        glob = stats.get("global_remote_intern_count", 0)

        lines = [
            "📈 <b>CyberSec Job Scraper — Run Summary</b>",
            f"🗄️ Total Jobs: <b>{total}</b>",
            f"🎯 Target Matches: <b>{target}</b> (🇮🇳 India: {india} | 🌐 Global Online Internships: {glob})",
            f"🎓 Internships: {stats.get('internships', 0)}",
            "",
            "<b>New This Run:</b>",
        ]
        new_total = 0
        for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            if count > 0:
                lines.append(f"  • {source}: +{count}")
                new_total += count
        if new_total == 0:
            lines.append("  (No new jobs this run)")
        lines.append(f"\n📊 Total new: {new_total}")

        return await self.send_message("\n".join(lines))


def load_config(config_path: str = "config.yaml") -> TelegramConfig:
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    tg = cfg.get("telegram", {})
    token = os.getenv("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "1650972026")
    return TelegramConfig(bot_token=token, chat_id=chat_id)


async def test_notifier():
    config = load_config()
    if not config.bot_token:
        print("No Telegram bot token configured. Set TELEGRAM_BOT_TOKEN env var.")
        return
    notifier = TelegramNotifier(config)
    await notifier.send_message("🧪 CyberSec Job Scraper test message — System online!")


if __name__ == "__main__":
    asyncio.run(test_notifier())
