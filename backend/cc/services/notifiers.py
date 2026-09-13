"""Outbound notification channels (Telegram, webhook, email). Configured only via environment."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import requests

from ..config import EnvConfig


class NotificationError(Exception):
    pass


def send_telegram(env: EnvConfig, text: str) -> str:
    if not env.telegram_configured:
        raise NotificationError("Telegram not configured (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{env.telegram_bot_token}/sendMessage",
            json={"chat_id": env.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
    except requests.RequestException as exc:
        # never include the request URL: it contains the bot token
        raise NotificationError(f"Telegram request failed: {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise NotificationError(f"Telegram HTTP {resp.status_code}")
    return "sent"


def send_webhook(env: EnvConfig, payload: dict) -> str:
    if not env.alert_webhook_url:
        raise NotificationError("webhook not configured (ALERT_WEBHOOK_URL)")
    try:
        resp = requests.post(env.alert_webhook_url, json=payload, timeout=15)
    except requests.RequestException as exc:
        raise NotificationError(f"webhook request failed: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise NotificationError(f"webhook HTTP {resp.status_code}")
    return "sent"


def send_email(env: EnvConfig, subject: str, body: str) -> str:
    if not env.email_configured:
        raise NotificationError("email not configured (SMTP_HOST, ALERT_EMAIL_TO)")
    message = EmailMessage()
    message["Subject"] = subject[:200]
    message["From"] = env.alert_email_from or env.smtp_user
    message["To"] = env.alert_email_to
    message.set_content(body)
    try:
        with smtplib.SMTP(env.smtp_host, env.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if env.smtp_user:
                smtp.login(env.smtp_user, env.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotificationError(f"email failed: {type(exc).__name__}") from None
    return "sent"
