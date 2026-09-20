"""Schemas for the Jobs collection."""

from datetime import datetime

from pydantic import Field

from model.base import MongoModel


class EligibilityMark(MongoModel):
    """Academic eligibility threshold for a job profile."""

    level: str
    criteria: float


class JobDocumentAttachment(MongoModel):
    """Document attached to a SuperSet job profile."""

    name: str
    identifier: str
    url: str | None = None


class JobDocument(MongoModel):
    """Structured SuperSet job profile stored in Jobs."""

    id: str = Field(..., description="SuperSet job profile identifier")
    job_profile: str
    company: str
    placement_category_code: int = 0
    placement_category: str = "Unknown"
    content: str = ""
    createdAt: int | None = None
    deadline: int | None = None
    eligibility_marks: list[EligibilityMark] = Field(default_factory=list)
    eligibility_courses: list[str] = Field(default_factory=list)
    allowed_genders: list[str] = Field(default_factory=list)
    job_description: str = ""
    location: str = "Unknown"
    package: float = 0
    annum_months: str | None = None
    package_info: str = ""
    required_skills: list[str] = Field(default_factory=list)
    hiring_flow: list[str] = Field(default_factory=list)
    placement_type: str | None = None
    documents: list[JobDocumentAttachment] = Field(default_factory=list)
    saved_at: datetime | None = None
    updated_at: datetime | None = None
