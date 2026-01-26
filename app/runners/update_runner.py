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
from clients.superset_client import SupersetClientService
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
        if db_service:
            self.db = db_service
            self._owns_db = False
        else:
            from clients.db_client import DBClient

            self.db_client = DBClient()
            self.db_client.connect()
            self.db = DatabaseService(self.db_client)
            self._owns_db = True

        self.scraper = scraper_service or SupersetClientService()
        self.formatter = formatter_service or NoticeFormatterService()

    def fetch_and_process_updates(self) -> dict:
        """
        Fetch new data from SuperSet and process it.

        Optimized to first check existing IDs in the database, then only
        fetch details for new notices/jobs.

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

        # Pre-fetch existing IDs from database for efficient filtering
        safe_print("Checking existing records in database...")
        existing_notice_ids = self.db.get_all_notice_ids()
        existing_job_ids = self.db.get_all_job_ids()
        safe_print(
            f"Found {len(existing_notice_ids)} existing notices, {len(existing_job_ids)} existing jobs in DB"
        )

        # Fetch notices and filter out existing ones
        safe_print("Fetching notices...")
        all_notices = self.scraper.get_notices(users)
        notices = [n for n in all_notices if n.id not in existing_notice_ids]
        safe_print(f"Found {len(all_notices)} notices ({len(notices)} new)")

        # Fetch basic job listings first (fast, no detail API calls)
        safe_print("Fetching basic job listings...")
        all_jobs_basic = self.scraper.get_job_listings_basic(users)
        safe_print(f"Found {len(all_jobs_basic)} job listings")

        # Filter for new jobs before fetching expensive details
        new_jobs_basic = [
            j
            for j in all_jobs_basic
            if j.get("jobProfileIdentifier") not in existing_job_ids
        ]
        safe_print(f"Found {len(new_jobs_basic)} new jobs to enrich")

        # Enrich only new jobs with detailed info (expensive API calls)
        enriched_new_jobs = []
        if new_jobs_basic:
            safe_print("Enriching new jobs with detailed info...")
            detail_user = users[0]
            enriched_new_jobs = self.scraper.enrich_jobs(detail_user, new_jobs_basic)
            safe_print(f"Enriched {len(enriched_new_jobs)} jobs with details")

        # For notice linking, structure existing jobs from basic info only (without API calls)
        # This is sufficient for matching company names in notices
        all_jobs_for_linking = enriched_new_jobs + [
            self.scraper.structure_job_listing(j)
            for j in all_jobs_basic
            if j.get("jobProfileIdentifier") in existing_job_ids
        ]

        # Track enriched job IDs for later
        enriched_job_ids = {j.id for j in enriched_new_jobs}

        # Process only new notices (use all_jobs for linking)
        # Also collect job IDs that were matched during notice processing
        new_notices, matched_job_ids = self._process_notices(
            notices, all_jobs_for_linking, users[0], all_jobs_basic, enriched_job_ids
        )
        safe_print(f"Saved {new_notices} new notices")

        # Process only new jobs (already enriched)
        new_jobs = self._process_jobs(enriched_new_jobs)
        safe_print(f"Saved {new_jobs} new jobs")

        return {"notices": new_notices, "jobs": new_jobs}

    def _process_notices(
        self,
        notices: list,
        jobs: list,
        detail_user,
        all_jobs_basic: list,
        already_enriched_ids: set,
    ) -> tuple[int, set]:
        """
        Process and save new notices (already filtered for new ones only).

        Uses job_enricher callback to enrich jobs mid-pipeline when matched.
        The LLM identifies the matching job, and if it needs enriching, the
        enricher callback fetches details before formatting continues.

        Returns:
            Tuple of (new_notices_count, matched_job_ids)
        """
        new_notices = 0
        matched_job_ids = set()

        # Create a lookup for basic job data by ID
        basic_job_lookup = {j.get("jobProfileIdentifier"): j for j in all_jobs_basic}

        # Create a mutable lookup for jobs (so enriched versions persist across notices)
        jobs_by_id = {j.id: j for j in jobs}

        def job_enricher(matched_job):
            """Callback to enrich a matched job with full details."""
            if matched_job.id in already_enriched_ids:
                # Already enriched, return the enriched version if we have it
                return jobs_by_id.get(matched_job.id, matched_job)

            basic_job = basic_job_lookup.get(matched_job.id)
            if not basic_job:
                return matched_job  # Can't enrich, return as-is

            # Enrich the job
            enriched_job = self.scraper.enrich_job(detail_user, basic_job)

            # Update our lookups
            jobs_by_id[matched_job.id] = enriched_job
            already_enriched_ids.add(matched_job.id)

            # Save to DB
            self.db.upsert_structured_job(enriched_job.model_dump())

            return enriched_job

        for notice in notices:
            try:
                # Format notice with enricher callback
                # The LLM will identify the matching job, and if found,
                # the enricher is called mid-pipeline before formatting
                formatted = self.formatter.format_notice(
                    notice,
                    list(jobs_by_id.values()),
                    job_enricher=job_enricher,
                )
                matched_job_id = formatted.get("matched_job_id")

                if matched_job_id:
                    matched_job_ids.add(matched_job_id)

                success, _ = self.db.save_notice(formatted)
                if success:
                    new_notices += 1

            except Exception as e:
                logger.error(f"Error processing notice {notice.id}: {e}")
                safe_print(f"Error processing notice {notice.id}: {e}")

        return new_notices, matched_job_ids

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
