import os
import asyncio
import aiohttp
from typing import List, Dict, Any
from dataclasses import dataclass
from loguru import logger


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


class TelegramNotifier:
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config.bot_token}"

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram."""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("Telegram message sent successfully")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Telegram API error: {resp.status} - {error}")
                        return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def format_job_alert(self, jobs: List[Dict[str, Any]]) -> str:
        """Format jobs into a Telegram message."""
        if not jobs:
            return ""

        lines = ["🔐 <b>New CyberSecurity Opportunities Found</b>", ""]

        for i, job in enumerate(jobs[:10], 1):  # Limit to 10 per message
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            location = job.get("location", "Remote")
            job_type = job.get("job_type", "full-time")
            tags = job.get("domain_tags", [])
            apply_url = job.get("apply_url", "")
            source = job.get("source", "")

            type_emoji = "🎓" if job_type == "internship" else "💼"
            remote_emoji = "🌍" if job.get("remote") else "🏢"

            from database import is_india_location, is_target_opportunity
            if is_india_location(location):
                scope_tag = "🇮🇳 <b>[India • Office/WFH]</b>\n"
            elif is_target_opportunity(location, job.get("remote"), job_type):
                scope_tag = "🌐 <b>[Global • Online Internship]</b>\n"
            else:
                scope_tag = ""

            tag_str = " ".join([f"#{t.replace(' ', '')}" for t in tags[:5]])

            lines.append(
                f"{i}. {type_emoji} <b>{title}</b>\n"
                f"   {scope_tag}"
                f"   {remote_emoji} {company} • {location}\n"
                f"   {tag_str}\n"
                f"   🔗 <a href='{apply_url}'>Apply Here</a> | Source: {source}"
            )

        if len(jobs) > 10:
            lines.append(f"\n... and {len(jobs) - 10} more jobs!")

        lines.append(f"\n📊 Total new: {len(jobs)}")
        return "\n".join(lines)

    async def send_job_alert(self, jobs: List[Dict[str, Any]]) -> bool:
        """Send formatted job alert."""
        if not jobs:
            return True
        message = self.format_job_alert(jobs)
        return await self.send_message(message)

    async def send_summary(self, stats: Dict[str, Any], source_counts: Dict[str, int]) -> bool:
        """Send scraping summary."""
        lines = [
            "📈 <b>CyberSec Job Scraper - Run Summary</b>",
            f"Total Jobs in DB: {stats.get('total', 0)}",
            f"Internships: {stats.get('internships', 0)}",
            "",
            "<b>By Type:</b>",
        ]
        for jtype, count in stats.get("by_type", {}).items():
            lines.append(f"  • {jtype}: {count}")

        lines.append("\n<b>New This Run:</b>")
        for source, count in source_counts.items():
            if count > 0:
                lines.append(f"  • {source}: {count}")

        return await self.send_message("\n".join(lines))


def load_config(config_path: str = "config.yaml") -> TelegramConfig:
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    tg = cfg.get("telegram", {})
    # Allow env override
    token = os.getenv("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "1650972026")
    return TelegramConfig(bot_token=token, chat_id=chat_id)


async def test_notifier():
    config = load_config()
    if not config.bot_token:
        print("No Telegram bot token configured. Set TELEGRAM_BOT_TOKEN env var.")
        return

    notifier = TelegramNotifier(config)
    # Test message
    await notifier.send_message("🧪 CyberSec Job Scraper test message - System online!")


if __name__ == "__main__":
    asyncio.run(test_notifier())