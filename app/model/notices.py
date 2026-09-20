"""Schemas for the Notices collection."""

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from model.base import MongoModel


class StudentNoticeRow(MongoModel):
    """Student row used by shortlist and placement-offer notices."""

    name: str = "Unknown"
    enrollment: str | None = None
    enrollment_number: str | None = None
    company: str | None = None
    role: str | None = None
    package: Any | None = None
    location: str | None = None
    joining_date: str | None = None
    offer_received_at: datetime | None = None
    offerReceivedAt: int | None = None


class MatchedJobSummary(MongoModel):
    """Embedded summary of a related Jobs document."""

    id: str
    company: str | None = None
    job_profile: str | None = None
    location: str | None = None
    package: Any | None = None
    package_breakdown: str | None = None


class NoticeDocument(MongoModel):
    """Notice document stored in Notices."""

    id: str | None = Field(None, description="Source notice identifier")
    title: str = "Notice"
    content: str = ""
    author: str | None = None
    type: str = "announcement"
    source: str | None = None
    category: str = "announcement"
    year: str | None = None

    createdAt: int | None = None
    updatedAt: int | None = None
    saved_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    time_sent: str | None = None
    sent_to_telegram: bool = False
    delivery_status: dict[str, bool] = Field(default_factory=dict)
    delivery_timestamps: dict[str, datetime] = Field(default_factory=dict)

    details: dict[str, Any] = Field(default_factory=dict)
    deadline: str | None = None
    links: list[str] | None = None

    job_company: str | None = None
    job_role: str | None = None
    package: str | None = None
    package_breakdown: str | None = None
    location: str | None = None
    eligibility_criteria: list[str] | None = None
    hiring_flow: list[str] | None = None

    students: list[StudentNoticeRow] | None = None
    selected_students: list[StudentNoticeRow] = Field(default_factory=list)
    shortlisted_students: list[StudentNoticeRow] = Field(default_factory=list)
    students_count: int | None = None
    number_of_offers: int | None = None

    placement_offer_ref: str | None = None
    is_update: bool | None = None
    new_students_count: int | None = None

    matched_job_id: str | None = None
    related_job_id: str | None = None
    matched_job: MatchedJobSummary | None = None
    likely_on_campus: bool = False
    on_campus_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("selected_students", "shortlisted_students", mode="before")
    @classmethod
    def normalize_required_student_lists(cls, value: Any) -> Any:
        """Treat source nulls as empty lists for required student collections."""
        return [] if value is None else value
