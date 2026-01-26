"""
Telegram Notification Service

Implements INotificationChannel protocol for Telegram notifications.
Handles message sending, formatting, and user broadcasting.
"""

import os
import re
import time
import logging
from typing import Dict, List, Any, Optional
from typing import Dict, List, Any, Optional
import time

from core.config import safe_print
from clients.telegram_client import TelegramClient


class TelegramService:
    """
    Telegram notification service implementing INotificationChannel protocol.

    Handles:
    - Sending messages to default channel
    - Sending messages to specific users
    - Broadcasting to all users
    - Message formatting (Markdown/HTML)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        db_service: Optional[Any] = None,
    ):
        """
        Initialize Telegram service.

        Args:
            bot_token: Telegram bot token. If None, reads from env.
            chat_id: Default chat ID for notifications. If None, reads from env.
            db_service: Database service for user lookup.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        # Initialize client
        self.client = TelegramClient(bot_token, chat_id)

        self.logger.info("TelegramService initialized with TelegramClient")
        self.logger.info("TelegramService initialized")

    @property
    def channel_name(self) -> str:
        """Return the name of this notification channel"""
        return "telegram"

    def test_connection(self) -> bool:
        """Test if Telegram bot is configured correctly"""
        return self.client.test_connection()

    def send_message(
        self,
        message: str,
        parse_mode: str = "HTML",
        **kwargs,
    ) -> bool:
        """Send a message to the default channel/chat"""
        try:
            if not self.client.bot_token or not self.client.default_chat_id:
                safe_print("Error: Telegram bot token or chat ID not configured")
                return False

            # Split long messages
            if len(message) > 4000:
                safe_print(f"Message too long ({len(message)} chars), splitting...")
                chunks = self.split_long_message(message, max_length=4000)
                chunks_sent = 0

                for i, chunk in enumerate(chunks, 1):
                    safe_print(
                        f"Sending chunk {i}/{len(chunks)} ({len(chunk)} chars)..."
                    )
                    if self._send_single_message(chunk, parse_mode):
                        chunks_sent += 1
                        if i < len(chunks):
                            time.sleep(1)
                    else:
                        safe_print(f"Failed to send chunk {i}/{len(chunks)}")
                        break

                return chunks_sent == len(chunks)

            else:
                return self._send_single_message(message, parse_mode)

        except Exception as e:
            safe_print(f"Error sending Telegram message: {e}")
            return False

    def _send_single_message(
        self,
        message: str,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a single message chunk"""
        if parse_mode == "MarkdownV2":
            formatted_message = self.convert_markdown_to_telegram(message)
        elif parse_mode == "HTML":
            formatted_message = self.convert_markdown_to_html(message)
        else:
            formatted_message = message

        sent = self.client.send_message(text=formatted_message, parse_mode=parse_mode)

        if not sent and parse_mode:
            # Retry without formatting
            safe_print("Retrying with plain text...")
            return self.client.send_message(text=message, parse_mode="")

        return sent

    def send_to_user(
        self,
        user_id: Any,
        message: str,
        parse_mode: str = "HTML",
        **kwargs,
    ) -> bool:
        """Send a message to a specific user"""
        if parse_mode == "HTML":
            formatted_message = self.convert_markdown_to_html(message)
        else:
            formatted_message = message

        return self.client.send_message(
            text=formatted_message, chat_id=user_id, parse_mode=parse_mode
        )

    def broadcast_to_all_users(
        self,
        message: str,
        parse_mode: str = "HTML",
        **kwargs,
    ) -> Dict[str, Any]:
        """Send a message to all active users"""
        if not self.db_service:
            safe_print("Database service not available for broadcasting")
            return {"success": 0, "failed": 0, "total": 0}

        users = self.db_service.get_active_users()
        success_count = 0
        failed_count = 0

        for user in users:
            chat_id = user.get("chat_id") or user.get("user_id")

            if chat_id:
                if self.send_to_user(chat_id, message, parse_mode):
                    success_count += 1
                else:
                    failed_count += 1
                time.sleep(0.05)  # Rate limiting

        safe_print(
            f"Broadcast complete: {success_count} success, {failed_count} failed"
        )
        return {
            "success": success_count,
            "failed": failed_count,
            "total": len(users),
        }

    def send_message_html(self, message: str) -> bool:
        """Send message using HTML formatting"""
        try:
            if not self.client.bot_token or not self.client.default_chat_id:
                safe_print("Error: Telegram bot token or chat ID not configured")
                return False

            if len(message) > 4000:
                chunks = self.split_long_message(message, max_length=4000)
                chunks_sent = 0

                for i, chunk in enumerate(chunks, 1):
                    if self._send_single_html_message(chunk):
                        chunks_sent += 1
                        if i < len(chunks):
                            time.sleep(1)
                    else:
                        break

                return chunks_sent == len(chunks)

            else:
                return self._send_single_html_message(message)

        except Exception as e:
            safe_print(f"Error sending HTML message: {e}")
            return False

    def _send_single_html_message(self, message: str) -> bool:
        """Send a single HTML message"""
        formatted = self.convert_markdown_to_html(message)

        sent = self.client.send_message(text=formatted, parse_mode="HTML")

        if not sent:
            # retry fallback
            return self.client.send_message(text=message, parse_mode="")

        return sent

    """
            Message Formatting
    """

    def split_long_message(self, message: str, max_length: int = 4000) -> List[str]:
        """Split a long message into smaller chunks"""
        if len(message) <= max_length:
            return [message]

        chunks = []
        lines = message.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + "\n"
                else:
                    words = line.split(" ")
                    current_line = ""
                    for word in words:
                        if len(current_line) + len(word) + 1 > max_length:
                            if current_line:
                                chunks.append(current_line.strip())
                                current_line = word + " "
                            else:
                                chunks.append(word[:max_length])
                                current_line = ""
                        else:
                            current_line += word + " "
                    if current_line:
                        current_chunk = current_line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2"""
        escape_chars = [
            "_",
            "*",
            "[",
            "]",
            "(",
            ")",
            "~",
            "`",
            ">",
            "#",
            "+",
            "-",
            "=",
            "|",
            "{",
            "}",
            ".",
            "!",
        ]
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")
        return text

    def convert_markdown_to_telegram(self, text: str) -> str:
        """Convert standard markdown to Telegram-compatible MarkdownV2"""
        text = text.replace("**", "*")
        text = re.sub(r"^##\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)
        text = re.sub(r"^###\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)
        text = re.sub(r"^>\s+(.*?)$", r"_\1_", text, flags=re.MULTILINE)

        lines = text.split("\n")
        processed_lines = []

        for line in lines:
            if line.strip():
                if "*" in line or "_" in line or "`" in line:
                    processed_lines.append(line)
                else:
                    processed_lines.append(self.escape_markdown_v2(line))
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines)

    @staticmethod
    def convert_markdown_to_html(text: str) -> str:
        """Convert markdown to HTML for Telegram"""
        if not text:
            return ""

        # Add extra line after Deadline
        text = re.sub(r"(?m)^(.*Deadline:.*)$", r"\1\n", text)

        # Convert markdown links [text](url) to HTML <a> tags FIRST
        # This must happen before other conversions to avoid conflicts
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

        # Convert email addresses in angle brackets <email@example.com> to links
        text = re.sub(
            r"<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>",
            r'<a href="mailto:\1">\1</a>',
            text,
        )

        # Headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)
        text = re.sub(r"^###\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # Bold **...** (allow newlines inside with DOTALL)
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)

        # Italic _..._  (simple approach - URLs typically don't use single underscores for emphasis)
        text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", text)

        # Blockquotes
        text = re.sub(r"^>\s+(.*?)$", r"<i>\1</i>", text, flags=re.MULTILINE)

        # Inline code
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        # Single *...* to italic (but not inside URLs)
        text = re.sub(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)", r"<i>\1</i>", text)

        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    @staticmethod
    def escape_html(text: str) -> str:
        """Escape HTML special characters"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
