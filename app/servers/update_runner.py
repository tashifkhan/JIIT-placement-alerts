"""
Update Runner Service

Handles fetching and processing updates from SuperSet portal.
Uses dependency injection for testability.
"""

import json
import logging
from typing import Optional

from core.config import get_settings, safe_print
from services.database_service import DatabaseService
from services.superset_client import SupersetClientService
from services.notice_formatter_service import NoticeFormatterService


logger = logging.getLogger(__name__)


class UpdateRunner:
    """
    Service for fetching and processing updates from SuperSet.

    Uses dependency injection for all service dependencies.
    """

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        scraper_service: Optional[SupersetClientService] = None,
        formatter_service: Optional[NoticeFormatterService] = None,
    ):
        """
        Initialize UpdateRunner with dependencies.

        Args:
            db_service: Database service instance (created if not provided)
            scraper_service: SuperSet client instance (created if not provided)
            formatter_service: Formatter service instance (created if not provided)
        """
        self.db = db_service or DatabaseService()
        self.scraper = scraper_service or SupersetClientService()
        self.formatter = formatter_service or NoticeFormatterService()
        self._owns_db = db_service is None  # Track if we created the DB connection

    def fetch_and_process_updates(self) -> dict:
        """
        Fetch new data from SuperSet and process it.

        Returns:
            Dict with counts of new notices and jobs
        """
        settings = get_settings()

        safe_print("Initializing services...")

        # Login to SuperSet
        safe_print("Logging in to SuperSet...")
        users = []

        try:
            credentials = json.loads(settings.superset_credentials)
            if credentials:
                users = self.scraper.login_multiple(credentials)
                for user in users:
                    safe_print(f"Logged in as: {user.name}")
            else:
                safe_print("No credentials found in configuration.")

        except Exception as e:
            logger.error(f"Login process failed: {e}", exc_info=True)
            safe_print(f"Login process failed: {e}")

        if not users:
            safe_print("No users logged in. Check credentials.")
            return {"notices": 0, "jobs": 0}

        # Fetch data
        safe_print("Fetching notices...")
        notices = self.scraper.get_notices(users)
        safe_print(f"Found {len(notices)} notices")

        safe_print("Fetching job listings...")
        jobs = self.scraper.get_job_listings(users)
        safe_print(f"Found {len(jobs)} job listings")

        # Process notices
        new_notices = self._process_notices(notices, jobs)
        safe_print(f"Saved {new_notices} new notices")

        # Process jobs
        new_jobs = self._process_jobs(jobs)
        safe_print(f"Saved/updated {new_jobs} jobs")

        return {"notices": new_notices, "jobs": new_jobs}

    def _process_notices(self, notices: list, jobs: list) -> int:
        """Process and save new notices."""
        new_notices = 0
        for notice in notices:
            if not self.db.notice_exists(notice.id):
                try:
                    formatted = self.formatter.format_notice(notice, jobs)
                    success, _ = self.db.save_notice(formatted)
                    if success:
                        new_notices += 1

                except Exception as e:
                    logger.error(f"Error processing notice {notice.id}: {e}")
                    safe_print(f"Error processing notice {notice.id}: {e}")

        return new_notices

    def _process_jobs(self, jobs: list) -> int:
        """Process and save/update jobs."""
        new_jobs = 0
        for job in jobs:
            try:
                success, _ = self.db.upsert_structured_job(job.model_dump())
                if success:
                    new_jobs += 1

            except Exception as e:
                logger.error(f"Error processing job {job.id}: {e}")
                safe_print(f"Error processing job {job.id}: {e}")

        return new_jobs

    def close(self):
        """Close resources if we own them."""
        if self._owns_db:
            self.db.close_connection()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.close()
        return False


def fetch_and_process_updates(
    db_service: Optional[DatabaseService] = None,
    scraper_service: Optional[SupersetClientService] = None,
    formatter_service: Optional[NoticeFormatterService] = None,
) -> dict:
    """
    Convenience function to fetch and process updates.

    This is a functional wrapper around UpdateRunner for backward compatibility.

    Args:
        db_service: Optional database service (created if not provided)
        scraper_service: Optional SuperSet client (created if not provided)
        formatter_service: Optional formatter service (created if not provided)

    Returns:
        Dict with counts of new notices and jobs
    """
    with UpdateRunner(
        db_service=db_service,
        scraper_service=scraper_service,
        formatter_service=formatter_service,
    ) as runner:
        return runner.fetch_and_process_updates()
