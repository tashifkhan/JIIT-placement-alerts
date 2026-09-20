"""Email notice service orchestration."""

import logging
from typing import Any

from clients.google_groups_client import GoogleGroupsClient
from core import get_settings, safe_print
from core.llm import DEFAULT_GEMINI_MODEL, build_chat_model
from services.email_notice.document_builder import EmailNoticeDocumentMixin
from services.email_notice.graph import EmailNoticeGraphMixin
from services.email_notice.models import NoticeDocument, NoticeGraphState
from services.placement_policy import PlacementPolicyService


class EmailNoticeService(EmailNoticeGraphMixin, EmailNoticeDocumentMixin):
    """
    Service for extracting structured non-placement notices from email.

    Handles fetching Google Groups emails, LLM-based classification/extraction,
    policy handoff, structured notice document creation, and database saves.
    """

    def __init__(
        self,
        email_client: GoogleGroupsClient | None = None,
        google_api_key: str | None = None,
        db_service: Any | None = None,
        policy_service: PlacementPolicyService | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
    ):
        """
        Initialize email notice service.

        Args:
            email_client: GoogleGroupsClient instance for fetching emails.
            google_api_key: API key for LLM.
            db_service: Database service for saving notices.
            policy_service: Optional injected PlacementPolicyService.
            model: LLM model to use.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.email_client = email_client or GoogleGroupsClient()
        settings = get_settings()
        api_key = google_api_key or settings.google_api_key
        self.db_service = db_service
        self._jobs_cache: list[dict[str, Any]] | None = None

        if policy_service:
            self.policy_service = policy_service
        else:
            self.policy_service = PlacementPolicyService(
                db_service=db_service, google_api_key=api_key
            )

        self.llm = build_chat_model(model=model, api_key=api_key)
        self.app = self._build_graph()

        self.logger.info("EmailNoticeService initialized")

    def process_emails(self, mark_as_read: bool = True) -> list[NoticeDocument]:
        """
        Fetch and process unread emails for notices sequentially.

        Args:
            mark_as_read: Whether to mark emails as read after processing.

        Returns:
            List of NoticeDocument objects for valid notices.
        """
        safe_print("Fetching unread email IDs...")
        try:
            email_ids = self.email_client.get_unread_message_ids()
        except Exception as e:
            self.logger.exception("Failed to fetch email IDs")
            safe_print(f"Error fetching email IDs: {e}")
            return []

        safe_print(f"Found {len(email_ids)} unread emails")
        notices: list[NoticeDocument] = []

        for email_id in email_ids:
            try:
                email_data = self.email_client.fetch_email(email_id, mark_as_read=False)

                if not email_data:
                    safe_print(f"Failed to fetch content for email {email_id}, skipping")
                    continue

                result = self.process_single_email(email_data)

                if result:
                    notices.append(result)
                    if self.db_service:
                        success, _ = self.db_service.save_notice(result.model_dump())
                        if success:
                            safe_print(f"Saved notice: {result.title}")

                if mark_as_read:
                    self.email_client.mark_as_read(email_id)

            except Exception as e:
                self.logger.exception("Error processing email %s", email_id)
                safe_print(f"Error processing email {email_id}: {e}")

        safe_print(f"Processed {len(notices)} notices")
        return notices

    def process_single_email(
        self, email_data: dict[str, str]
    ) -> NoticeDocument | None:
        """
        Process a single email through the extraction pipeline.

        Args:
            email_data: Dict with subject, sender, and body keys.

        Returns:
            NoticeDocument if valid notice, otherwise None.
        """
        initial_state: NoticeGraphState = {
            "email": email_data,
            "is_relevant": None,
            "confidence_score": None,
            "classification_reason": None,
            "rejection_reason": None,
            "extracted_notice": None,
            "validation_errors": None,
            "retry_count": 0,
            "extracted_policy": None,
            "is_policy_update": False,
        }

        result = self.app.invoke(initial_state)

        if result.get("is_policy_update") and result.get("extracted_policy"):
            self.policy_service.process_policy_email(
                email_data, result.get("extracted_policy")
            )
            return None

        notice = result.get("extracted_notice")
        if not notice or not result.get("is_relevant"):
            return None

        return self._create_notice_document(notice, email_data)
