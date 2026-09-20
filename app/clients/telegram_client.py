"""
Telegram Client

Handles raw interactions with the Telegram Bot API.
Responsible for:
- Sending messages (text, HTML, Markdown)
- Managing Request exceptions
"""

import logging
import os
import time
from typing import Any, Optional

import requests

from core.config import safe_print


class TelegramClient:
    """
    Low-level client for Telegram Bot API.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram Client.

        Args:
            bot_token: API Token. If None, loaded from env.
            chat_id: Default chat ID. If None, loaded from env.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.default_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.session = requests.Session()

        if not self.bot_token:
            self.logger.warning("TELEGRAM_BOT_TOKEN not provided or set in env.")

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> bool:
        """
        Send a message to a chat ID.

        Args:
            text: Message text to send.
            chat_id: Target chat ID. Defaults to self.default_chat_id.
            parse_mode: 'HTML', 'MarkdownV2', or '' (None).
            disable_web_page_preview: Whether to disable link previews.
            retries: Number of retries on failure.
            backoff_factor: Delay multiplier between retries.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        target_id = chat_id or self.default_chat_id

        if not self.bot_token:
            safe_print("Error: Telegram bot token not configured")
            return False

        if not target_id:
            safe_print("Error: Target chat ID not provided")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {
            "chat_id": target_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }

        if parse_mode:
            payload["parse_mode"] = parse_mode

        for attempt in range(retries):
            try:
                response = self.session.post(url, json=payload, timeout=10)

                if response.status_code == 200:
                    return True

                # Handle rate limiting (429)
                if response.status_code == 429:
                    retry_after = self._get_retry_after(response)
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s.")
                    time.sleep(retry_after)
                    continue

                self.logger.warning(
                    "Telegram send attempt %s/%s failed with HTTP %s",
                    attempt + 1,
                    retries,
                    response.status_code,
                )

            except requests.RequestException as e:
                self.logger.warning(
                    "Telegram send attempt %s/%s failed (%s)",
                    attempt + 1,
                    retries,
                    type(e).__name__,
                )

            # exponential backoff if retrying
            if attempt < retries - 1:
                time.sleep(backoff_factor * (2**attempt))

        return False

    @staticmethod
    def _get_retry_after(response: requests.Response) -> int:
        """Read Telegram's retry delay without assuming one response format."""
        retry_after: Any = None
        try:
            body = response.json()
            if isinstance(body, dict):
                parameters = body.get("parameters")
                if isinstance(parameters, dict):
                    retry_after = parameters.get("retry_after")
        except (ValueError, requests.JSONDecodeError):
            pass

        if retry_after is None:
            retry_after = response.headers.get("Retry-After", 1)

        try:
            return max(1, int(retry_after))
        except (TypeError, ValueError):
            return 1

    def test_connection(self) -> bool:
        """Test authentication by calling getMe."""
        if not self.bot_token:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = self.session.get(url, timeout=10)
            return response.status_code == 200

        except Exception as e:
            self.logger.error(
                "Telegram connection test failed (%s)", type(e).__name__
            )
            return False
