"""
Placement Notification Formatter Service

Handles formatting and creating notices for placement events.
Decoupled from database operations for clean separation of concerns.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from core.config import safe_print
from model.notices import NoticeDocument


# Pydantic Models
class RoleData(BaseModel):
    """Role information from placement offer"""

    role: str = Field(..., description="Role/position title")
    package: float | None = Field(None, description="Package in numeric form")
    package_details: str | None = Field(
        None, description="Package breakdown details"
    )


class StudentData(BaseModel):
    """Student information from placement offer"""

    name: str = Field(..., description="Student name")
    enrollment_number: str | None = Field(None, description="Enrollment number")
    email: str | None = Field(None, description="Student email")
    role: str | None = Field(None, description="Role offered")
    package: float | None = Field(None, description="Package offered")
    location: str | None = Field(None, description="Job location")
    joining_date: str | None = Field(None, description="Joining date")
    offer_received_at: Any | None = Field(
        None, description="When this student received the offer"
    )
    offerReceivedAt: int | None = Field(
        None, description="Offer received time in epoch milliseconds"
    )


class OfferData(BaseModel):
    """Placement offer data structure"""

    company: str = Field(..., description="Company name")
    roles: list[RoleData] = Field(default_factory=list, description="Roles offered")
    job_location: list[str] | None = Field(None, description="Job locations")
    joining_date: str | None = Field(None, description="Joining date")
    students_selected: list[StudentData] = Field(
        default_factory=list, description="Students selected"
    )
    number_of_offers: int = Field(0, description="Total number of offers")
    time_sent: str | None = Field(None, description="Time when the email was sent")
    created_at: str | None = Field(None, description="Source creation time")
    createdAt: int | None = Field(None, description="Source creation time in ms")


class NewOfferEvent(BaseModel):
    """Event for a new placement offer"""

    type: Literal["new_offer"] = Field("new_offer", description="Event type")
    company: str = Field(..., description="Company name")
    offer_id: str = Field(..., description="Database offer ID")
    offer_data: OfferData = Field(..., description="Full offer data")
    roles: list[RoleData] = Field(default_factory=list, description="Roles")
    total_students: int = Field(0, description="Total students")
    time_sent: str | None = Field(None, description="Time when the email was sent")
    email_sender: str | None = Field(None, description="Original email sender")


class UpdateOfferEvent(BaseModel):
    """Event for an updated placement offer (new students added)"""

    type: Literal["update_offer"] = Field("update_offer", description="Event type")
    company: str = Field(..., description="Company name")
    offer_id: str = Field(..., description="Database offer ID")
    newly_added_students: list[StudentData] = Field(
        default_factory=list, description="Newly added students"
    )
    roles: list[RoleData] = Field(default_factory=list, description="Roles")
    total_students: int = Field(0, description="Total students after update")
    email_sender: str | None = Field(None, description="Original email sender")
    time_sent: str | None = Field(None, description="Time when the email was sent")


PlacementEvent = NewOfferEvent | UpdateOfferEvent


# Service
class PlacementNotificationFormatter:
    """
    Formats placement events into notification notices.

    This service handles the presentation logic for placement updates,
    decoupled from database storage operations.
    """

    def __init__(self, db_service: object | None = None):
        """
        Initialize formatter.

        Args:
            db_service: Database service for saving notices (optional)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service

    @staticmethod
    def format_package(package: float | None) -> str | None:
        """
        Format a package value to human-readable string.

        Args:
            package: Package value (numeric)

        Returns:
            Formatted string like "8.5 LPA" or None
        """
        if package is None:
            return None
        try:
            p = float(package)
            return f"{p / 100000:.1f} LPA" if p >= 100000 else f"{p:g} LPA"

        except (ValueError, TypeError):
            return str(package) if package is not None else None

    @staticmethod
    def _timestamp_ms(value: Any) -> int | None:
        """Convert source date values to epoch milliseconds."""
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            from dateutil import parser as date_parser

            dt = date_parser.parse(str(value).replace(" IST", " +05:30"), fuzzy=True)
            return int(dt.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _location_text(locations: list[str] | None) -> str | None:
        if not locations:
            return None
        return ", ".join(str(location) for location in locations if location)

    def _normalize_students(
        self,
        students: list[StudentData],
        default_location: str | None,
        default_joining_date: str | None,
    ) -> list[dict[str, Any]]:
        """Build student-based rows for Mongo/UI rendering."""
        rows: list[dict[str, Any]] = []
        for student in students:
            row: dict[str, Any] = {
                "name": student.name,
                "enrollment": student.enrollment_number,
                "enrollment_number": student.enrollment_number,
                "role": student.role,
                "package": student.package,
                "location": student.location or default_location,
                "joining_date": student.joining_date or default_joining_date,
                "offer_received_at": student.offer_received_at,
                "offerReceivedAt": student.offerReceivedAt,
            }
            rows.append({k: v for k, v in row.items() if v not in (None, "", [], {})})
        return rows

    def _match_job(self, company: str) -> dict[str, Any] | None:
        """Fuzzy-match placement offer company to a stored SuperSet job."""
        if not self.db_service or not hasattr(self.db_service, "get_all_jobs"):
            return None
        try:
            jobs = self.db_service.get_all_jobs() or []
        except Exception as e:
            self.logger.warning(
                "Could not load jobs for placement match: %s", e, exc_info=True
            )
            return None

        choices = {
            index: str(job.get("company", ""))
            for index, job in enumerate(jobs)
            if job.get("company")
        }
        if not choices:
            return None

        match = process.extractOne(company, choices, scorer=fuzz.token_set_ratio)
        if not match:
            return None

        _, score, index = match
        if score <= 80:
            return None

        job = jobs[index]
        package = self.format_package(job.get("package"))
        return {
            "id": str(job.get("id") or job.get("_id") or ""),
            "company": job.get("company"),
            "job_profile": job.get("job_profile"),
            "location": job.get("location"),
            "package": package,
        }

    def _role_package_breakdown(self, roles: list[RoleData]) -> str | None:
        lines: list[str] = []
        for role in roles:
            if role.package_details:
                lines.append(f"- {role.role}: {role.package_details}")
        return "\n".join(lines) if lines else None

    def _primary_role_and_package(
        self,
        roles: list[RoleData],
        students: list[StudentData],
    ) -> tuple[str | None, str | None]:
        role = next((r.role for r in roles if r.role), None)
        packages = [r.package for r in roles if r.package is not None]
        if not packages:
            packages = [s.package for s in students if s.package is not None]
        package = max(packages) if packages else None
        return role, self.format_package(package)

    def _base_notice_fields(
        self,
        company: str,
        offer_id: str,
        roles: list[RoleData],
        students: list[StudentData],
        time_sent: str | None,
        source_created_at: Any | None,
        joining_date: str | None = None,
        job_location: list[str] | None = None,
    ) -> dict[str, Any]:
        created_ms = self._timestamp_ms(source_created_at or time_sent)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        created_at = created_ms or now_ms
        location = self._location_text(job_location)
        selected_students = self._normalize_students(students, location, joining_date)
        matched_job = self._match_job(company)
        matched_job_id = matched_job.get("id") if matched_job else None
        role, package = self._primary_role_and_package(roles, students)

        return {
            "author": "PlacementBot",
            "type": "placement_offer",
            "source": "Placement Offer Service",
            "placement_offer_ref": offer_id,
            "createdAt": created_at,
            "updatedAt": created_at,
            "sent_to_telegram": False,
            "time_sent": time_sent,
            "category": "placement offer",
            "details": {
                "company": company,
                "roles": [role.model_dump() for role in roles],
                "job_location": job_location,
                "joining_date": joining_date,
                "placement_offer_ref": offer_id,
            },
            "job_company": matched_job.get("company") if matched_job else company,
            "job_role": matched_job.get("job_profile") if matched_job else role,
            "package": matched_job.get("package") if matched_job else package,
            "package_breakdown": self._role_package_breakdown(roles),
            "location": matched_job.get("location") if matched_job else location,
            "joining_date": joining_date,
            "selected_students": selected_students,
            "shortlisted_students": selected_students,
            "students_count": len(selected_students),
            "number_of_offers": len(selected_students),
            "matched_job_id": matched_job_id,
            "related_job_id": matched_job_id,
            "matched_job": matched_job,
        }

    def _build_role_breakdown(
        self,
        students: list[StudentData],
        roles: list[RoleData],
        prefix: str = "",
    ) -> tuple[str, dict[str, int]]:
        """
        Build role breakdown text and counts.

        Args:
            students: List of students
            roles: List of roles
            prefix: Prefix for offer count (e.g., "new ")

        Returns:
            Tuple of (breakdown_text, role_counts)
        """
        # Build role -> package mapping
        role_names = [r.role for r in roles if r.role]
        role_pkg: dict[str, str | None] = {}
        for r in roles:
            if r.role:
                role_pkg[r.role] = self.format_package(r.package)

        # Count students per role
        role_counts: dict[str, int] = {}
        default_role = role_names[0] if len(role_names) == 1 else None
        for s in students:
            rname = s.role or default_role or "Unspecified"
            role_counts[rname] = role_counts.get(rname, 0) + 1

        # Build breakdown lines
        lines: list[str] = []
        listed: set[str] = set()
        for rname in role_names:
            cnt = role_counts.get(rname, 0)
            if cnt <= 0:
                continue
            pkg_str = role_pkg.get(rname)
            suffix = f" — {pkg_str}" if pkg_str else ""
            lines.append(
                f"- {rname}: {cnt} {prefix}offer{'s' if cnt != 1 else ''}{suffix}"
            )
            listed.add(rname)

        for rname, cnt in role_counts.items():
            if rname in listed:
                continue
            lines.append(f"- {rname}: {cnt} {prefix}offer{'s' if cnt != 1 else ''}")

        return "\n".join(lines), role_counts

    def format_new_offer_notice(self, event: NewOfferEvent) -> NoticeDocument:
        """
        Format a new placement offer event into a notice document.

        Args:
            event: NewOfferEvent from database service

        Returns:
            NoticeDocument ready for saving
        """
        company = event.company
        offer_data = event.offer_data
        roles = [
            RoleData(**r.model_dump()) if isinstance(r, RoleData) else RoleData(**r)
            for r in event.roles
        ]
        students = offer_data.students_selected
        total_count = len(students)
        offer_id = str(event.offer_id)
        safe_company = company.replace(" ", "_") or "unknown_company"
        time_sent = event.time_sent or offer_data.time_sent
        base_fields = self._base_notice_fields(
            company=company,
            offer_id=offer_id,
            roles=roles,
            students=students,
            time_sent=time_sent,
            source_created_at=offer_data.createdAt or offer_data.created_at,
            joining_date=offer_data.joining_date,
            job_location=offer_data.job_location,
        )
        base_fields["author"] = event.email_sender or "PlacementBot"
        base_fields["details"] = {
            **base_fields["details"],
            "is_update": False,
            "number_of_offers": total_count,
        }
        notice_id = f"placement_{safe_company}_{int(base_fields['createdAt'] / 1000)}"

        return NoticeDocument(
            id=notice_id,
            title=f"Placement Offer: {company}",
            content="",
            **base_fields,
            is_update=False,
            new_students_count=None,
        )

    def format_update_offer_notice(self, event: UpdateOfferEvent) -> NoticeDocument:
        """
        Format a placement update event (new students added) into a notice document.

        Args:
            event: UpdateOfferEvent from database service

        Returns:
            NoticeDocument ready for saving
        """
        company = event.company
        offer_id = str(event.offer_id)
        newly_added_students = event.newly_added_students
        roles = [
            RoleData(**r.model_dump()) if isinstance(r, RoleData) else RoleData(**r)
            for r in event.roles
        ]
        total_students = event.total_students
        new_count = len(newly_added_students)
        safe_company = company.replace(" ", "_") or "unknown_company"
        base_fields = self._base_notice_fields(
            company=company,
            offer_id=offer_id,
            roles=roles,
            students=newly_added_students,
            time_sent=event.time_sent,
            source_created_at=event.time_sent,
        )
        base_fields["author"] = event.email_sender or "PlacementBot"
        base_fields["number_of_offers"] = total_students
        base_fields["students_count"] = new_count
        base_fields["details"] = {
            **base_fields["details"],
            "is_update": True,
            "new_students_count": new_count,
            "number_of_offers": total_students,
        }
        notice_id = f"placement_update_{safe_company}_{int(base_fields['createdAt'] / 1000)}"

        return NoticeDocument(
            id=notice_id,
            title=f"Placement Update: {company} (+{new_count})",
            content="",
            **base_fields,
            is_update=True,
            new_students_count=new_count,
        )

    def format_event(self, event: dict) -> NoticeDocument:
        """
        Format any placement event into a notice document.

        Args:
            event: Event dict with 'type' field

        Returns:
            NoticeDocument ready for saving
        """
        event_type = event.get("type")

        if event_type == "new_offer":
            # Parse into typed event
            parsed_event = NewOfferEvent(
                type="new_offer",
                company=event.get("company", "Unknown"),
                offer_id=str(event.get("offer_id", "")),
                offer_data=OfferData(**event.get("offer_data", {})),
                roles=[RoleData(**r) for r in event.get("roles", [])],
                total_students=event.get("total_students", 0),
                time_sent=event.get("time_sent"),
                email_sender=event.get("email_sender"),
            )
            return self.format_new_offer_notice(parsed_event)
        elif event_type == "update_offer":
            parsed_event = UpdateOfferEvent(
                type="update_offer",
                company=event.get("company", "Unknown"),
                offer_id=str(event.get("offer_id", "")),
                newly_added_students=[
                    StudentData(**s) for s in event.get("newly_added_students", [])
                ],
                roles=[RoleData(**r) for r in event.get("roles", [])],
                total_students=event.get("total_students", 0),
                email_sender=event.get("email_sender"),
                time_sent=event.get("time_sent"),
            )
            return self.format_update_offer_notice(parsed_event)
        else:
            raise ValueError(f"Unknown event type: {event_type}")

    def process_events(
        self,
        events: list[dict],
        save_to_db: bool = True,
    ) -> list[NoticeDocument]:
        """
        Process multiple placement events, format them, and optionally save.

        Args:
            events: List of events from database service
            save_to_db: Whether to save notices to database

        Returns:
            List of NoticeDocument objects
        """
        notices: list[NoticeDocument] = []

        for event in events:
            try:
                notice = self.format_event(event)
                notices.append(notice)

                if save_to_db and self.db_service:
                    success, _ = self.db_service.save_notice(notice.model_dump())  # type: ignore
                    if success:
                        safe_print(f"Created placement notice: {notice.id}")
                    else:
                        safe_print(f"Notice already exists: {notice.id}")

            except Exception as e:
                self.logger.exception("Error processing placement event")
                safe_print(f"Error processing placement event: {e}")

        return notices
