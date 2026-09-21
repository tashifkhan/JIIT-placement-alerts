"""Placement service orchestration."""

import logging
import os
from typing import Any

from clients.google_groups_client import GoogleGroupsClient
from core.config import get_settings, safe_print
from core.llm import DEFAULT_GEMINI_MODEL, build_chat_model
from services.placement.extraction.email_fetcher import PlacementEmailFetcherMixin
from services.placement.extraction.graph import PlacementGraphMixin
from services.placement.extraction.models import GraphState, PlacementOffer
from services.placement.extraction.storage import PlacementStorageMixin


class PlacementService(
    PlacementGraphMixin,
    PlacementEmailFetcherMixin,
    PlacementStorageMixin,
):
    """
    Service for fetching placement emails and extracting placement offers.

    Handles Google Groups/IMAP fetching, LangGraph extraction, privacy
    sanitization, database persistence, and notice creation.
    """

    def __init__(
        self,
        email_address: str | None = None,
        app_password: str | None = None,
        google_api_key: str | None = None,
        db_service: Any | None = None,
        notification_formatter: Any | None = None,
        email_client: Any | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        output_file: str | None = None,
    ):
        """
        Initialize placement service.

        Args:
            email_address: Email to fetch from (deprecated, use email_client).
            app_password: App password for email (deprecated, use email_client).
            google_api_key: API key for LLM.
            db_service: Database service for saving offers.
            notification_formatter: Formatter for creating placement notices.
            email_client: GoogleGroupsClient instance for fetching emails.
            model: LLM model to use.
            output_file: JSON output file path used as fallback.
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        settings = get_settings()
        self.email_address = email_address or settings.placement_email
        self.app_password = app_password or settings.placement_app_password
        self.email_client = email_client or GoogleGroupsClient(
            email_address=self.email_address,
            app_password=self.app_password,
        )
        api_key = google_api_key or settings.google_api_key

        self.db_service = db_service
        self._jobs_cache: list[dict[str, Any]] | None = None
        self.likely_on_campus_min_confidence = (
            settings.likely_on_campus_min_confidence
        )
        self.notification_formatter = notification_formatter
        self.output_file = output_file or os.path.join(
            os.getcwd(), "data", "placement_offers.json"
        )

        self.llm = build_chat_model(model=model, api_key=api_key)

        self.app = self._build_graph()

        self.logger.info("PlacementService initialized")

    def _get_jobs(self) -> list[dict[str, Any]]:
        """Return this year's jobs for on-campus matching, loaded once per run."""
        if self._jobs_cache is not None:
            return self._jobs_cache
        jobs: list[dict[str, Any]] = []
        if self.db_service and hasattr(self.db_service, "get_all_jobs"):
            try:
                jobs = self.db_service.get_all_jobs(limit=0) or []
            except Exception:
                self.logger.warning("Could not load jobs for on-campus matching", exc_info=True)
        self._jobs_cache = jobs
        return jobs

    def process_email(self, email_data: dict[str, str]) -> PlacementOffer | None:
        """Process a single email through the LangGraph pipeline."""
        state: GraphState = {
            "email": email_data,
            "is_relevant": None,
            "confidence_score": None,
            "classification_reason": None,
            "rejection_reason": None,
            "extracted_offer": None,
            "validation_errors": None,
            "retry_count": None,
        }

        result = self.app.invoke(state)
        return result.get("extracted_offer")

    def update_placement_records(self) -> dict[str, Any]:
        """
        Fetch emails, process them, and save extracted placement offers.

        Creates placement notices for new and updated offers.
        """
        emails_fetched = 0
        offers_extracted = 0
        notices_created = 0
        extracted_offers: list[dict[str, Any]] = []

        if self.email_client:
            safe_print("Fetching unread email IDs...")
            try:
                email_ids = self.email_client.get_unread_message_ids()
            except Exception as e:
                safe_print(f"Error fetching email IDs: {e}")
                self.logger.exception("Error fetching email IDs")
                return {}

            safe_print(
                f"Found {len(email_ids)} unread emails. Processing sequentially..."
            )

            for email_id in email_ids:
                try:
                    email_data = self.email_client.fetch_email(
                        email_id, mark_as_read=False
                    )
                    if not email_data:
                        safe_print(f"Failed to content for email {email_id}")
                        continue

                    emails_fetched += 1
                    safe_print(
                        f"\nProcessing email: {email_data.get('subject', 'Unknown')}"
                    )

                    offer = self.process_email(email_data)

                    if offer:
                        offers_extracted += 1
                        offer_data = offer.model_dump()
                        extracted_offers.append(offer_data)

                        save_success = False
                        events = []

                        if self.db_service:
                            try:
                                result = self.db_service.save_placement_offers(
                                    [offer_data]
                                )
                                safe_print(f"Database save result: {result}")
                                events = result.get("events", [])
                                save_success = True
                            except Exception as e:
                                safe_print(f"Error saving to DB: {e}")
                                self.logger.exception(
                                    "Error saving placement offer to database"
                                )
                                self.save_to_json([offer_data])
                        else:
                            self.save_to_json([offer_data])
                            save_success = True

                        if save_success and events and self.notification_formatter:
                            safe_print(f"Creating notices for {len(events)} events...")
                            new_notices = self.notification_formatter.process_events(
                                events, save_to_db=True
                            )
                            notices_created += len(new_notices)

                        if save_success:
                            self.email_client.mark_as_read(email_id)
                    else:
                        safe_print("No valid offer extracted. Marking as read.")
                        self.email_client.mark_as_read(email_id)

                except Exception as e:
                    safe_print(f"Error processing email {email_id}: {e}")
                    self.logger.exception("Error processing email %s", email_id)

        else:
            safe_print("Using legacy bulk processing (no email_client configured)...")
            unread_emails = self.fetch_unread_emails()
            emails_fetched = len(unread_emails)

            for email_data in unread_emails:
                safe_print(
                    f"\nProcessing email: {email_data.get('subject', 'Unknown')}"
                )
                offer = self.process_email(email_data)
                if offer:
                    extracted_offers.append(offer.model_dump())
                    offers_extracted += 1

            if extracted_offers:
                events = []
                if self.db_service:
                    try:
                        result = self.db_service.save_placement_offers(extracted_offers)
                        events = result.get("events", [])
                    except Exception as e:
                        safe_print(f"Error saving offers: {e}")
                        self.logger.exception("Error saving extracted offers to database")
                        self.save_to_json(extracted_offers)
                else:
                    self.save_to_json(extracted_offers)

                if events and self.notification_formatter:
                    new_notices = self.notification_formatter.process_events(
                        events, save_to_db=True
                    )
                    notices_created = len(new_notices)

        safe_print("\nSummary:")
        safe_print(f"   • Emails fetched: {emails_fetched}")
        safe_print(f"   • Valid offers extracted: {offers_extracted}")
        safe_print(f"   • Notices created: {notices_created}")
        success_rate = (
            f"{(offers_extracted / emails_fetched * 100):.1f}%"
            if emails_fetched
            else "0%"
        )
        safe_print(f"   • Success rate: {success_rate}")

        return {
            "emails_fetched": emails_fetched,
            "offers_extracted": offers_extracted,
            "notices_created": notices_created,
            "offers": extracted_offers,
        }
