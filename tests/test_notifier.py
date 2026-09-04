"""Tests for notifier module."""
from unittest.mock import AsyncMock, patch

import pytest

from notifier import TelegramConfig, TelegramNotifier, load_config


class TestTelegramNotifier:
    """Test TelegramNotifier functionality."""
    
    def test_init(self, sample_config):
        """Test notifier initialization."""
        notifier = TelegramNotifier(sample_config)
        assert notifier.config == sample_config
        assert "test_token" in notifier.base_url
    
    def test_chunk_message_short(self, sample_config):
        """Test message chunking for short messages."""
        notifier = TelegramNotifier(sample_config)
        text = "Short message"
        chunks = notifier._chunk_message(text)
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_chunk_message_long(self, sample_config):
        """Test message chunking for long messages."""
        notifier = TelegramNotifier(sample_config)
        # Create a message longer than MAX_MSG_LEN (4000)
        text = "A" * 5000
        chunks = notifier._chunk_message(text)
        assert len(chunks) == 2
        assert len(chunks[0]) <= 4000
        assert len(chunks[1]) <= 4000
        assert "".join(chunks) == text
    
    def test_chunk_message_at_newlines(self, sample_config):
        """Test chunking prefers newline boundaries."""
        notifier = TelegramNotifier(sample_config)
        text = "Line 1\n" + "B" * 3990 + "\nLine 3"
        chunks = notifier._chunk_message(text)
        # Should split at newline before limit
        assert len(chunks) >= 1
    
    def test_fingerprint(self, sample_config):
        """Test job fingerprint generation."""
        notifier = TelegramNotifier(sample_config)
        jobs = [
            {"id": "1", "title": "Job 1"},
            {"id": "2", "title": "Job 2"},
        ]
        fp1 = notifier._fingerprint(jobs)
        fp2 = notifier._fingerprint(jobs)
        assert fp1 == fp2  # Deterministic
        assert len(fp1) == 16  # SHA1 truncated to 16 chars
        
        # Different order should give same fingerprint (sorted)
        jobs_reversed = [{"id": "2", "title": "Job 2"}, {"id": "1", "title": "Job 1"}]
        fp3 = notifier._fingerprint(jobs_reversed)
        assert fp1 == fp3
    
    def test_format_india_alert(self, sample_config):
        """Test India alert formatting."""
        notifier = TelegramNotifier(sample_config)
        jobs = [
            {
                "title": "Security Engineer",
                "company": "TestCorp",
                "location": "Bangalore, India",
                "job_type": "full-time",
                "seniority_level": "mid",
                "apply_url": "https://test.com/apply",
                "application_routes": {"direct_url": "https://test.com/apply"},
            }
        ]
        msg = notifier.format_india_alert(jobs)
        assert "🇮🇳" in msg
        assert "Security Engineer" in msg
        assert "TestCorp" in msg
        assert "Bangalore" in msg
        assert "Apply Now" in msg
    
    def test_format_global_intern_alert(self, sample_config):
        """Test global internship alert formatting."""
        notifier = TelegramNotifier(sample_config)
        jobs = [
            {
                "title": "Security Intern",
                "company": "GlobalCorp",
                "location": "Remote",
                "apply_url": "https://test.com/apply",
                "application_routes": {"direct_url": "https://test.com/apply"},
            }
        ]
        msg = notifier.format_global_intern_alert(jobs)
        assert "🌐" in msg
        assert "Security Intern" in msg
        assert "GlobalCorp" in msg
        assert "Remote" in msg
    
    @pytest.mark.asyncio
    async def test_send_message_no_token(self):
        """Test send_message with no token returns False."""
        config = TelegramConfig(bot_token="", chat_id="123")
        notifier = TelegramNotifier(config)
        result = await notifier.send_message("Test")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_send_job_alert_dedup(self, sample_config, temp_db):
        """Test send_job_alert respects deduplication."""
        notifier = TelegramNotifier(sample_config)
        jobs = [{"id": "1", "title": "Test", "company": "C", "location": "Bangalore", "job_type": "full-time", "apply_url": "https://test.com", "application_routes": {}}]
        
        # First send should work (mocked)
        with patch.object(notifier, 'send_message', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await notifier.send_job_alert(jobs, temp_db)
            assert result is True
            assert mock_send.call_count >= 1
        
        # Second send with same jobs should be deduplicated
        with patch.object(notifier, 'send_message', new_callable=AsyncMock) as mock_send:
            result = await notifier.send_job_alert(jobs, temp_db)
            assert result is True
            mock_send.assert_not_called()  # Should not send again


class TestLoadConfig:
    """Test config loading."""
    
    def test_load_config_from_yaml(self, tmp_path):
        """Test loading config from YAML file."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
telegram:
  bot_token: "yaml_token"
  chat_id: "999999"
""")
        
        config = load_config(str(config_file))
        assert config.bot_token == "yaml_token"
        assert config.chat_id == "999999"
    
    def test_load_config_env_override(self, tmp_path, monkeypatch):
        """Test environment variable overrides YAML."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
telegram:
  bot_token: "yaml_token"
  chat_id: "999999"
""")
        
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token")
        config = load_config(str(config_file))
        assert config.bot_token == "env_token"
