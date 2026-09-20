"""Schemas for the Notices collection."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from model.base import MongoModel


class StudentNoticeRow(MongoModel):
    """Student row used by shortlist and placement-offer notices."""

    name: str = "Unknown"
    enrollment: Optional[str] = None
    enrollment_number: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    package: Optional[Any] = None
    location: Optional[str] = None
    joining_date: Optional[str] = None
    offer_received_at: Optional[datetime] = None
    offerReceivedAt: Optional[int] = None


class MatchedJobSummary(MongoModel):
    """Embedded summary of a related Jobs document."""

    id: str
    company: Optional[str] = None
    job_profile: Optional[str] = None
    location: Optional[str] = None
    package: Optional[Any] = None
    package_breakdown: Optional[str] = None


class NoticeDocument(MongoModel):
    """Notice document stored in Notices."""

    id: Optional[str] = Field(None, description="Source notice identifier")
    title: str = "Notice"
    content: str = ""
    author: Optional[str] = None
    type: str = "announcement"
    source: Optional[str] = None
    category: str = "announcement"
    year: Optional[str] = None

    createdAt: Optional[int] = None
    updatedAt: Optional[int] = None
    saved_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    time_sent: Optional[str] = None
    sent_to_telegram: bool = False
    delivery_status: Dict[str, bool] = Field(default_factory=dict)
    delivery_timestamps: Dict[str, datetime] = Field(default_factory=dict)

    details: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[str] = None
    links: Optional[List[str]] = None

    job_company: Optional[str] = None
    job_role: Optional[str] = None
    package: Optional[str] = None
    package_breakdown: Optional[str] = None
    location: Optional[str] = None
    eligibility_criteria: Optional[List[str]] = None
    hiring_flow: Optional[List[str]] = None

    students: Optional[List[StudentNoticeRow]] = None
    selected_students: List[StudentNoticeRow] = Field(default_factory=list)
    shortlisted_students: List[StudentNoticeRow] = Field(default_factory=list)
    students_count: Optional[int] = None
    number_of_offers: Optional[int] = None

    placement_offer_ref: Optional[str] = None
    is_update: Optional[bool] = None
    new_students_count: Optional[int] = None

    matched_job_id: Optional[str] = None
    related_job_id: Optional[str] = None
    matched_job: Optional[MatchedJobSummary] = None

    @field_validator("selected_students", "shortlisted_students", mode="before")
    @classmethod
    def normalize_required_student_lists(cls, value: Any) -> Any:
        """Treat source nulls as empty lists for required student collections."""
        return [] if value is None else value
