"""Models for email notice extraction."""

from typing import Any, TypedDict

from pydantic import BaseModel, Field

from model.notices import NoticeDocument
from services.placement_policy import ExtractedPolicyUpdate

__all__ = [
    "ExtractedNotice",
    "NoticeDocument",
    "NoticeGraphState",
]


class ExtractedNotice(BaseModel):
    """Structured notice data extracted from email."""

    is_notice: bool = Field(..., description="Whether this is a valid notice")
    rejection_reason: str | None = Field(None, description="Reason for rejection")
    title: str | None = Field(None, description="Notice title")
    content: str | None = Field(None, description="Notice content")
    type: str | None = Field(
        None,
        description="Notice type: announcement, hackathon, job_posting, shortlisting, update, webinar, reminder, internship_noc",
    )
    source: str | None = Field(None, description="Source organization")
    deadline: str | None = Field(None, description="Deadline if applicable")
    links: list[str] | None = Field(None, description="Relevant URLs")
    additional_info: str | None = Field(None, description="Other details")

    students: list[dict[str, str | None]] | None = Field(
        None,
        description="List of students with name, enrollment, and optionally company",
    )
    company_name: str | None = Field(
        None, description="Company name for shortlisting/job posting"
    )
    role: str | None = Field(None, description="Job role/profile")
    total_shortlisted: int | None = Field(
        None, description="Total number of shortlisted students"
    )
    round: str | None = Field(None, description="Interview round name")
    interview_date: str | None = Field(None, description="Interview date")
    venue: str | None = Field(None, description="Interview/event venue")

    package: str | None = Field(None, description="CTC/stipend")
    location: str | None = Field(None, description="Job location")
    eligibility_criteria: list[str] | None = Field(
        None, description="Eligibility requirements"
    )
    hiring_flow: list[str] | None = Field(None, description="Selection process steps")
    job_type: str | None = Field(None, description="Full-time or Internship")

    event_name: str | None = Field(None, description="Event name")
    topic: str | None = Field(None, description="Topic/theme")
    theme: str | None = Field(None, description="Hackathon theme")
    speaker: str | None = Field(None, description="Speaker name(s)")
    date: str | None = Field(None, description="Event date")
    time: str | None = Field(None, description="Event time")
    registration_link: str | None = Field(None, description="Registration URL")

    start_date: str | None = Field(None, description="Start date")
    end_date: str | None = Field(None, description="End date")
    registration_deadline: str | None = Field(
        None, description="Registration deadline"
    )
    prize_pool: str | None = Field(None, description="Prize details")
    team_size: str | None = Field(None, description="Team size requirements")
    organizer: str | None = Field(None, description="Organizing body")


class NoticeGraphState(TypedDict):
    """LangGraph state for email notice processing."""

    email: dict[str, str]
    is_relevant: bool | None
    confidence_score: float | None
    classification_reason: str | None
    rejection_reason: str | None
    extracted_notice: ExtractedNotice | None
    validation_errors: list[str] | None
    retry_count: int | None
    extracted_policy: ExtractedPolicyUpdate | None
    is_policy_update: bool | None
    job_candidates: list[dict[str, Any]]
    selected_job: dict[str, Any] | None
