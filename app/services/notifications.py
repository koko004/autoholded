"""Notification service for sending alerts."""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Handles sending notifications via email and webhooks."""
    
    async def send_notification(
        self,
        subject: str,
        message: str,
        notification_type: str = "info"
    ):
        """Send notification through all enabled channels."""
        try:
            if settings.SMTP_ENABLED:
                await self._send_email(subject, message)
            
            if settings.WEBHOOK_ENABLED:
                await self._send_webhook(subject, message, notification_type)
                
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    async def _send_email(self, subject: str, message: str):
        """Send email notification."""
        try:
            if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
                logger.warning("SMTP credentials not configured")
                return
            
            msg = MIMEMultipart()
            msg['From'] = settings.SMTP_FROM or settings.SMTP_USER
            msg['Subject'] = f"[Fichador Holded] {subject}"
            
            # Add HTML formatting
            html = f"""
            <html>
            <body>
                <h2>Fichador Automático Holded</h2>
                <p>{message}</p>
                <hr>
                <p style="color: #666; font-size: 12px;">
                    Este es un mensaje automático del sistema de fichaje.
                </p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            # Send to all recipients
            recipients = self._get_email_recipients()
            if not recipients:
                logger.warning("No email recipients configured")
                return
            
            msg['To'] = ', '.join(recipients)
            
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"Email sent: {subject}")
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
    
    async def _send_webhook(self, subject: str, message: str, notification_type: str):
        """Send webhook notification."""
        try:
            if not settings.WEBHOOK_URL:
                logger.warning("Webhook URL not configured")
                return
            
            payload = {
                "text": f"*{subject}*\n{message}",
                "type": notification_type,
                "timestamp": __import__('datetime').datetime.now().isoformat()
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.WEBHOOK_URL,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
            
            logger.info(f"Webhook sent: {subject}")
            
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
    
    def _get_email_recipients(self) -> List[str]:
        """Get list of email recipients from config."""
        # TODO: Get from database
        # For now, use environment variable
        if settings.SMTP_USER:
            return [settings.SMTP_USER]
        return []
    
    async def notify_fichaje_success(self, fichaje_type: str, time_str: str):
        """Send success notification for fichaje."""
        subject = f"Fichaje {fichaje_type} registrado"
        message = f"Se ha registrado correctamente tu fichaje de {fichaje_type} a las {time_str}."
        await self.send_notification(subject, message, "success")
    
    async def notify_fichaje_error(self, fichaje_type: str, error: str):
        """Send error notification for fichaje."""
        subject = f"Error en fichaje {fichaje_type}"
        message = f"Ha ocurrido un error al registrar tu fichaje de {fichaje_type}: {error}"
        await self.send_notification(subject, message, "error")


# Singleton instance
notifications = NotificationService()
