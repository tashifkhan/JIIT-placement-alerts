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

import asyncio
import logging
from typing import Optional
from datetime import time

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
        self.logger.info("Running scheduled update...")
        safe_print("Starting scheduled update job...")

        try:
            # Import the same modules used by main.py commands
            from runners.update_runner import fetch_and_process_updates
            from runners.notification_runner import send_updates

            # Step 1: Fetch updates (SuperSet + Emails)
            # This mirrors cmd_update() in main.py
            safe_print("━━━ Fetching SuperSet Updates ━━━")
            ss_result = fetch_and_process_updates()
            safe_print(f"SuperSet update: {ss_result}")

            # Step 2: Fetch email updates (placement offers + general notices)
            # This mirrors cmd_update_emails() in main.py
            safe_print("━━━ Fetching Email Updates ━━━")
            email_result = self._run_email_updates()
            safe_print(f"Email update: {email_result}")

            # Step 3: Send via Telegram
            # This mirrors the send_updates call in cmd_legacy
            safe_print("━━━ Sending Telegram Notifications ━━━")
            send_result = send_updates(telegram=True, web=False)
            safe_print(f"Send result: {send_result}")

            safe_print("━━━ Scheduled Update Complete ━━━")

        except Exception as e:
            self.logger.error(f"Scheduled update failed: {e}", exc_info=True)
            safe_print(f"Scheduled update error: {e}")

    def _run_email_updates(self) -> dict:
        """
        Fetch and process BOTH placement offers AND general notices from Emails.

        This mirrors cmd_update_emails() in main.py.
        """
        import logging
        from services.database_service import DatabaseService
        from services.placement_service import PlacementService
        from services.placement_notification_formatter import (
            PlacementNotificationFormatter,
        )
        from clients.google_groups_client import GoogleGroupsClient
        from clients.db_client import DBClient
        from services.email_notice_service import EmailNoticeService
        from services.placement_policy_service import PlacementPolicyService

        logger = logging.getLogger(__name__)
        safe_print("Starting email updates (placement offers + general notices)...")

        # Create shared dependencies
        db_client = DBClient()
        db_client.connect()
        db = DatabaseService(db_client)
        email_client = GoogleGroupsClient()
        policy_service = PlacementPolicyService(db_service=db)

        # Create services
        notification_formatter = PlacementNotificationFormatter(db_service=db)
        placement_service = PlacementService(
            db_service=db,
            notification_formatter=notification_formatter,
        )

        notice_service = EmailNoticeService(
            email_client=email_client,
            db_service=db,
            policy_service=policy_service,
        )

        logger.info("Created services for orchestrated email processing")

        # Fetch unread emails
        try:
            email_ids = email_client.get_unread_message_ids()
        except Exception as e:
            safe_print(f"Error fetching email IDs: {e}")
            db.close_connection()
            return {"error": str(e)}

        safe_print(f"Found {len(email_ids)} unread emails")

        placement_count = 0
        notice_count = 0
        skipped_count = 0

        for e_id in email_ids:
            try:
                email_data = email_client.fetch_email(e_id, mark_as_read=False)
                if not email_data:
                    safe_print(f"Failed to fetch email {e_id}, skipping")
                    continue

                subject = email_data.get("subject", "Unknown")
                safe_print(f"📧 Processing: {subject[:60]}...")

                processed = False

                # Try PlacementService first
                offer = placement_service.process_email(email_data)
                if offer:
                    safe_print(f"  ✓ Placement offer detected: {offer.company}")
                    offer_data = offer.model_dump()

                    try:
                        result = db.save_placement_offers([offer_data])
                        events = result.get("events", [])

                        if events and notification_formatter:
                            notification_formatter.process_events(
                                events, save_to_db=True
                            )

                        placement_count += 1
                        processed = True
                    except Exception as e:
                        safe_print(f"  ⚠ Error saving placement: {e}")

                # If not a placement offer, try EmailNoticeService
                if not processed:
                    notice_doc = notice_service.process_single_email(email_data)
                    if notice_doc:
                        safe_print(f"  ✓ Notice detected: {notice_doc.type}")
                        try:
                            success, _ = db.save_notice(notice_doc.model_dump())
                            if success:
                                notice_count += 1
                                processed = True
                        except Exception as e:
                            safe_print(f"  ⚠ Error saving notice: {e}")
                    else:
                        safe_print(f"  ○ Not relevant (skipped)")
                        skipped_count += 1
                        processed = True

                # Mark as read if processed
                if processed:
                    email_client.mark_as_read(e_id)

            except Exception as e:
                safe_print(f"  ✗ Error processing email {e_id}: {e}")

        db.close_connection()

        return {
            "emails_processed": len(email_ids),
            "placements": placement_count,
            "notices": notice_count,
            "skipped": skipped_count,
        }

    async def run_official_placement_scrape(self) -> None:
        """
        Scrape official placement data from JIIT website.

        This mirrors cmd_official() in main.py.
        Runs daily at 12:00 PM IST.
        """
        self.logger.info("Running official placement scrape...")
        safe_print("━━━ Scraping Official Placement Data ━━━")

        try:
            from services.official_placement_service import OfficialPlacementService
            from services.database_service import DatabaseService
            from clients.db_client import DBClient

            db_client = DBClient()
            db_client.connect()
            db_service = DatabaseService(db_client)
            service = OfficialPlacementService(db_service=db_service)

            data = service.scrape_and_save()

            db_service.close_connection()

            safe_print(
                f"Official placement scrape complete: {len(data) if data else 0} records"
            )
            self.logger.info(
                f"Official placement scrape complete: {len(data) if data else 0} records"
            )

        except Exception as e:
            self.logger.error(f"Official placement scrape failed: {e}", exc_info=True)
            safe_print(f"Official placement scrape error: {e}")

    def setup_scheduler(self) -> None:
        """Setup scheduled jobs"""
        self.scheduler = AsyncIOScheduler(timezone=self.ist)

        # Schedule updates at specific times (IST)
        schedule_times = [
            time(8, 0),  # 8:00 AM
            time(9, 0),  # 9:00 AM
            time(10, 0),  # 10:00 AM
            time(11, 0),  # 11:00 AM
            time(12, 0),  # 12:00 PM
            time(13, 0),  # 1:00 PM
            time(14, 0),  # 2:00 PM
            time(15, 0),  # 3:00 PM
            time(16, 0),  # 4:00 PM
            time(17, 0),  # 5:00 PM
            time(18, 0),  # 6:00 PM
            time(19, 0),  # 7:00 PM
            time(20, 0),  # 8:00 PM
            time(21, 0),  # 9:00 PM
            time(22, 0),  # 10:00 PM
            time(23, 0),  # 11:00 PM
            time(0, 0),  # 12:00 AM
        ]

        for t in schedule_times:
            self.scheduler.add_job(
                self.run_scheduled_update,
                trigger="cron",
                hour=t.hour,
                minute=t.minute,
                timezone=self.ist,
            )
            self.logger.info(f"Scheduled update job at {t.strftime('%H:%M')} IST")

        # Schedule official placement scraping at 12:00 PM (noon) daily
        self.scheduler.add_job(
            self.run_official_placement_scrape,
            trigger="cron",
            hour=12,
            minute=0,
            timezone=self.ist,
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
    import argparse

    parser = argparse.ArgumentParser(description="Run Scheduler Server")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    args = parser.parse_args()

    server = create_scheduler_server(daemon_mode=args.daemon)
    server.run()
