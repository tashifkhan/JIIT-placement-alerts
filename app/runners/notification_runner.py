"""
Notification Runner Service

Handles sending unsent notices via various notification channels.
Uses dependency injection for testability.
"""

import logging
from typing import Any

from core.config import get_settings, safe_print
from core.year_context import database_name_for_year, get_configured_placement_years
from services.database import DatabaseService
from services.notification import NotificationService
from services.telegram import TelegramService
from services.web_push import WebPushService

logger = logging.getLogger(__name__)


class _PlacementYearUserService:
    """Delegate global user operations with a fixed broadcast year filter."""

    def __init__(self, global_db_service: DatabaseService, placement_year: str):
        self._global_db_service = global_db_service
        self._placement_year = placement_year

    def get_active_users(self, placement_year: str | None = None):
        """Return users subscribed to this scoped placement year."""
        return self._global_db_service.get_active_users(
            placement_year or self._placement_year
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._global_db_service, name)


class NotificationRunner:
    """
    Service for sending unsent notices via specified channels.

    Uses dependency injection for all service dependencies.
    """

    def __init__(
        self,
        db_service: DatabaseService | None = None,
        telegram_service: TelegramService | None = None,
        web_push_service: WebPushService | None = None,
        notification_service: NotificationService | None = None,
        placement_year: str | None = None,
    ):
        """
        Initialize NotificationRunner with dependencies.

        Args:
            db_service: Database service instance (created if not provided)
            telegram_service: Telegram service instance (created if not provided when needed)
            web_push_service: Web push service instance (created if not provided when needed)
            notification_service: Notification service instance (created if not provided)
        """
        if db_service:
            self.db = db_service
            self._owns_db = False
        else:
            from clients.db_client import DBClient

            # Local db client for this runner instance
            self.db_client = DBClient()
            self.db_client.connect()
            self.db = DatabaseService(self.db_client)
            self._owns_db = True

        self._telegram_service = telegram_service
        self._web_push_service = web_push_service
        self._notification_service = notification_service
        self.placement_year = placement_year

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
            channels.append(web_push_service)
            if web_push_service.is_enabled:
                safe_print("Web Push channel enabled")
            else:
                safe_print("Web Push not configured; recording disabled no-op")

        if not channels:
            safe_print("No channels enabled. Use --telegram or --web flags.")
            return {"error": "No channels specified"}

        # Use provided notification service or create one
        notification = self._notification_service or NotificationService(
            channels=channels,
            db_service=self.db,
            placement_year=self.placement_year,
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
    db_service: DatabaseService | None = None,
    telegram_service: TelegramService | None = None,
    web_push_service: WebPushService | None = None,
    notification_service: NotificationService | None = None,
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
        notification_service: Optional notification orchestrator for a scoped run

    Returns:
        Dict with send results
    """
    if db_service or telegram_service or web_push_service or notification_service:
        with NotificationRunner(
            db_service=db_service,
            telegram_service=telegram_service,
            web_push_service=web_push_service,
            notification_service=notification_service,
        ) as runner:
            return runner.send_updates(telegram=telegram, web=web)

    from clients.db_client import DBClient

    settings = get_settings()
    placement_years = get_configured_placement_years(settings)
    global_client = DBClient(use_global_database=True)
    global_client.connect()
    global_db = DatabaseService(global_client)
    results: dict = {
        "years": {},
        "total": 0,
        "sent": 0,
        "failed": 0,
    }

    try:
        for placement_year in placement_years:
            year_client = DBClient(
                database_name=database_name_for_year(placement_year)
            )
            year_client.connect()
            year_db = DatabaseService(year_client)
            if hasattr(global_db, "import_legacy_users"):
                global_db.import_legacy_users(
                    year_db.get_all_users(),
                    placement_year,
                )
            user_db = _PlacementYearUserService(global_db, placement_year)

            try:
                scoped_telegram = (
                    TelegramService(db_service=user_db) if telegram else None
                )
                scoped_web_push = (
                    WebPushService(db_service=user_db) if web else None
                )
                runner = NotificationRunner(
                    db_service=year_db,
                    telegram_service=scoped_telegram,
                    web_push_service=scoped_web_push,
                    placement_year=placement_year,
                )
                year_result = runner.send_updates(telegram=telegram, web=web)
                results["years"][placement_year] = year_result
                for key in ("total", "sent", "failed"):
                    results[key] += int(year_result.get(key, 0))
            finally:
                year_db.close_connection()
    finally:
        global_db.close_connection()

    return results
