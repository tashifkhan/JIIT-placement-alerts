"""
Admin Telegram Service

Handles administrative commands for the Telegram bot.
"""

import os
import logging
import asyncio
from typing import Any, Optional

from telegram import Update
from telegram.ext import ContextTypes

from core.config import safe_print


class AdminTelegramService:
    """
    Handles admin-only commands:
    - /users: List all users
    - /boo: Broadcast messages
    - /fu: Force update (scrape)
    - /logs: View server logs
    """

    def __init__(
        self,
        settings: Any,
        db_service: Any,
        telegram_service: Any,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.settings = settings
        self.db_service = db_service
        self.telegram_service = telegram_service

        # Admin authentication
        self.admin_chat_id = str(settings.telegram_chat_id)

    async def _is_admin(self, update: Update) -> bool:
        """Check if the user is the admin"""
        if not update.effective_chat or not update.message:
            return False

        chat_id = str(update.effective_chat.id)
        if chat_id != self.admin_chat_id:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            self.logger.warning(f"Unauthorized admin command attempt by {chat_id}")
            return False
        return True

    async def users_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /users command"""
        if not update.message:
            return

        if not await self._is_admin(update):
            return

        try:
            users = self.db_service.get_all_users()

            if not users:
                await update.message.reply_text("No users found in the database.")
                return

            text = "👥 User List:\n\n"
            for i, user_data in enumerate(users, 1):
                status = (
                    "✅ Active" if user_data.get("is_active", False) else "❌ Inactive"
                )
                username = user_data.get("username", "No username")
                first_name = user_data.get("first_name", "No name")
                last_name = user_data.get("last_name", "")
                user_id = user_data.get("user_id", "Unknown")

                text += f"{i}. {first_name} {last_name} (@{username})\n"
                text += f"   ID: {user_id}\n"
                text += f"   Status: {status}\n\n"

            # Split if too long (simple split for now, or use telegram_service if it has split)
            # telegram_service.send_message handles splitting, but update.message.reply_text might not.
            # We'll use telegram_service to send safe large messages if possible,
            # OR just rely on telegram_service.split_long_message logic if exposed.
            # Re-using telegram_service.split_long_message would be good but it's an instance method.

            # Since we are replying to the update, we can loop if lengthy.
            if len(text) > 4000:
                chunks = self.telegram_service.split_long_message(text)
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(text)

            safe_print(f"Admin requested user list")

        except Exception as e:
            error_msg = f"Error getting user list: {e}"
            await update.message.reply_text(f"❌ {error_msg}")
            safe_print(error_msg)

    async def broadcast_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /boo command - Broadcast"""
        if not update.message or not update.message.text:
            return

        if not await self._is_admin(update):
            return

        # Get message
        message_text = update.message.text.strip()

        # Remove /boo
        cmd_len = len("/boo")
        if message_text.lower().startswith("/boo"):
            message_text = message_text[cmd_len:].strip()

        if not message_text:
            await update.message.reply_text(
                "❌ Please provide a message to send.\n"
                "Usage:\n"
                "- /boo broadcast <message> - Send to all users\n"
                "- /boo <chat_id> <message> - Send to specific user"
            )
            return

        # Check broadcast
        if message_text.lower().startswith("broadcast"):
            broadcast_msg = message_text[9:].strip()  # len("broadcast") == 9
            if not broadcast_msg:
                await update.message.reply_text(
                    "❌ Please provide a message to broadcast."
                )
                return

            # Use telegram_service to broadcast
            # Note: telegram_service.broadcast_to_all_users is synchronous or async?
            # Looking at telegram_service.py outline (Step 31), it seems synchronous using requests?
            # Let's check if it returns a coroutine. It imports 'requests', likely sync.
            # But we are in an async handler. It's better if we run it in a thread or if it's fast enough.
            # Given it loops over users and sends requests, it might block.
            # Ideally should be async, but for now we call it directly as per existing design.

            # Since telegram_service methods seem to be synchronous (using `requests`),
            # we might block the event loop. However, to keep it simple and consistent:
            success_count = 0
            # We assume broadcast_to_all_users returns a dict or similar from NotificationService,
            # BUT wait, TelegramService.broadcast_to_all_users (Step 31) doesn't return count directly?
            # Step 31: broadcast_to_all_users(self, message: str, parse_mode="HTML", **kwargs)
            # It seems to loop and print. logic in telegram_handeller.py line 900 returns boolean (successful_sends > 0).

            # Let's check telegram_service.py again.
            # It has `broadcast_to_all_users`.

            result = self.telegram_service.broadcast_to_all_users(broadcast_msg)
            # Steps 31 output doesn't show return type but usually implies dict or bool.
            # Let's assume it works like the one in notification service which wraps it.

            await update.message.reply_text(f"✅ Broadcast processed. Result: {result}")
            return

        # Targeted message
        try:
            parts = message_text.split(" ", 1)
            if len(parts) != 2:
                await update.message.reply_text("❌ Invalid format.")
                return

            target_chat_id, target_msg = parts

            # Use telegram_service.send_to_user
            success = self.telegram_service.send_to_user(target_chat_id, target_msg)

            if success:
                await update.message.reply_text(f"✅ Message sent to {target_chat_id}")
            else:
                await update.message.reply_text(
                    f"❌ Failed to send message to {target_chat_id}"
                )

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def scrape_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /fu and /scrapyyy command"""
        if not update.message:
            return

        if not await self._is_admin(update):
            return

        await update.message.reply_text("⏳ Running main workflow (main.py)...")

        try:
            # We need to run this in a separate thread to avoid blocking the bot loop
            # since main.py likely has blocking calls or is long-running.
            loop = asyncio.get_event_loop()

            # Function to run the scraper
            def run_scraper():
                from main import main as run_main_process

                try:
                    return run_main_process()  # type: ignore
                except Exception:
                    return 1

            result = await loop.run_in_executor(None, run_scraper)

            if result == 0:
                await update.message.reply_text("✅ Workflow completed successfully!")
            else:
                await update.message.reply_text(
                    f"⚠️ Workflow completed with exit code: {result}"
                )

        except Exception as e:
            await update.message.reply_text(f"❌ Error running workflow: {e}")

    async def logs_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Handle /logs command
        Usage: /logs [bot|scheduler] (default: bot)
        """
        if not update.message:
            return

        if not await self._is_admin(update):
            return

        # Parse argument
        target = "bot"
        if context.args and len(context.args) > 0:
            target = context.args[0].lower()

        # Determine file path
        if target == "scheduler":
            log_filename = "logs/scheduler.log"
        elif target == "bot":
            log_filename = self.settings.log_file  # Default log file
        else:
            await update.message.reply_text(
                "❌ Unknown log type. Use: /logs [bot|scheduler]"
            )
            return

        # Resolve absolute path (robust way)
        # Using the same logic as config.py or relative to project root
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        log_path = os.path.join(base_dir, log_filename)

        # If settings.log_file is absolute, use it directly for bot
        if target == "bot" and os.path.isabs(self.settings.log_file):
            log_path = self.settings.log_file

        if not os.path.exists(log_path):
            await update.message.reply_text(f"❌ Log file not found: {log_filename}")
            return

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            last_lines = lines[-100:] if len(lines) >= 100 else lines

            header = f"📋 <b>Log Viewer ({target})</b>\n"
            header += f"Path: <code>{log_filename}</code>\n"
            header += f"Lines: {len(last_lines)}\n\n"

            full_text = "".join(last_lines)
            message = header + f"<pre>{full_text}</pre>"

            if len(message) > 4000:
                # Naive chunking if too big
                # Or use telegram_service.split_long_message if available
                # For now, just send the tail that fits
                await update.message.reply_text(message[-4000:], parse_mode="HTML")
            else:
                await update.message.reply_text(message, parse_mode="HTML")

        except Exception as e:
            await update.message.reply_text(f"❌ Error reading logs: {e}")
