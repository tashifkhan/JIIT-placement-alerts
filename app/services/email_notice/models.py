"""Models for email notice extraction."""

from typing import Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field

from model.notices import NoticeDocument
from services.placement_policy import ExtractedPolicyUpdate


class ExtractedNotice(BaseModel):
    """Structured notice data extracted from email."""

    is_notice: bool = Field(..., description="Whether this is a valid notice")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection")
    title: Optional[str] = Field(None, description="Notice title")
    content: Optional[str] = Field(None, description="Notice content")
    type: Optional[str] = Field(
        None,
        description="Notice type: announcement, hackathon, job_posting, shortlisting, update, webinar, reminder, internship_noc",
    )
    source: Optional[str] = Field(None, description="Source organization")
    deadline: Optional[str] = Field(None, description="Deadline if applicable")
    links: Optional[List[str]] = Field(None, description="Relevant URLs")
    additional_info: Optional[str] = Field(None, description="Other details")

    students: Optional[List[Dict[str, Optional[str]]]] = Field(
        None,
        description="List of students with name, enrollment, and optionally company",
    )
    company_name: Optional[str] = Field(
        None, description="Company name for shortlisting/job posting"
    )
    role: Optional[str] = Field(None, description="Job role/profile")
    total_shortlisted: Optional[int] = Field(
        None, description="Total number of shortlisted students"
    )
    round: Optional[str] = Field(None, description="Interview round name")
    interview_date: Optional[str] = Field(None, description="Interview date")
    venue: Optional[str] = Field(None, description="Interview/event venue")

    package: Optional[str] = Field(None, description="CTC/stipend")
    location: Optional[str] = Field(None, description="Job location")
    eligibility_criteria: Optional[List[str]] = Field(
        None, description="Eligibility requirements"
    )
    hiring_flow: Optional[List[str]] = Field(None, description="Selection process steps")
    job_type: Optional[str] = Field(None, description="Full-time or Internship")

    event_name: Optional[str] = Field(None, description="Event name")
    topic: Optional[str] = Field(None, description="Topic/theme")
    theme: Optional[str] = Field(None, description="Hackathon theme")
    speaker: Optional[str] = Field(None, description="Speaker name(s)")
    date: Optional[str] = Field(None, description="Event date")
    time: Optional[str] = Field(None, description="Event time")
    registration_link: Optional[str] = Field(None, description="Registration URL")

    start_date: Optional[str] = Field(None, description="Start date")
    end_date: Optional[str] = Field(None, description="End date")
    registration_deadline: Optional[str] = Field(
        None, description="Registration deadline"
    )
    prize_pool: Optional[str] = Field(None, description="Prize details")
    team_size: Optional[str] = Field(None, description="Team size requirements")
    organizer: Optional[str] = Field(None, description="Organizing body")


class NoticeGraphState(TypedDict):
    """LangGraph state for email notice processing."""

    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
    rejection_reason: Optional[str]
    extracted_notice: Optional[ExtractedNotice]
    validation_errors: Optional[List[str]]
    retry_count: Optional[int]
    extracted_policy: Optional[ExtractedPolicyUpdate]
    is_policy_update: Optional[bool]
