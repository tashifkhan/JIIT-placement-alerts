"""
Notification Service

Unified notification orchestrator that routes messages to multiple channels.
"""

import logging
from typing import Any

from core.config import safe_print
from services.notice_message_builder import NoticeMessageBuilder


class NotificationService:
    """
    Unified notification service that aggregates multiple channels.

    Routes notifications to enabled channels (Telegram, Web Push, etc.)
    based on configuration and flags.
    """

    def __init__(
        self,
        channels: list[Any] | None = None,
        db_service: Any | None = None,
        placement_year: str | None = None,
    ):
        """
        Initialize notification service.

        Args:
            channels: List of notification channel implementations
            db_service: Database service for fetching unsent notices
            placement_year: Placement year used to scope user broadcasts
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.channels = channels or []
        self.db_service = db_service
        self.placement_year = placement_year
        self.message_builder = NoticeMessageBuilder()

        channel_names = [c.channel_name for c in self.channels]
        self.logger.info(
            f"NotificationService initialized with channels: {channel_names}"
        )

    def add_channel(self, channel: Any) -> None:
        """Add a notification channel"""
        self.channels.append(channel)
        self.logger.info(f"Added channel: {channel.channel_name}")

    def send_to_channel(
        self,
        message: str,
        channel_name: str,
        **kwargs,
    ) -> bool:
        """Send message to a specific channel"""
        for channel in self.channels:
            if channel.channel_name == channel_name:
                return channel.send_message(message, **kwargs)

        self.logger.warning(f"Channel not found: {channel_name}")
        return False

    def broadcast(
        self,
        message: str,
        channels: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Broadcast message to specified channels (or all if not specified).

        Args:
            message: Message to send
            channels: List of channel names, or None for all
            **kwargs: Additional args passed to channels

        Returns:
            Dict with results per channel
        """
        results = {}

        for channel in self.channels:
            if channels is None or channel.channel_name in channels:
                try:
                    result = channel.broadcast_to_all_users(message, **kwargs)
                    results[channel.channel_name] = result
                except Exception:
                    self.logger.exception(
                        "Error broadcasting to %s", channel.channel_name
                    )
                    results[channel.channel_name] = {"error": "Channel delivery failed"}

        return results

    def send_unsent_notices(
        self,
        telegram: bool = True,
        web: bool = False,
    ) -> dict[str, Any]:
        """
        Send all unsent notices to specified channels.

        Args:
            telegram: Send to Telegram
            web: Send to Web Push

        Returns:
            Stats about sent notices
        """
        if not self.db_service:
            safe_print("Database service not available")
            return {"error": "Database service not available"}

        # Determine which channels to use
        target_channels = []
        if telegram:
            target_channels.append("telegram")
        if web:
            target_channels.append("web_push")

        self.logger.info(f"Target channels for unsent notices: {target_channels}")

        if not target_channels:
            return {"error": "No channels specified"}

        if hasattr(self.db_service, "get_pending_notices"):
            unsent_posts = self.db_service.get_pending_notices(target_channels)
        else:
            unsent_posts = self.db_service.get_unsent_notices()

        if not unsent_posts:
            safe_print("No unsent notices found")
            return {
                "total": 0,
                "sent": 0,
                "failed": 0,
                "channels": target_channels,
            }

        safe_print(f"Found {len(unsent_posts)} unsent notices")

        sent_count = 0
        failed_count = 0
        details = []
        channels_by_name = {channel.channel_name: channel for channel in self.channels}

        for post in unsent_posts:
            message = self.message_builder.build(post)
            post_results: dict[str, Any] = {}
            all_success = True

            for channel_name in target_channels:
                if self._was_delivered(post, channel_name):
                    post_results[channel_name] = {"skipped": "already_delivered"}
                    continue

                channel = channels_by_name.get(channel_name)
                if channel is None:
                    post_results[channel_name] = {"error": "Channel not available"}
                    all_success = False
                    continue

                try:
                    channel_result = channel.broadcast_to_all_users(
                        message,
                        placement_year=self.placement_year,
                    )
                except Exception:
                    self.logger.exception(
                        "Error broadcasting to %s", channel_name
                    )
                    channel_result = {"error": "Channel delivery failed"}

                post_results[channel_name] = channel_result
                if not self._delivery_succeeded(channel_result):
                    all_success = False
                    continue

                if hasattr(self.db_service, "mark_channel_delivered"):
                    marked = self.db_service.mark_channel_delivered(
                        post["_id"], channel_name
                    )
                elif channel_name == "telegram":
                    marked = self.db_service.mark_as_sent(post["_id"])
                else:
                    marked = False

                if not marked:
                    all_success = False
                    post_results[channel_name] = {
                        "delivery": channel_result,
                        "error": "Delivery succeeded but state was not persisted",
                    }

            if all_success:
                sent_count += 1
                safe_print(
                    f"Sent and marked: {post.get('title', 'Unknown')[:50]}..."
                )
            else:
                failed_count += 1

            details.append(
                {
                    "post_id": str(post.get("_id", "")),
                    "title": post.get("title", "")[:50],
                    "channels": post_results,
                }
            )

        result = {
            "total": len(unsent_posts),
            "sent": sent_count,
            "failed": failed_count,
            "channels": target_channels,
            "details": details,
        }

        safe_print(f"Notification summary: {result}")
        return result

    @staticmethod
    def _was_delivered(post: dict[str, Any], channel_name: str) -> bool:
        """Read channel state while honoring the persisted Telegram legacy flag."""
        delivery_status = post.get("delivery_status") or {}
        if delivery_status.get(channel_name) is True:
            return True
        return channel_name == "telegram" and post.get("sent_to_telegram") is True

    @staticmethod
    def _delivery_succeeded(result: Any) -> bool:
        """Require explicit no-op state or successful non-empty recipient delivery."""
        if result is True:
            return True
        if not isinstance(result, dict) or result.get("error"):
            return False
        if result.get("disabled") is True or result.get("noop") is True:
            return True
        if str(result.get("status", "")).casefold() in {
            "disabled",
            "noop",
            "no-op",
        }:
            return True

        total = result.get("total", 0)
        success = result.get("success", 0)
        failed = result.get("failed", 0)
        return total > 0 and failed == 0 and success >= total

    def send_new_posts_to_all_users(
        self,
        telegram: bool = True,
        web: bool = False,
    ) -> dict[str, Any]:
        """
        Send new posts to all registered users via specified channels.

        This is the main entry point for scheduled jobs.
        """
        return self.send_unsent_notices(telegram=telegram, web=web)
