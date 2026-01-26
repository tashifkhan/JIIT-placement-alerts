"""
Telegram Bot Server

Dedicated Telegram bot server with:
- User command handling (/start, /help, /stats, etc.)
"""

import asyncio
import logging
from typing import Optional, Any

import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from core.config import (
    Settings,
    get_settings,
    set_daemon_mode,
    safe_print,
    setup_logging,
)


class BotServer:
    """
    Telegram Bot Server with DI support.

    Handles:
    - Bot commands and user interactions
    - User registration and management
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        db_service: Optional[Any] = None,
        notification_service: Optional[Any] = None,
        admin_service: Optional[Any] = None,
        stats_service: Optional[Any] = None,
        daemon_mode: bool = False,
    ):
        """
        Initialize bot server with injected dependencies.

        Args:
            settings: Application settings
            db_service: Database service instance
            notification_service: Notification service instance
            admin_service: Admin service instance
            stats_service: PlacementStatsCalculatorService instance
            daemon_mode: Run in daemon mode (suppress stdout)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.settings = settings or get_settings()
        self.daemon_mode = daemon_mode

        # Injected services
        self.db_service = db_service
        self.notification_service = notification_service
        self.admin_service = admin_service
        self.stats_service = stats_service

        # Bot setup
        self.bot_token = self.settings.telegram_bot_token
        self.application: Optional[Application] = None

        # Timezone
        self.ist = pytz.timezone("Asia/Kolkata")

        # Running state
        self.running = True

        if daemon_mode:
            set_daemon_mode(True)

        self.logger.info("BotServer initialized")

    # =========================================================================
    # Command Handlers
    # =========================================================================

    async def start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command - register user"""
        user = update.effective_user
        chat = update.effective_chat

        if not user or not chat or not update.message:
            return

        chat_id = chat.id

        if self.db_service:
            success, msg = self.db_service.add_user(
                user_id=user.id,
                chat_id=chat_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )

            welcome_parts = []

            if success:
                if "reactivated" in msg.lower():
                    welcome_parts.append(
                        f"Welcome back {user.first_name}! 👋\n\n"
                        "Your subscription has been reactivated!\n"
                        "You'll now receive job posting updates automatically.\n\n"
                    )
                else:
                    welcome_parts.append(
                        f"Hello {user.first_name}! 👋\n\n"
                        "Welcome to SuperSet Placement Notifications Bot!\n"
                        "You'll receive job posting updates automatically.\n\n"
                    )

                welcome_parts.append(
                    "<b>Commands:</b>\n"
                    "  /start - Register for notifications\n"
                    "  /stop - Stop receiving notifications\n"
                    "  /status - Check your subscription status\n"
                    "  /stats - Get Placement Statistics\n"
                    "  /web - Get JIIT Suite Links\n\n"
                )

                welcome_parts.append(
                    "<i>btw...</i>\n"
                    "here are some links you might wanna look at -\n"
                    "1. <a href='https://jiit-placement-updates.tashif.codes'>Placement Updates PWA</a>\n"
                    "2. <a href='https://jiit-timetable.tashif.codes'>Timetable</a>\n"
                    "3. <a href='https://sophos-autologin.tashif.codes'>Wifi (Sophos) Auto Login</a>\n"
                    "4. <a href='https://jportal.tashif.codes'>JPortal</a>"
                )
                welcome_msg = "".join(welcome_parts)
            else:
                if "already exists and is active" in msg:
                    welcome_parts.append(
                        f"Hi {user.first_name}! 👋\n\n"
                        "You're already registered and active for SuperSet placement notifications.\n"
                        "You'll continue receiving job posting updates automatically.\n\n"
                    )
                    welcome_parts.append(
                        "Use /status to check your subscription details."
                    )
                    welcome_msg = "".join(welcome_parts)
                else:
                    welcome_msg = (
                        f"Welcome back, {user.first_name}! You're already subscribed."
                    )
        else:
            welcome_msg = f"Welcome, {user.first_name}! Bot is starting up..."

        await update.message.reply_text(
            welcome_msg, parse_mode="HTML", disable_web_page_preview=True
        )
        self.logger.info(f"User started: {user.id} (@{user.username})")

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command"""
        if not update.message:
            return

        help_text = """
📚 **SuperSet Bot Commands**

/start - Register for notifications
/stop - Unsubscribe from notifications
/status - Check your subscription status
/stats - View placement statistics
/noticestats - View notice statistics
/userstats - View user statistics (admin)
/web - Get JIIT Suite Links
/help - Show this help message

The bot automatically sends:
- New job postings
- Notice updates
- Placement announcements
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def stop_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stop command - unsubscribe user"""
        user = update.effective_user

        if not user or not update.message:
            return

        if self.db_service:
            success = self.db_service.deactivate_user(user.id)
            if success:
                msg = "You've been unsubscribed. Use /start to subscribe again."
            else:
                msg = "You're not currently subscribed."
        else:
            msg = "Service temporarily unavailable."

        await update.message.reply_text(msg)
        self.logger.info(f"User stopped: {user.id}")

    async def status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command - check subscription status"""
        user = update.effective_user

        if not user or not update.message:
            return

        if not self.db_service:
            await update.message.reply_text("Service temporarily unavailable.")
            return

        user_data = self.db_service.get_user_by_id(user.id)

        if user_data and user_data.get("is_active", False):
            text = "✅ You're subscribed to SuperSet placement notifications.\n"
            created_at = user_data.get("created_at")
            if created_at:
                text += f"Registered on: {created_at.strftime('%B %d, %Y')}\n"
            text += f"User ID: {user_data.get('user_id')}\n"
            text += f"Status: Active ✅"
        else:
            text = "❌ You're not subscribed to notifications.\n"
            if user_data:
                text += f"Found your account but it's marked as inactive.\n"
                text += f"User ID: {user_data.get('user_id')}\n"
            else:
                text += "No account found in our database.\n"
            text += "Use /start to subscribe."

        await update.message.reply_text(text)
        self.logger.info(f"Status checked: {user.id}")

    async def stats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stats command - show placement statistics"""
        if not update.message:
            return

        if not self.stats_service:
            await update.message.reply_text("Statistics temporarily unavailable.")
            return

        try:
            stats = self.stats_service.calculate_all_stats()
        except Exception as e:
            self.logger.error(f"Error calculating stats: {e}")
            await update.message.reply_text(f"Error calculating stats: {e}")
            return

        # Format branch stats
        branch_lines = []
        branch_stats = stats.get("branch_stats", {})
        for branch in ["CSE", "ECE", "IT", "BT", "Intg. MTech"]:
            bs = branch_stats.get(branch)
            if bs:
                pct = bs.get("placement_percentage", 0)
                unique = bs.get("unique_students", 0)
                total = bs.get("total_students_in_branch", 0)
                avg = bs.get("avg_package", 0)
                median = bs.get("median_package", 0)
                branch_lines.append(
                    f"  • {branch}: {unique}/{total} ({pct:.1f}%)\n      Avg: ₹{avg:.1f}L | Median: ₹{median:.1f}L"
                )

        branch_section = "\n".join(branch_lines) if branch_lines else "  No data"

        stats_msg = f"""📊 *Placement Statistics*

👥 Unique Students Placed: *{stats.get('unique_students_placed', 0)}*
📝 Total Offers: *{stats.get('total_offers', 0)}*
🏢 Companies: *{stats.get('unique_companies', 0)}*

💰 *Package Stats (LPA)*
  • Average: ₹{stats.get('average_package', 0):.2f}L
  • Median: ₹{stats.get('median_package', 0):.2f}L
  • Highest: ₹{stats.get('highest_package', 0):.2f}L

📈 *Branch-wise Placement*
{branch_section}

📊 Overall: *{stats.get('placement_percentage', 0):.1f}%* ({stats.get('unique_students_placed', 0)}/{stats.get('total_eligible_students', 0)})
"""

        await update.message.reply_text(stats_msg, parse_mode="Markdown")

    async def notice_stats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /noticestats command"""
        if not update.message:
            return

        if not self.db_service:
            await update.message.reply_text("Statistics temporarily unavailable.")
            return

        stats = self.db_service.get_notice_stats()

        stats_msg = f"""
📋 **Notice Statistics**

📝 Total Notices: {stats.get('total_posts', 0)}
✅ Sent: {stats.get('sent_to_telegram', 0)}
⏳ Pending: {stats.get('pending_to_send', 0)}
        """

        await update.message.reply_text(stats_msg, parse_mode="Markdown")

    async def user_stats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /userstats command (admin)"""
        if not update.message:
            return

        if not self.db_service:
            await update.message.reply_text("Statistics temporarily unavailable.")
            return

        stats = self.db_service.get_users_stats()

        stats_msg = f"""
👥 **User Statistics**

📊 Total Users: {stats.get('total_users', 0)}
✅ Active: {stats.get('active_users', 0)}
❌ Inactive: {stats.get('inactive_users', 0)}
        """

        await update.message.reply_text(stats_msg, parse_mode="Markdown")

    async def web_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /web command"""
        if not update.message:
            return

        text = (
            f"<b>Jaypee Tools:</b>\n"
            f"1. <a href='https://jiit-placement-updates.tashif.codes'>Placement Updates</a>\n"
            f"2. <a href='https://jiit-timetable.tashif.codes'>Timetable</a>\n"
            f"3. <a href='https://sophos-autologin.tashif.codes'>Wifi (Sophos) Auto Login</a>\n"
            f"4. <a href='https://jportal.tashif.codes'>JPortal</a>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    # =========================================================================
    # Bot Lifecycle
    # =========================================================================

    def setup_handlers(self, application: Application) -> None:
        """Register command handlers"""
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("stop", self.stop_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(
            CommandHandler("noticestats", self.notice_stats_command)
        )
        application.add_handler(CommandHandler("userstats", self.user_stats_command))
        application.add_handler(CommandHandler("web", self.web_command))

        # Admin commands
        if self.admin_service:
            application.add_handler(
                CommandHandler("users", self.admin_service.users_command)
            )
            application.add_handler(
                CommandHandler("boo", self.admin_service.broadcast_command)
            )
            application.add_handler(
                CommandHandler("fu", self.admin_service.scrape_command)
            )
            application.add_handler(
                CommandHandler("scrapyyy", self.admin_service.scrape_command)
            )
            application.add_handler(
                CommandHandler("logs", self.admin_service.logs_command)
            )
            application.add_handler(
                CommandHandler("s", self.admin_service.scrape_command)
            )
            application.add_handler(
                CommandHandler("kill", self.admin_service.kill_scheduler_command)
            )

        self.logger.info("Command handlers registered")

    async def run_async(self) -> None:
        """Run bot asynchronously"""
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        # Setup logging
        setup_logging(self.settings)

        # Build application
        self.application = Application.builder().token(self.bot_token).build()
        self.setup_handlers(self.application)

        safe_print("Starting Telegram bot...")
        self.logger.info("Bot starting in polling mode")

        # Start polling
        await self.application.initialize()
        await self.application.start()
        if self.application.updater:
            await self.application.updater.start_polling(drop_pending_updates=True)

        safe_print("Bot is running. Press Ctrl+C to stop.")

        # Keep running
        while self.running:
            await asyncio.sleep(1)

    def run(self) -> None:
        """Run bot (blocking)"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.logger.info("Bot stopped by user")
            safe_print("Bot stopped.")
        finally:
            self.running = False

    async def shutdown(self) -> None:
        """Graceful shutdown"""
        self.running = False

        if self.application:
            if self.application.updater:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

        self.logger.info("Bot shutdown complete")


def create_bot_server(
    settings: Optional[Settings] = None,
    daemon_mode: bool = False,
) -> BotServer:
    """
    Factory function to create bot server with full DI setup.

    Note: Scheduler-related services (scraper, formatter) have been moved
    to create_scheduler_server() in scheduler_server.py
    """
    from services.database_service import DatabaseService
    from services.notification_service import NotificationService
    from services.telegram_service import TelegramService
    from services.admin_telegram_service import AdminTelegramService
    from services.placement_stats_calculator_service import (
        PlacementStatsCalculatorService,
    )
    from clients.db_client import DBClient

    settings = settings or get_settings()

    # Initialize services
    db_client = DBClient(settings.mongo_connection_str)
    db_client.connect()
    db_service = DatabaseService(db_client)

    # Setup notification channels
    telegram_service = TelegramService(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        db_service=db_service,
    )

    notification_service = NotificationService(
        channels=[telegram_service], db_service=db_service
    )

    # Admin Service
    admin_service = AdminTelegramService(
        settings=settings, db_service=db_service, telegram_service=telegram_service
    )

    # Stats Calculator Service
    stats_service = PlacementStatsCalculatorService(db_service=db_service)

    return BotServer(
        settings=settings,
        db_service=db_service,
        notification_service=notification_service,
        admin_service=admin_service,
        stats_service=stats_service,
        daemon_mode=daemon_mode,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Telegram Bot Server")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    args = parser.parse_args()

    server = create_bot_server(daemon_mode=args.daemon)
    server.run()
