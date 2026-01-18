"""
Placement Notification Formatter Service

Handles formatting and creating notices for placement events.
Decoupled from database operations for clean separation of concerns.
"""

import logging
from typing import List, Optional, Union, Literal
from datetime import datetime

from pydantic import BaseModel, Field

from core.config import safe_print


# Pydantic Models
class RoleData(BaseModel):
    """Role information from placement offer"""

    role: str = Field(..., description="Role/position title")
    package: Optional[float] = Field(None, description="Package in numeric form")
    package_details: Optional[str] = Field(
        None, description="Package breakdown details"
    )


class StudentData(BaseModel):
    """Student information from placement offer"""

    name: str = Field(..., description="Student name")
    enrollment_number: Optional[str] = Field(None, description="Enrollment number")
    email: Optional[str] = Field(None, description="Student email")
    role: Optional[str] = Field(None, description="Role offered")
    package: Optional[float] = Field(None, description="Package offered")


class OfferData(BaseModel):
    """Placement offer data structure"""

    company: str = Field(..., description="Company name")
    roles: List[RoleData] = Field(default_factory=list, description="Roles offered")
    students_selected: List[StudentData] = Field(
        default_factory=list, description="Students selected"
    )
    number_of_offers: int = Field(0, description="Total number of offers")
    time_sent: Optional[str] = Field(None, description="Time when the email was sent")


class NewOfferEvent(BaseModel):
    """Event for a new placement offer"""

    type: Literal["new_offer"] = Field("new_offer", description="Event type")
    company: str = Field(..., description="Company name")
    offer_id: str = Field(..., description="Database offer ID")
    offer_data: OfferData = Field(..., description="Full offer data")
    roles: List[RoleData] = Field(default_factory=list, description="Roles")
    total_students: int = Field(0, description="Total students")
    time_sent: Optional[str] = Field(None, description="Time when the email was sent")
    email_sender: Optional[str] = Field(None, description="Original email sender")


class UpdateOfferEvent(BaseModel):
    """Event for an updated placement offer (new students added)"""

    type: Literal["update_offer"] = Field("update_offer", description="Event type")
    company: str = Field(..., description="Company name")
    offer_id: str = Field(..., description="Database offer ID")
    newly_added_students: List[StudentData] = Field(
        default_factory=list, description="Newly added students"
    )
    roles: List[RoleData] = Field(default_factory=list, description="Roles")
    total_students: int = Field(0, description="Total students after update")
    email_sender: Optional[str] = Field(None, description="Original email sender")
    time_sent: Optional[str] = Field(None, description="Time when the email was sent")


PlacementEvent = Union[NewOfferEvent, UpdateOfferEvent]


class NoticeDocument(BaseModel):
    """Notice document ready for database storage"""

    id: str = Field(..., description="Unique notice ID")
    title: str = Field(..., description="Notice title")
    content: str = Field(..., description="Notice content")
    author: str = Field("PlacementBot", description="Author name")
    type: str = Field("placement_update", description="Notice type")
    source: str = Field("PlacementOffers", description="Source")
    placement_offer_ref: str = Field(..., description="Reference to placement offer")
    formatted_message: str = Field(..., description="Formatted message for sending")
    createdAt: int = Field(..., description="Creation timestamp (ms)")
    updatedAt: int = Field(..., description="Update timestamp (ms)")
    sent_to_telegram: bool = Field(False, description="Whether sent to Telegram")
    is_update: Optional[bool] = Field(
        None, description="Whether this is an update notice"
    )
    new_students_count: Optional[int] = Field(None, description="Count of new students")


# Service
class PlacementNotificationFormatter:
    """
    Formats placement events into notification notices.

    This service handles the presentation logic for placement updates,
    decoupled from database storage operations.
    """

    def __init__(self, db_service: Optional[object] = None):
        """
        Initialize formatter.

        Args:
            db_service: Database service for saving notices (optional)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service

    @staticmethod
    def format_package(package: Optional[float]) -> Optional[str]:
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

    def _build_role_breakdown(
        self,
        students: List[StudentData],
        roles: List[RoleData],
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
        role_pkg: dict[str, Optional[str]] = {}
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
        lines: List[str] = []
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

        ts = datetime.utcnow().timestamp()
        safe_company = company.replace(" ", "_") or "unknown_company"
        notice_id = f"placement_{safe_company}_{int(ts)}"

        breakdown, _ = self._build_role_breakdown(students, roles)

        # Build summary
        summary = f"{total_count} student{'s' if total_count != 1 else ''} have been placed at {company}."
        if breakdown:
            summary += f"\n\nPositions:\n{breakdown}"

        # Add time sent if available
        time_sent = event.time_sent or offer_data.time_sent
        if time_sent:
            summary += f"\n\n📅 Sent: {time_sent}"

        summary += "\n\nCongratulations to all selected!"

        # Use email sender as author if available
        author = event.email_sender or "PlacementBot"

        return NoticeDocument(
            id=notice_id,
            title=f"Placement Update: {company}",
            content=summary,
            author=author,
            type="placement_update",
            source="Placement Offer Service",
            placement_offer_ref=offer_id,
            formatted_message=summary,
            createdAt=int(ts * 1000),
            updatedAt=int(ts * 1000),
            sent_to_telegram=False,
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

        ts = datetime.utcnow().timestamp()
        safe_company = company.replace(" ", "_") or "unknown_company"
        notice_id = f"placement_update_{safe_company}_{int(ts)}"

        breakdown, _ = self._build_role_breakdown(
            newly_added_students, roles, prefix="new "
        )

        # Build summary
        summary = f"🔄 **Placement Update: {company}**\n\n"
        summary += f"{new_count} more student{'s have' if new_count != 1 else ' has'} been placed at {company}!"
        summary += f"\n\nTotal placements at {company}: {total_students}"
        if breakdown:
            summary += f"\n\nNew positions:\n{breakdown}"
        summary += "\n\nCongratulations to the newly selected!"

        # Use email sender as author if available
        author = event.email_sender or "PlacementBot"

        return NoticeDocument(
            id=notice_id,
            title=f"Placement Update: {company} (+{new_count})",
            content=summary,
            author=author,
            type="placement_update",
            source="Placement Offer Service",
            placement_offer_ref=offer_id,
            formatted_message=summary,
            createdAt=int(ts * 1000),
            updatedAt=int(ts * 1000),
            sent_to_telegram=False,
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
        events: List[dict],
        save_to_db: bool = True,
    ) -> List[NoticeDocument]:
        """
        Process multiple placement events, format them, and optionally save.

        Args:
            events: List of events from database service
            save_to_db: Whether to save notices to database

        Returns:
            List of NoticeDocument objects
        """
        notices: List[NoticeDocument] = []

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
                self.logger.error(f"Error processing event: {e}")
                safe_print(f"Error processing placement event: {e}")

        return notices
