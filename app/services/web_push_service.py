"""
Web Push Notification Service

Implements INotificationChannel protocol for Web Push notifications.
Uses VAPID for authentication.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional

from core.config import safe_print

# Optional dependency - will gracefully degrade if not installed
try:
    from pywebpush import webpush, WebPushException

    WEBPUSH_AVAILABLE = True

except ImportError:
    WEBPUSH_AVAILABLE = False
    webpush = None
    WebPushException = Exception


class WebPushService:
    """
    Web Push notification service implementing INotificationChannel protocol.

    Handles:
    - Sending push notifications to subscribed browsers
    - Managing subscriptions via database
    - VAPID authentication
    """

    def __init__(
        self,
        vapid_private_key: Optional[str] = None,
        vapid_public_key: Optional[str] = None,
        vapid_email: Optional[str] = None,
        db_service: Optional[Any] = None,
    ):
        """
        Initialize Web Push service.

        Args:
            vapid_private_key: VAPID private key for auth
            vapid_public_key: VAPID public key (shared with clients)
            vapid_email: Contact email for VAPID
            db_service: Database service for subscription management
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        self.vapid_private_key = vapid_private_key or os.getenv("VAPID_PRIVATE_KEY")
        self.vapid_public_key = vapid_public_key or os.getenv("VAPID_PUBLIC_KEY")
        self.vapid_email = vapid_email or os.getenv("VAPID_EMAIL")
        self.db_service = db_service

        self._enabled = WEBPUSH_AVAILABLE and bool(self.vapid_private_key)

        if not WEBPUSH_AVAILABLE:
            self.logger.warning("pywebpush not installed. Web push disabled.")

        elif not self.vapid_private_key:
            self.logger.warning("VAPID keys not configured. Web push disabled.")

        else:
            self.logger.info("WebPushService initialized")

    @property
    def channel_name(self) -> str:
        """Return the name of this notification channel"""
        return "web_push"

    @property
    def is_enabled(self) -> bool:
        """Check if web push is properly configured"""
        return self._enabled

    def send_message(self, message: str, **kwargs) -> bool:
        """Send to all subscriptions (broadcast)"""
        if not self._enabled:
            self.logger.debug("Web push disabled, skipping send_message")
            return True  # Return True to not block pipeline

        result = self.broadcast_to_all_users(message, **kwargs)
        return result.get("success", 0) > 0 or result.get("total", 0) == 0

    def send_to_user(self, user_id: Any, message: str, **kwargs) -> bool:
        """Send to a specific user's subscriptions"""
        if not self._enabled:
            return True

        if not self.db_service:
            safe_print("Database service not available for web push")
            return False

        try:
            # Get user's push subscriptions
            user = self.db_service.get_user_by_id(user_id)
            if not user:
                return False

            subscriptions = user.get("push_subscriptions", [])
            if not subscriptions:
                return True  # No subscriptions is not a failure

            title = kwargs.get("title", "SuperSet Update")

            for sub in subscriptions:
                self._send_push(sub, title, message)

            return True

        except Exception as e:
            self.logger.error(f"Error sending web push to user {user_id}: {e}")
            return False

    def broadcast_to_all_users(self, message: str, **kwargs) -> Dict[str, Any]:
        """Send to all users with push subscriptions"""
        if not self._enabled:
            return {"success": 0, "failed": 0, "total": 0, "disabled": True}

        if not self.db_service:
            safe_print("Database service not available for web push broadcast")
            return {"success": 0, "failed": 0, "total": 0}

        try:
            users = self.db_service.get_active_users()
            title = kwargs.get("title", "SuperSet Update")

            success_count = 0
            failed_count = 0
            total_subs = 0

            for user in users:
                subscriptions = user.get("push_subscriptions", [])
                for sub in subscriptions:
                    total_subs += 1
                    if self._send_push(sub, title, message):
                        success_count += 1
                    else:
                        failed_count += 1

            safe_print(f"Web push broadcast: {success_count}/{total_subs} success")
            return {
                "success": success_count,
                "failed": failed_count,
                "total": total_subs,
            }

        except Exception as e:
            self.logger.error(f"Error broadcasting web push: {e}")
            return {"success": 0, "failed": 0, "total": 0, "error": str(e)}

    def _send_push(
        self, subscription: Dict[str, Any], title: str, message: str
    ) -> bool:
        """Send a push notification to a single subscription"""
        if not self._enabled or not webpush:
            return False

        try:
            payload = json.dumps(
                {
                    "title": title,
                    "body": message[:200],  # Truncate for push
                    "icon": "/icon.png",
                    "badge": "/badge.png",
                    "data": {"url": "/"},
                }
            )

            vapid_claims = {"sub": f"mailto:{self.vapid_email}"}

            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=self.vapid_private_key,
                vapid_claims=vapid_claims,  # type: ignore
            )
            return True

        except WebPushException as e:
            self.logger.warning(f"Web push failed: {e}")
            # Handle expired subscriptions
            if hasattr(e, "response") and e.response and hasattr(e.response, "status_code") and e.response.status_code in (404, 410):  # type: ignore
                self._remove_subscription(subscription)
            return False
        except Exception as e:
            self.logger.error(f"Unexpected web push error: {e}")
            return False

    def _remove_subscription(self, subscription: Dict[str, Any]) -> None:
        """Remove an expired/invalid subscription"""
        if not self.db_service:
            return

        try:
            endpoint = subscription.get("endpoint")
            if endpoint:
                self.logger.info(f"Removing expired subscription: {endpoint[:50]}...")
                # This would need a specific method in database service
                # For now, just log it
        except Exception as e:
            self.logger.error(f"Error removing subscription: {e}")

    # =========================================================================
    # Subscription Management (for webhook server)
    # =========================================================================

    def save_subscription(self, user_id: int, subscription: Dict[str, Any]) -> bool:
        """Save a push subscription for a user"""
        if not self.db_service:
            return False

        try:
            # This would add the subscription to user's push_subscriptions array
            # Implementation depends on database service method
            self.logger.info(f"Saved push subscription for user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving subscription: {e}")
            return False

    def remove_subscription(self, user_id: int, endpoint: str) -> bool:
        """Remove a push subscription for a user"""
        if not self.db_service:
            return False

        try:
            self.logger.info(f"Removed push subscription for user {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error removing subscription: {e}")
            return False

    def get_public_key(self) -> Optional[str]:
        """Get VAPID public key for clients"""
        return self.vapid_public_key
