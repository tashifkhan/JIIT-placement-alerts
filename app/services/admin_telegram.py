"""
Admin Telegram Service

Handles administrative commands for the Telegram bot.
"""

import asyncio
import json
import logging
import os
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from core.config import safe_print
from core.daemon import stop_daemon, is_running, get_daemon_status


class AdminTelegramService:
    """
    Handles admin-only commands:
    - /users: List all users
    - /boo: Broadcast messages
    - /fu or /s: Force update (scrape)
    - /logs: View server logs
    - /kill: Kill scheduler
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

        self.admin_user_ids = self._parse_admin_user_ids(
            getattr(settings, "admin_telegram_user_ids", "")
        )

    def _parse_admin_user_ids(self, raw_value: Any) -> set[int]:
        """Parse the dedicated admin ID setting and fail closed on bad input."""
        try:
            values = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if not isinstance(values, list):
                raise ValueError("ADMIN_TELEGRAM_USER_IDS must be a JSON list")
            return {int(value) for value in values if str(value).strip()}
        except (TypeError, ValueError, json.JSONDecodeError):
            self.logger.error("Invalid ADMIN_TELEGRAM_USER_IDS configuration")
            return set()

    async def _is_admin(self, update: Update) -> bool:
        """Check if the user is the admin"""
        if not update.effective_user or not update.message:
            return False

        user_id = update.effective_user.id
        if user_id not in self.admin_user_ids:
            await update.message.reply_text(
                "❌ This command is only available to administrators."
            )
            self.logger.warning("Unauthorized admin command attempt by user %s", user_id)
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

        except Exception:
            self.logger.error("Error getting user list", exc_info=True)
            await update.message.reply_text("❌ Unable to get the user list.")

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

            result = await asyncio.to_thread(
                self.telegram_service.broadcast_to_all_users, broadcast_msg
            )

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

        except Exception:
            self.logger.error("Targeted Telegram send failed", exc_info=True)
            await update.message.reply_text("❌ Unable to send the message.")

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
            def run_legacy_update():
                from main import cmd_legacy
                import argparse

                return cmd_legacy(
                    argparse.Namespace(
                        dry_run=False,
                        telegram=True,
                        web=False,
                        both=False,
                        fetch=True,
                        verbose=False,
                        year=None,
                    )
                )

            result = await asyncio.to_thread(run_legacy_update)

            await update.message.reply_text(
                f"✅ Update workflow completed!\n"
                f"Fetch: {result.get('fetch')}\n"
                f"Send: {result.get('send')}"
            )

        except Exception:
            self.logger.error("Admin update workflow failed", exc_info=True)
            await update.message.reply_text("❌ Update workflow failed. Check server logs.")

    async def kill_scheduler_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /kill command - Stop scheduler daemon"""
        if not update.message:
            return

        if not await self._is_admin(update):
            return

        name = "scheduler"
        if not is_running(name):
            await update.message.reply_text("❌ Scheduler is not running.")
            return

        status = get_daemon_status(name)
        pid = status.get("pid")

        await update.message.reply_text(f"🛑 Stopping scheduler (PID: {pid})...")

        if stop_daemon(name):
            await update.message.reply_text("✅ Scheduler stopped successfully.")
            self.logger.info(f"Scheduler stopped by admin {update.effective_user.id}")

        else:
            await update.message.reply_text("❌ Failed to stop scheduler.")
            self.logger.error("Failed to stop scheduler via admin command")

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

        # Proper import for escaping
        import html

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Get last 100 lines first
            last_lines = lines[-100:] if len(lines) >= 100 else lines
            full_text = "".join(last_lines)

            # Escape the log content to avoid HTML parsing errors
            safe_text = html.escape(full_text)

            # Simple truncation if too long (reserving space for header/tags)
            # standard max is 4096, keep it safe at 4000
            if len(safe_text) > 3800:
                safe_text = safe_text[-3800:]
                safe_text = f"...[truncated]\n{safe_text}"

            header = f"📋 <b>Log Viewer ({target})</b>\n"
            header += f"Path: <code>{log_filename}</code>\n"
            header += f"Lines: {len(last_lines)}\n\n"

            message = header + f"<pre>{safe_text}</pre>"

            await update.message.reply_text(message, parse_mode="HTML")

        except Exception:
            self.logger.error("Unable to read requested log file", exc_info=True)
            await update.message.reply_text("❌ Unable to read the requested logs.")
