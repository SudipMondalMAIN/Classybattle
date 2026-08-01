"""
Reusable transactional email service backed by Brevo (Sendinblue) API.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.core.exceptions import ExternalServiceException
from app.core.logging import get_logger
from app.emails.templates import otp_email_template, password_reset_otp_template

logger = get_logger(__name__)

BREVO_SEND_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"


class EmailService:
    """Reusable service for sending transactional emails via Brevo."""

    def __init__(self) -> None:
        self.api_key = settings.BREVO_API_KEY
        self.sender_email = settings.BREVO_SENDER_EMAIL
        self.sender_name = settings.BREVO_SENDER_NAME

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _send(self, to_email: str, subject: str, html_content: str) -> None:
        if not self.api_key:
            logger.warning("brevo_api_key_missing", to=to_email, subject=subject)
            return

        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        }
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(BREVO_SEND_EMAIL_URL, json=payload, headers=headers)

        if response.status_code >= 400:
            logger.error(
                "brevo_send_failed",
                to=to_email,
                status_code=response.status_code,
                body=response.text,
            )
            raise ExternalServiceException("Failed to send email. Please try again shortly.")

        logger.info("email_sent", to=to_email, subject=subject)

    async def send_signup_otp(self, to_email: str, full_name: str, otp: str, expiry_minutes: int) -> None:
        html = otp_email_template(full_name=full_name, otp=otp, expiry_minutes=expiry_minutes)
        await self._send(to_email, "Verify your ClassyBattle account", html)

    async def send_password_reset_otp(self, to_email: str, full_name: str, otp: str, expiry_minutes: int) -> None:
        html = password_reset_otp_template(full_name=full_name, otp=otp, expiry_minutes=expiry_minutes)
        await self._send(to_email, "Reset your ClassyBattle password", html)

    async def send_notification_email(self, to_email: str, subject: str, body: str) -> None:
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; background-color: #0d0d0d; padding: 24px;">
            <div style="max-width: 480px; margin: 0 auto; background: #1a1a1a; border-radius: 12px; padding: 32px; color: #f5f5f5;">
              <h2 style="color: #ffcc00; margin-top: 0;">{subject}</h2>
              <p>{body}</p>
              <p style="margin-top: 32px; font-size: 12px; color: #888;">— The ClassyBattle Team</p>
            </div>
          </body>
        </html>
        """
        await self._send(to_email, subject, html)


email_service = EmailService()
