"""Notice document construction helpers for email notices."""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from rapidfuzz import fuzz

from clients.google_groups_client import GoogleGroupsClient
from core.year_context import (
    DEFAULT_PLACEMENT_YEAR,
    extract_year_from_email_data,
    normalize_year,
)
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

    @staticmethod
    def _company_acronym(value: str) -> str:
        """Build a conservative acronym from a company name."""
        ignored = {
            "and",
            "company",
            "corporation",
            "global",
            "group",
            "india",
            "limited",
            "llc",
            "llp",
            "of",
            "private",
            "pvt",
            "the",
        }
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", value.casefold())
            if word not in ignored
        ]
        return "".join(word[0] for word in words).upper() if len(words) > 1 else ""

    def _find_job_candidates(
        self, notice: ExtractedNotice, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Rank year-scoped jobs by company and role text for the LLM judge."""
        company = " ".join((notice.company_name or "").split())
        role = " ".join((notice.role or "").split())
        if not company and not role:
            return []

        candidates: list[dict[str, Any]] = []
        for job in self._get_jobs():
            job_id = str(job.get("id") or job.get("_id") or "")
            job_company = " ".join(str(job.get("company") or "").split())
            job_role = " ".join(str(job.get("job_profile") or "").split())
            if not job_id or not job_company:
                continue

            company_score = 0.0
            acronym_match = False
            if company:
                company_score = fuzz.WRatio(company, job_company) / 100
                company_token = re.sub(r"[^A-Za-z0-9]", "", company).upper()
                acronym_match = (
                    len(company_token) >= 2
                    and company_token == self._company_acronym(job_company)
                )
                if acronym_match:
                    company_score = 1.0

            role_score = fuzz.WRatio(role, job_role) / 100 if role and job_role else 0.0
            if company and role:
                rank_score = 0.6 * company_score + 0.4 * role_score
                eligible = company_score >= 0.55 or acronym_match
            elif company:
                rank_score = company_score
                eligible = company_score >= 0.55 or acronym_match
            else:
                rank_score = role_score
                eligible = role_score >= 0.7

            if not eligible:
                continue
            candidates.append(
                {
                    "id": job_id,
                    "company": job_company,
                    "job_profile": job_role,
                    "location": job.get("location"),
                    "package": job.get("package"),
                    "annum_months": job.get("annum_months"),
                    "package_info": job.get("package_info"),
                    "deadline": job.get("deadline"),
                    "placement_type": job.get("placement_type"),
                    "company_score": round(company_score, 4),
                    "role_score": round(role_score, 4),
                    "rank_score": round(rank_score, 4),
                    "acronym_match": acronym_match,
                }
            )

        candidates.sort(key=lambda item: item["rank_score"], reverse=True)
        return candidates[:limit]

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
        likely_on_campus: bool = False,
        on_campus_confidence: float | None = None,
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
            likely_on_campus=likely_on_campus,
            on_campus_confidence=on_campus_confidence,
        )
