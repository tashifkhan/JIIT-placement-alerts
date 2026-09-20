"""
Web Push Notification Service

Implements INotificationChannel protocol for Web Push notifications.
Uses VAPID for authentication.
"""

import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

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

        self._enabled = WEBPUSH_AVAILABLE and all(
            (self.vapid_private_key, self.vapid_public_key, self.vapid_email)
        )

        if not WEBPUSH_AVAILABLE:
            self.logger.warning("pywebpush not installed. Web push disabled.")

        elif not self._enabled:
            self.logger.warning("VAPID configuration incomplete. Web push disabled.")

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

            successful = True
            for sub in subscriptions:
                if not self._send_push(sub, title, message, user_id=user_id):
                    successful = False
            return successful

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
            users = self.db_service.get_active_users(kwargs.get("placement_year"))
            title = kwargs.get("title", "SuperSet Update")

            success_count = 0
            failed_count = 0
            total_subs = 0

            for user in users:
                subscriptions = user.get("push_subscriptions", [])
                for sub in subscriptions:
                    total_subs += 1
                    if self._send_push(
                        sub, title, message, user_id=user.get("user_id")
                    ):
                        success_count += 1
                    else:
                        failed_count += 1

            safe_print(f"Web push broadcast: {success_count}/{total_subs} success")
            result = {
                "success": success_count,
                "failed": failed_count,
                "total": total_subs,
            }
            if total_subs == 0:
                result["noop"] = True
            return result

        except Exception:
            self.logger.error("Error broadcasting web push", exc_info=True)
            return {
                "success": 0,
                "failed": 0,
                "total": 0,
                "error": "Web push delivery failed",
            }

    def _send_push(
        self,
        subscription: Dict[str, Any],
        title: str,
        message: str,
        user_id: Optional[int] = None,
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
            response = getattr(e, "response", None)
            if response is not None and getattr(response, "status_code", None) in (404, 410):
                self._remove_subscription(subscription, user_id=user_id)
            return False
        except Exception as e:
            self.logger.error(f"Unexpected web push error: {e}")
            return False

    def _remove_subscription(
        self, subscription: Dict[str, Any], user_id: Optional[int] = None
    ) -> None:
        """Remove an expired/invalid subscription"""
        if not self.db_service:
            return

        try:
            endpoint = subscription.get("endpoint")
            if endpoint:
                self.logger.info(f"Removing expired subscription: {endpoint[:50]}...")
                if user_id is not None:
                    self.remove_subscription(user_id, endpoint)
                    return

                collection = getattr(self.db_service, "users_collection", None)
                if collection is not None:
                    collection.update_many(
                        {"push_subscriptions.endpoint": endpoint},
                        {"$pull": {"push_subscriptions": {"endpoint": endpoint}}},
                    )
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
            normalized = self._validate_subscription(subscription)
            repository_method = getattr(
                self.db_service, "save_push_subscription", None
            )
            if callable(repository_method):
                return bool(repository_method(user_id, normalized))

            collection = getattr(self.db_service, "users_collection", None)
            if collection is None:
                return False

            endpoint = normalized["endpoint"]
            result = collection.update_one(
                {"user_id": user_id},
                [
                    {
                        "$set": {
                            "push_subscriptions": {
                                "$concatArrays": [
                                    {
                                        "$filter": {
                                            "input": {
                                                "$ifNull": [
                                                    "$push_subscriptions",
                                                    [],
                                                ]
                                            },
                                            "as": "subscription",
                                            "cond": {
                                                "$ne": [
                                                    "$$subscription.endpoint",
                                                    endpoint,
                                                ]
                                            },
                                        }
                                    },
                                    [normalized],
                                ]
                            }
                        }
                    }
                ],
            )
            saved = result.matched_count > 0
            if saved:
                self.logger.info("Saved push subscription for user %s", user_id)
            return saved
        except Exception as e:
            self.logger.error(f"Error saving subscription: {e}")
            return False

    def remove_subscription(self, user_id: int, endpoint: str) -> bool:
        """Remove a push subscription for a user"""
        if not self.db_service:
            return False

        try:
            if not self._is_valid_endpoint(endpoint):
                return False

            repository_method = getattr(
                self.db_service, "remove_push_subscription", None
            )
            if callable(repository_method):
                return bool(repository_method(user_id, endpoint))

            collection = getattr(self.db_service, "users_collection", None)
            if collection is None:
                return False

            result = collection.update_one(
                {"user_id": user_id},
                {"$pull": {"push_subscriptions": {"endpoint": endpoint}}},
            )
            removed = result.matched_count > 0
            if removed:
                self.logger.info("Removed push subscription for user %s", user_id)
            return removed
        except Exception as e:
            self.logger.error(f"Error removing subscription: {e}")
            return False

    def get_public_key(self) -> Optional[str]:
        """Get VAPID public key for clients"""
        return self.vapid_public_key

    @staticmethod
    def _is_valid_endpoint(endpoint: Any) -> bool:
        """Accept only bounded HTTPS push-service endpoints."""
        if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 4096:
            return False
        parsed = urlsplit(endpoint)
        return parsed.scheme.lower() == "https" and bool(parsed.netloc)

    @classmethod
    def _validate_subscription(cls, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize browser subscription data."""
        if not isinstance(subscription, dict):
            raise ValueError("Invalid push subscription")

        endpoint = subscription.get("endpoint")
        keys = subscription.get("keys")
        if not cls._is_valid_endpoint(endpoint) or not isinstance(keys, dict):
            raise ValueError("Invalid push subscription")

        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        if not all(isinstance(value, str) and value.strip() for value in (p256dh, auth)):
            raise ValueError("Invalid push subscription keys")

        return {
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
        }
