"""Email utilities for sending reset password emails."""
from __future__ import annotations

import os
import aiosmtplib
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() == "true"
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
FROM_NAME = os.getenv("FROM_NAME", "STT Engine")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")


async def send_reset_email(to_email: str, username: str, reset_token: str) -> bool:
    """
    Send password reset email.
    Returns True if sent successfully, False otherwise.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print("SMTP not configured, skipping email send")
        return False

    reset_url = f"{APP_BASE_URL}/reset.html?token={reset_token}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #4f46e5; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 8px 8px; }}
            .button {{ display: inline-block; background: #4f46e5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .footer {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 20px; }}
            .token {{ background: #e5e7eb; padding: 10px; border-radius: 4px; font-family: monospace; word-break: break-all; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Reset Password - STT Engine</h1>
            </div>
            <div class="content">
                <p>Halo <strong>{username}</strong>,</p>
                <p>Kami menerima permintaan untuk mereset password akun Anda. Klik tombol di bawah untuk melanjutkan:</p>
                <p style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset Password</a>
                </p>
                <p>Atau salin token ini ke halaman reset:</p>
                <div class="token">{reset_token}</div>
                <p><small>Token ini berlaku selama 30 menit. Jika Anda tidak meminta reset password, abaikan email ini.</small></p>
            </div>
            <div class="footer">
                <p>STT Engine - Voice-to-Text Engine</p>
                <p>Email ini dikirim otomatis, mohon tidak dibalas.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_content = f"""
Reset Password - STT Engine

Halo {username},

Kami menerima permintaan untuk mereset password akun Anda.

Link reset: {reset_url}

Atau gunakan token ini: {reset_token}

Token ini berlaku selama 30 menit. Jika Anda tidak meminta reset password, abaikan email ini.

---
STT Engine - Voice-to-Text Engine
Email ini dikirim otomatis, mohon tidak dibalas.
"""

    message = EmailMessage()
    message["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    message["To"] = to_email
    message["Subject"] = "Reset Password - STT Engine"
    message.set_content(text_content)
    message.add_alternative(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=SMTP_TLS,
        )
        return True
    except Exception as e:
        print(f"Failed to send reset email: {e}")
        return False