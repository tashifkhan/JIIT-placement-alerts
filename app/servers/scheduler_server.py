"""
Scheduler Server

Dedicated scheduler server for running automated update jobs.
Decoupled from the Telegram bot server.

The scheduler runs the same update logic as `cmd_legacy` in main.py:
1. Fetch updates from SuperSet + Emails
2. Send notifications via Telegram

Usage:
    python main.py scheduler              # Run scheduler only
    python main.py scheduler --daemon     # Run in daemon mode
"""

import argparse
import asyncio
import logging
from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import (
    Settings,
    get_settings,
    set_daemon_mode,
    safe_print,
    setup_logging,
)


class SchedulerServer:
    """
    Scheduler Server for running automated update jobs.

    Handles:
    - Scheduled update jobs (fetching from SuperSet + Emails, sending notifications)
    - Independent operation from the Telegram bot

    Uses the same update logic as cmd_legacy in main.py.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        daemon_mode: bool = False,
    ):
        """
        Initialize scheduler server.

        Args:
            settings: Application settings
            daemon_mode: Run in daemon mode (suppress stdout)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.settings = settings or get_settings()
        self.daemon_mode = daemon_mode

        # Scheduler setup
        self.scheduler: Optional[AsyncIOScheduler] = None

        # Timezone
        self.ist = pytz.timezone("Asia/Kolkata")

        # Running state
        self.running = True
        self._update_lock = asyncio.Lock()

        if daemon_mode:
            set_daemon_mode(True)

        self.logger.info("SchedulerServer initialized")

    # =========================================================================
    # Scheduled Jobs
    # =========================================================================

    async def run_scheduled_update(self) -> None:
        """
        Run scheduled update job.

        This mirrors the cmd_legacy behavior in main.py:
        1. Fetch updates from SuperSet + Emails
        2. Send notifications via Telegram
        """
        if self._update_lock.locked():
            self.logger.warning("Skipping update because another update is running")
            return

        async with self._update_lock:
            self.logger.info("Running scheduled update...")
            safe_print("Starting scheduled update job...")

            try:
                from main import cmd_update_emails
                from runners.notification_runner import send_updates
                from runners.update_runner import fetch_and_process_updates

                safe_print("━━━ Fetching SuperSet Updates ━━━")
                ss_result = await asyncio.to_thread(fetch_and_process_updates)
                safe_print(f"SuperSet update: {ss_result}")

                safe_print("━━━ Fetching Email Updates ━━━")
                email_args = argparse.Namespace(year=None)
                email_result = await asyncio.to_thread(cmd_update_emails, email_args)
                safe_print(f"Email update: {email_result}")

                safe_print("━━━ Sending Telegram Notifications ━━━")
                send_result = await asyncio.to_thread(
                    send_updates, telegram=True, web=False
                )
                safe_print(f"Send result: {send_result}")
                safe_print("━━━ Scheduled Update Complete ━━━")
            except Exception as e:
                self.logger.error("Scheduled update failed: %s", e, exc_info=True)
                safe_print(f"Scheduled update error: {e}")

    async def run_official_placement_scrape(self) -> None:
        """
        Scrape official placement data from JIIT website.

        This mirrors cmd_official() in main.py.
        Runs daily at 12:00 PM IST.
        """
        self.logger.info("Running official placement scrape...")
        safe_print("━━━ Scraping Official Placement Data ━━━")

        try:
            data = await asyncio.to_thread(self._scrape_official_placement)

            if data is None:
                raise RuntimeError("Official placement scrape or persistence failed")

            safe_print(
                f"Official placement scrape complete: {len(data.batches)} batches"
            )
            self.logger.info(
                "Official placement scrape complete: %s batches", len(data.batches)
            )

        except Exception as e:
            self.logger.error(f"Official placement scrape failed: {e}", exc_info=True)
            safe_print(f"Official placement scrape error: {e}")

    @staticmethod
    def _scrape_official_placement():
        """Run the blocking official scrape and database work in one thread."""
        from clients.db_client import DBClient
        from services.database import DatabaseService
        from services.official_placement import OfficialPlacementService

        db_client = DBClient(use_global_database=True)
        try:
            db_client.connect()
            service = OfficialPlacementService(db_service=DatabaseService(db_client))
            return service.scrape_and_save()
        finally:
            db_client.close_connection()

    def setup_scheduler(self) -> None:
        """Setup scheduled jobs"""
        self.scheduler = AsyncIOScheduler(timezone=self.ist)

        self.scheduler.add_job(
            self.run_scheduled_update,
            trigger="cron",
            id="scheduled_update",
            hour="0,8-23",
            minute=0,
            timezone=self.ist,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=30 * 60,
        )
        self.logger.info("Scheduled update job for hours 0 and 8-23 IST")

        # Schedule official placement scraping at 12:00 PM (noon) daily
        self.scheduler.add_job(
            self.run_official_placement_scrape,
            trigger="cron",
            hour=12,
            minute=0,
            timezone=self.ist,
            id="official_placement_scrape",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60 * 60,
        )
        self.logger.info("Scheduled official placement scrape at 12:00 PM IST daily")

        self.scheduler.start()
        safe_print("Scheduler started with update jobs")

    # =========================================================================
    # Server Lifecycle
    # =========================================================================

    async def run_async(self) -> None:
        """Run scheduler asynchronously"""
        try:
            # Setup logging
            setup_logging(self.settings)

            # Setup scheduler
            self.setup_scheduler()

            safe_print("Scheduler server is running. Press Ctrl+C to stop.")
            self.logger.info("Scheduler server started")

            # Keep running
            while self.running:
                await asyncio.sleep(1)

        finally:
            self.running = False
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown()
            self.logger.info("Scheduler server stopped")

    def run(self) -> None:
        """Run scheduler (blocking)"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.logger.info("Scheduler stopped by user")
            safe_print("Scheduler stopped.")
        finally:
            self.running = False

    async def shutdown(self) -> None:
        """Graceful shutdown"""
        self.running = False

        self.logger.info("Scheduler shutdown complete")


def create_scheduler_server(
    settings: Optional[Settings] = None,
    daemon_mode: bool = False,
) -> SchedulerServer:
    """
    Factory function to create scheduler server.

    The scheduler uses the runner modules directly (same as cmd_legacy),
    so no service injection is needed.
    """
    settings = settings or get_settings()
    return SchedulerServer(settings=settings, daemon_mode=daemon_mode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Scheduler Server")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    args = parser.parse_args()

    server = create_scheduler_server(daemon_mode=args.daemon)
    server.run()
