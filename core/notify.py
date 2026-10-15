"""Optional owner e-mail notifications (no Streamlit). Off until SMTP is configured in secrets:

    [email]
    smtp_host = "smtp.example.com"
    smtp_port = 587            # 465 = SSL, otherwise STARTTLS
    username  = "..."
    password  = "..."
    sender    = "World Explorer <noreply@example.com>"
    owner_to  = ["owner@example.com"]

A failed or missing e-mail never affects the withdrawal request, which is already recorded in the database and shown
in the Owner dashboard. Returns 'not_configured', 'sent' or 'failed'; never raises.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

TIMEOUT = 10


def configured(cfg: dict | None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("smtp_host") and cfg.get("sender") and cfg.get("owner_to"))


def withdrawal_message(details: dict, test: bool) -> tuple[str, str]:
    """Subject and body: the player's name, reference, amount and request date (no bank details, no legal name)."""
    prefix = "[TEST RECORD — NOT PAYABLE] " if test else ""
    subject = f"{prefix}New World Explorer withdrawal request {details.get('reference', '')}"
    body = (f"{prefix}A player has requested a withdrawal.\n\n"
            f"Player: {details.get('player', '')}\n"
            f"Reference: {details.get('reference', '')}\n"
            f"Amount: ₦{int(details.get('amount') or 0):,}\n"
            f"Request date: {str(details.get('requested_at', ''))[:10]}\n"
            f"Status: Pending Review\n\n"
            "Review it in World Explorer → Owner dashboard → 💰 Rewards & Referral Management → 💳 Withdrawals.\n"
            "Approving never moves money: transfer the money from your bank, then use “Mark as paid”.\n")
    return subject, body


def send(cfg: dict | None, subject: str, body: str, smtp_factory=None) -> str:
    cfg = cfg or {}
    if not configured(cfg):
        return "not_configured"
    to = cfg.get("owner_to")
    recipients = [to] if isinstance(to, str) else [str(x) for x in to]
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, str(cfg["sender"]), ", ".join(recipients)
    message.set_content(body)
    port = int(cfg.get("smtp_port") or 587)
    try:
        if smtp_factory:
            server = smtp_factory(str(cfg["smtp_host"]), port)
        elif port == 465:
            server = smtplib.SMTP_SSL(str(cfg["smtp_host"]), port, timeout=TIMEOUT,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(str(cfg["smtp_host"]), port, timeout=TIMEOUT)
        with server:
            if not smtp_factory and port != 465:
                server.starttls(context=ssl.create_default_context())
            if cfg.get("username"):
                server.login(str(cfg["username"]), str(cfg.get("password") or ""))
            server.send_message(message)
        return "sent"
    except Exception:
        return "failed"
