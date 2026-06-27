"""Email notification service — send alarm alerts via SMTP."""

import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class EmailNotifier:
    """Send alarm notifications via SMTP email."""

    def __init__(self):
        self._enabled = False
        self._smtp_host = ""
        self._smtp_port = 587
        self._smtp_user = ""
        self._smtp_pass = ""
        self._from_addr = ""
        self._to_addrs: list[str] = []

    async def load_config(self) -> None:
        """Load email config from database system_config."""
        try:
            from app.db import async_session
            from app.models.system_config import SystemConfig
            from sqlalchemy import select

            async with async_session() as session:
                keys = ["EMAIL_ENABLED", "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT",
                        "EMAIL_SMTP_USER", "EMAIL_SMTP_PASS", "EMAIL_FROM", "EMAIL_TO"]
                result = await session.execute(
                    select(SystemConfig).where(SystemConfig.config_key.in_(keys))
                )
                configs = {r.config_key: r.config_value for r in result.scalars().all()}

            self._enabled = configs.get("EMAIL_ENABLED", "false").lower() == "true"
            self._smtp_host = configs.get("EMAIL_SMTP_HOST", "")
            self._smtp_port = int(configs.get("EMAIL_SMTP_PORT", "587"))
            self._smtp_user = configs.get("EMAIL_SMTP_USER", "")
            self._smtp_pass = configs.get("EMAIL_SMTP_PASS", "")
            self._from_addr = configs.get("EMAIL_FROM", self._smtp_user)
            to_str = configs.get("EMAIL_TO", "")
            self._to_addrs = [a.strip() for a in to_str.split(",") if a.strip()]

            if self._enabled and self._smtp_host and self._to_addrs:
                logger.info("email_notifier_configured", host=self._smtp_host, recipients=len(self._to_addrs))
            else:
                logger.debug("email_notifier_disabled")
        except Exception as e:
            logger.error("email_config_load_error", error=str(e))

    async def send_alarm_email(
        self,
        alarm_type: str,
        stream_id: str,
        confidence: float,
        class_name: str,
        alarm_id: int,
    ) -> bool:
        """Send an alarm notification email.

        Returns True if sent successfully, False otherwise.
        """
        if not self._enabled or not self._smtp_host or not self._to_addrs:
            return False

        type_names = {"helmet": "安全帽", "fire": "火灾", "intrusion": "入侵检测", "no-helmet": "未戴安全帽"}
        type_cn = type_names.get(alarm_type, alarm_type)

        subject = f"[Argus 告警] {type_cn} - {stream_id}"
        body = (
            f"Argus 监控告警通知\n\n"
            f"告警类型: {type_cn}\n"
            f"监控流: {stream_id}\n"
            f"检测类别: {class_name}\n"
            f"置信度: {confidence:.1%}\n"
            f"告警ID: {alarm_id}\n\n"
            f"请及时处理。"
        )

        try:
            msg = MIMEMultipart()
            msg["From"] = self._from_addr
            msg["To"] = ", ".join(self._to_addrs)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Run SMTP in thread to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_sync, msg)

            logger.info("alarm_email_sent", alarm_type=alarm_type, stream_id=stream_id, recipients=len(self._to_addrs))
            return True
        except Exception as e:
            logger.error("alarm_email_failed", error=str(e), alarm_type=alarm_type)
            return False

    def _send_sync(self, msg: MIMEMultipart) -> None:
        """Send email synchronously via SMTP."""
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
            server.starttls()
            if self._smtp_user and self._smtp_pass:
                server.login(self._smtp_user, self._smtp_pass)
            server.send_message(msg)


# Singleton
email_notifier = EmailNotifier()
