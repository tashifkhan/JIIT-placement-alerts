"""Schemas for the Jobs collection."""

from datetime import datetime
from typing import List, Optional

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
    url: Optional[str] = None


class JobDocument(MongoModel):
    """Structured SuperSet job profile stored in Jobs."""

    id: str = Field(..., description="SuperSet job profile identifier")
    job_profile: str
    company: str
    placement_category_code: int = 0
    placement_category: str = "Unknown"
    content: str = ""
    createdAt: Optional[int] = None
    deadline: Optional[int] = None
    eligibility_marks: List[EligibilityMark] = Field(default_factory=list)
    eligibility_courses: List[str] = Field(default_factory=list)
    allowed_genders: List[str] = Field(default_factory=list)
    job_description: str = ""
    location: str = "Unknown"
    package: float = 0
    annum_months: Optional[str] = None
    package_info: str = ""
    required_skills: List[str] = Field(default_factory=list)
    hiring_flow: List[str] = Field(default_factory=list)
    placement_type: Optional[str] = None
    documents: List[JobDocumentAttachment] = Field(default_factory=list)
    saved_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
