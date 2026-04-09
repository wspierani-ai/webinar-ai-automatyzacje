"""Tests for bot configuration — Unit 1."""

import os
import pytest
from unittest.mock import patch


class TestConfigValidation:
    """Config validation rzuca ValueError gdy brakuje env vara."""

    def test_raises_value_error_when_telegram_bot_token_missing(self):
        env = {
            "TELEGRAM_SECRET_TOKEN": "secret",
            "GCP_PROJECT_ID": "project",
            "CLOUD_RUN_SERVICE_URL": "https://example.run.app",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
                Config.from_env()

    def test_raises_value_error_when_multiple_required_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            from bot.config import Config
            with pytest.raises(ValueError):
                Config.from_env()

    def test_raises_value_error_when_gcp_project_id_missing(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_SECRET_TOKEN": "secret",
            "CLOUD_RUN_SERVICE_URL": "https://example.run.app",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
                Config.from_env()

    def test_raises_value_error_when_cloud_run_service_url_missing(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_SECRET_TOKEN": "secret",
            "GCP_PROJECT_ID": "project",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            with pytest.raises(ValueError, match="CLOUD_RUN_SERVICE_URL"):
                Config.from_env()


class TestConfigLoadsFromEnv:
    """Config poprawnie ładuje zmienne z environment."""

    def test_loads_all_required_fields(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_SECRET_TOKEN": "test-secret",
            "GCP_PROJECT_ID": "test-project",
            "CLOUD_RUN_SERVICE_URL": "https://test.run.app",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            config = Config.from_env()
            assert config.telegram_bot_token == "test-token"
            assert config.telegram_secret_token == "test-secret"
            assert config.gcp_project_id == "test-project"
            assert config.cloud_run_service_url == "https://test.run.app"

    def test_defaults_for_optional_fields(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_SECRET_TOKEN": "secret",
            "GCP_PROJECT_ID": "project",
            "CLOUD_RUN_SERVICE_URL": "https://example.run.app",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            config = Config.from_env()
            assert config.gcp_region == "europe-central2"
            assert config.cloud_tasks_reminders_queue == "reminders"
            assert config.cloud_tasks_nudges_queue == "nudges"

    def test_parses_admin_email_whitelist(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_SECRET_TOKEN": "secret",
            "GCP_PROJECT_ID": "project",
            "CLOUD_RUN_SERVICE_URL": "https://example.run.app",
            "ADMIN_EMAIL_WHITELIST": "admin@example.com,admin2@example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            config = Config.from_env()
            assert config.admin_email_whitelist == [
                "admin@example.com",
                "admin2@example.com",
            ]

    def test_empty_whitelist_when_not_set(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_SECRET_TOKEN": "secret",
            "GCP_PROJECT_ID": "project",
            "CLOUD_RUN_SERVICE_URL": "https://example.run.app",
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config import Config
            config = Config.from_env()
            assert config.admin_email_whitelist == []
