"""Tests for email notification service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.email_notifier import EmailNotifier


class TestEmailNotifier:
    """Test EmailNotifier class."""

    def test_init_defaults(self):
        """Test notifier initializes with disabled state."""
        notifier = EmailNotifier()
        assert notifier._enabled is False
        assert notifier._smtp_host == ""
        assert notifier._to_addrs == []

    @pytest.mark.asyncio
    async def test_load_config_disabled(self):
        """Test config loading when email is disabled."""
        notifier = EmailNotifier()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.db.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await notifier.load_config()

            assert notifier._enabled is False

    @pytest.mark.asyncio
    async def test_load_config_enabled(self):
        """Test config loading when email is enabled."""
        notifier = EmailNotifier()

        mock_configs = [
            MagicMock(config_key="EMAIL_ENABLED", config_value="true"),
            MagicMock(config_key="EMAIL_SMTP_HOST", config_value="smtp.example.com"),
            MagicMock(config_key="EMAIL_SMTP_PORT", config_value="465"),
            MagicMock(config_key="EMAIL_SMTP_USER", config_value="user@example.com"),
            MagicMock(config_key="EMAIL_SMTP_PASS", config_value="pass123"),
            MagicMock(config_key="EMAIL_FROM", config_value="alerts@example.com"),
            MagicMock(config_key="EMAIL_TO", config_value="admin@example.com,ops@example.com"),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_configs
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.db.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await notifier.load_config()

            assert notifier._enabled is True
            assert notifier._smtp_host == "smtp.example.com"
            assert notifier._smtp_port == 465
            assert len(notifier._to_addrs) == 2

    @pytest.mark.asyncio
    async def test_send_when_disabled(self):
        """Test send returns False when disabled."""
        notifier = EmailNotifier()
        result = await notifier.send_alarm_email("fire", "cam-1", 0.9, "fire", 1)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_when_no_recipients(self):
        """Test send returns False when no recipients configured."""
        notifier = EmailNotifier()
        notifier._enabled = True
        notifier._smtp_host = "smtp.example.com"
        notifier._to_addrs = []
        result = await notifier.send_alarm_email("fire", "cam-1", 0.9, "fire", 1)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Test successful email send."""
        notifier = EmailNotifier()
        notifier._enabled = True
        notifier._smtp_host = "smtp.example.com"
        notifier._smtp_port = 587
        notifier._smtp_user = "user@example.com"
        notifier._smtp_pass = "pass"
        notifier._from_addr = "alerts@example.com"
        notifier._to_addrs = ["admin@example.com"]

        with patch.object(notifier, "_send_sync") as mock_send:
            result = await notifier.send_alarm_email("fire", "cam-1", 0.9, "fire", 42)
            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_smtp_error(self):
        """Test email send handles SMTP errors gracefully."""
        notifier = EmailNotifier()
        notifier._enabled = True
        notifier._smtp_host = "smtp.example.com"
        notifier._smtp_port = 587
        notifier._to_addrs = ["admin@example.com"]

        with patch.object(notifier, "_send_sync", side_effect=Exception("SMTP down")):
            result = await notifier.send_alarm_email("fire", "cam-1", 0.9, "fire", 42)
            assert result is False
