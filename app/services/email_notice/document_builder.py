"""Notice document construction helpers for email notices."""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from clients.google_groups_client import GoogleGroupsClient
from core.year_context import (
    DEFAULT_PLACEMENT_YEAR,
    extract_year_from_email_data,
    normalize_year,
)
from services.campus_match import find_job_candidates
from services.email_notice.models import ExtractedNotice, NoticeDocument
from services.notice_formatter import NoticeFormatterService

logger = logging.getLogger(__name__)


class EmailNoticeDocumentMixin:
    """Helpers for matching jobs and building structured NoticeDocument objects."""

    @staticmethod
    def _timestamp_ms_from_date(date_str: str | None) -> int | None:
        """Convert a date-like string to epoch milliseconds."""
        if not date_str:
            return None
        try:
            from dateutil import parser as date_parser

            dt = date_parser.parse(str(date_str), fuzzy=True)
            if dt.tzinfo is None:
                from zoneinfo import ZoneInfo

                dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            return int(dt.timestamp() * 1000)
        except Exception:
            logger.exception("Error parsing date string: %s", date_str)
            return None

    @staticmethod
    def _normalize_category(notice_type: str | None) -> str:
        """Map the internal notice type to the website-facing category vocabulary."""
        return (notice_type or "announcement").replace("_", " ").strip().lower()

    @staticmethod
    def _notice_id(email_data: dict[str, str]) -> str:
        """Build a stable notice ID from the email's immutable identity."""
        message_id = " ".join(str(email_data.get("message_id") or "").split())
        if message_id:
            identity = f"message-id:{message_id}"
        else:
            normalized_body = " ".join(str(email_data.get("body") or "").split())
            body_digest = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()
            identity_fields = {
                "sender": " ".join(
                    str(email_data.get("sender") or "").split()
                ).casefold(),
                "subject": " ".join(
                    str(email_data.get("subject") or "").split()
                ).casefold(),
                "time_sent": " ".join(
                    str(email_data.get("time_sent") or "").split()
                ),
                "body_digest": body_digest,
            }
            identity = json.dumps(identity_fields, sort_keys=True, separators=(",", ":"))
        return f"notice_{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"

    def _get_jobs(self) -> list[dict[str, Any]]:
        """Return and cache structured jobs from the DB."""
        if self._jobs_cache is not None:
            return self._jobs_cache

        jobs: list[dict[str, Any]] = []
        if self.db_service and hasattr(self.db_service, "get_all_jobs"):
            try:
                jobs = self.db_service.get_all_jobs(limit=0) or []
            except Exception as e:  # pragma: no cover - defensive
                self.logger.warning(
                    "Could not load jobs for matching: %s", e, exc_info=True
                )
                jobs = []
        self._jobs_cache = jobs
        return jobs

    def _find_job_candidates(
        self, notice: ExtractedNotice, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Rank year-scoped jobs by company and role text for the LLM judge."""
        return find_job_candidates(
            self._get_jobs(), notice.company_name, notice.role, limit
        )

    @staticmethod
    def _build_details(notice: ExtractedNotice) -> dict[str, Any]:
        """Build a compact structured payload from extracted notice fields."""
        dropped = {"is_notice", "rejection_reason", "title", "content", "type", "source"}
        data = notice.model_dump()
        return {
            key: value
            for key, value in data.items()
            if key not in dropped and value not in (None, [], "")
        }

    def _create_notice_document(
        self,
        notice: ExtractedNotice,
        email_data: dict[str, str],
        *,
        matched_job: dict[str, Any] | None = None,
    ) -> NoticeDocument:
        """Create a structured NoticeDocument from extracted JSON fields."""
        timestamp = datetime.now(UTC).timestamp()
        notice_id = self._notice_id(email_data)

        body = email_data.get("body", "")
        forwarded_sender = GoogleGroupsClient.extract_forwarded_sender(body)
        raw_author = forwarded_sender or email_data.get("sender") or "EmailNoticeBot"
        author = re.sub(r"\s*<[^>]+>", "", raw_author).strip()

        time_sent = email_data.get("time_sent")
        created_ms = self._timestamp_ms_from_date(time_sent) or int(timestamp * 1000)

        students_list = notice.students if notice.type == "internship_noc" else None
        students_count = len(notice.students) if notice.students else None
        shortlisted = notice.students if notice.type == "shortlisting" else None

        try:
            year = extract_year_from_email_data(email_data) or normalize_year(
                DEFAULT_PLACEMENT_YEAR
            )
        except Exception:
            logger.exception("Error resolving notice year from email data")
            year = normalize_year(DEFAULT_PLACEMENT_YEAR)

        matched_job_id = matched_job.get("id") if matched_job else None
        if matched_job and matched_job.get("package") is not None:
            package = NoticeFormatterService._format_package(
                matched_job.get("package"), matched_job.get("annum_months")
            )
            package_breakdown = NoticeFormatterService.format_html_breakdown(
                matched_job.get("package_info")
            )
        else:
            package = notice.package
            package_breakdown = None

        matched_job_summary: dict[str, Any] | None = None
        if matched_job:
            matched_job_summary = {
                "id": matched_job.get("id"),
                "company": matched_job.get("company"),
                "job_profile": matched_job.get("job_profile"),
                "location": matched_job.get("location"),
                "package": package,
                "package_breakdown": package_breakdown or None,
            }

        return NoticeDocument(
            id=notice_id,
            title=notice.title or "Notice",
            content=notice.content or "",
            author=author,
            type=notice.type or "announcement",
            source="Email Notice Service",
            createdAt=created_ms,
            updatedAt=created_ms,
            sent_to_telegram=False,
            time_sent=time_sent,
            deadline=notice.deadline,
            links=notice.links,
            students=students_list,
            students_count=students_count,
            category=self._normalize_category(notice.type),
            year=year,
            details=self._build_details(notice),
            job_company=(matched_job or {}).get("company") or notice.company_name,
            job_role=(matched_job or {}).get("job_profile") or notice.role,
            package=package,
            package_breakdown=package_breakdown,
            location=(matched_job or {}).get("location") or notice.location or notice.venue,
            eligibility_criteria=notice.eligibility_criteria,
            hiring_flow=notice.hiring_flow,
            shortlisted_students=shortlisted or [],
            matched_job_id=matched_job_id,
            related_job_id=matched_job_id,
            matched_job=matched_job_summary,
        )
