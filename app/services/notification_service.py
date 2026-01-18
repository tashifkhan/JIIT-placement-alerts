"""
Notification Service

Unified notification orchestrator that routes messages to multiple channels.
"""

import logging
from typing import Dict, List, Any, Optional

from core.config import safe_print


class NotificationService:
    """
    Unified notification service that aggregates multiple channels.

    Routes notifications to enabled channels (Telegram, Web Push, etc.)
    based on configuration and flags.
    """

    def __init__(
        self,
        channels: Optional[List[Any]] = None,
        db_service: Optional[Any] = None,
    ):
        """
        Initialize notification service.

        Args:
            channels: List of notification channel implementations
            db_service: Database service for fetching unsent notices
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.channels = channels or []
        self.db_service = db_service

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
        channels: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
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
                except Exception as e:
                    self.logger.error(
                        f"Error broadcasting to {channel.channel_name}: {e}"
                    )
                    results[channel.channel_name] = {"error": str(e)}

        return results

    def send_unsent_notices(
        self,
        telegram: bool = True,
        web: bool = False,
    ) -> Dict[str, Any]:
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

        # Get unsent notices
        unsent_posts = self.db_service.get_unsent_notices()

        if not unsent_posts:
            safe_print("No unsent notices found")
            return {"total": 0, "sent": 0, "failed": 0}

        safe_print(f"Found {len(unsent_posts)} unsent notices")

        # Determine which channels to use
        target_channels = []
        if telegram:
            target_channels.append("telegram")
        if web:
            target_channels.append("web_push")

        self.logger.info(f"Target channels for unsent notices: {target_channels}")

        sent_count = 0
        failed_count = 0

        for post in unsent_posts:
            message = post.get("formatted_message")
            if not message:
                # Fallback to content
                title = post.get("title", "Update")
                content = post.get("content", "")
                message = f"**{title}**\n\n{content}"

            # Send to all target channels
            all_success = True
            for channel_name in target_channels:
                if not self.send_to_channel(message, channel_name):
                    all_success = False

            if all_success:
                # Mark as sent
                if self.db_service.mark_as_sent(post["_id"]):
                    sent_count += 1
                    safe_print(
                        f"Sent and marked: {post.get('title', 'Unknown')[:50]}..."
                    )
                else:
                    failed_count += 1
            else:
                failed_count += 1

        result = {
            "total": len(unsent_posts),
            "sent": sent_count,
            "failed": failed_count,
            "channels": target_channels,
        }

        safe_print(f"Notification summary: {result}")
        return result

    def send_new_posts_to_all_users(
        self,
        telegram: bool = True,
        web: bool = False,
    ) -> Dict[str, Any]:
        """
        Send new posts to all registered users via specified channels.

        This is the main entry point for scheduled jobs.
        """
        if not self.db_service:
            return {"error": "Database service not available"}

        unsent_posts = self.db_service.get_unsent_notices()

        if not unsent_posts:
            safe_print("No new posts to send")
            return {"success": True, "sent": 0}

        results = {"total": len(unsent_posts), "sent": 0, "failed": 0, "details": []}

        target_channels = []
        if telegram:
            target_channels.append("telegram")
        if web:
            target_channels.append("web_push")

        for post in unsent_posts:
            message = post.get("formatted_message")
            if not message:
                title = post.get("title", "Update")
                content = post.get("content", "")
                message = f"**{title}**\n\n{content}"

            post_results = {}
            for channel in self.channels:
                if channel.channel_name in target_channels:
                    try:
                        channel_result = channel.broadcast_to_all_users(message)
                        post_results[channel.channel_name] = channel_result
                    except Exception as e:
                        self.logger.error(
                            f"Error sending via {channel.channel_name}: {e}"
                        )
                        post_results[channel.channel_name] = {"error": str(e)}

            # Mark as sent if at least one channel succeeded
            any_success = any(
                r.get("success", 0) > 0 or r.get("total", 0) == 0
                for r in post_results.values()
                if isinstance(r, dict) and "error" not in r
            )

            if any_success:
                self.db_service.mark_as_sent(post["_id"])
                results["sent"] += 1
            else:
                results["failed"] += 1

            results["details"].append(
                {
                    "post_id": str(post["_id"]),
                    "title": post.get("title", "")[:50],
                    "channels": post_results,
                }
            )

        return results
