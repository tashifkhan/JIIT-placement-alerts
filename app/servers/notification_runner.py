"""
Notification Runner Service

Handles sending unsent notices via various notification channels.
Uses dependency injection for testability.
"""

import logging
from typing import Optional

from core.config import safe_print
from services.database_service import DatabaseService
from services.telegram_service import TelegramService
from services.web_push_service import WebPushService
from services.notification_service import NotificationService


logger = logging.getLogger(__name__)


class NotificationRunner:
    """
    Service for sending unsent notices via specified channels.

    Uses dependency injection for all service dependencies.
    """

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        telegram_service: Optional[TelegramService] = None,
        web_push_service: Optional[WebPushService] = None,
        notification_service: Optional[NotificationService] = None,
    ):
        """
        Initialize NotificationRunner with dependencies.

        Args:
            db_service: Database service instance (created if not provided)
            telegram_service: Telegram service instance (created if not provided when needed)
            web_push_service: Web push service instance (created if not provided when needed)
            notification_service: Notification service instance (created if not provided)
        """
        self.db = db_service or DatabaseService()
        self._telegram_service = telegram_service
        self._web_push_service = web_push_service
        self._notification_service = notification_service
        self._owns_db = db_service is None  # Track if we created the DB connection

    def send_updates(
        self,
        telegram: bool = False,
        web: bool = False,
    ) -> dict:
        """
        Send unsent notices via specified channels.

        Args:
            telegram: Send via Telegram
            web: Send via Web Push

        Returns:
            Dict with send results
        """
        safe_print("Initializing services...")

        channels = []

        if telegram:
            telegram_service = self._telegram_service or TelegramService(
                db_service=self.db
            )
            channels.append(telegram_service)
            safe_print("Telegram channel enabled")

        if web:
            web_push_service = self._web_push_service or WebPushService(
                db_service=self.db
            )
            if web_push_service.is_enabled:
                channels.append(web_push_service)
                safe_print("Web Push channel enabled")
            else:
                safe_print("Web Push not configured, skipping")

        if not channels:
            safe_print("No channels enabled. Use --telegram or --web flags.")
            return {"error": "No channels specified"}

        # Use provided notification service or create one
        notification = self._notification_service or NotificationService(
            channels=channels,
            db_service=self.db,
        )

        # Send unsent notices
        safe_print("Sending unsent notices...")
        results = notification.send_unsent_notices(
            telegram=telegram,
            web=web,
        )

        safe_print(f"Send complete: {results}")

        return results

    def close(self):
        """Close resources if we own them."""
        if self._owns_db:
            self.db.close_connection()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.close()
        return False


def send_updates(
    telegram: bool = False,
    web: bool = False,
    db_service: Optional[DatabaseService] = None,
    telegram_service: Optional[TelegramService] = None,
    web_push_service: Optional[WebPushService] = None,
) -> dict:
    """
    Convenience function to send unsent notices.

    This is a functional wrapper around NotificationRunner for backward compatibility.

    Args:
        telegram: Send via Telegram
        web: Send via Web Push
        db_service: Optional database service (created if not provided)
        telegram_service: Optional Telegram service (created if not provided)
        web_push_service: Optional Web push service (created if not provided)

    Returns:
        Dict with send results
    """
    with NotificationRunner(
        db_service=db_service,
        telegram_service=telegram_service,
        web_push_service=web_push_service,
    ) as runner:
        return runner.send_updates(telegram=telegram, web=web)
