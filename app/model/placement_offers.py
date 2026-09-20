"""Schemas for the PlacementOffers collection."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from model.base import MongoModel
from model.notices import MatchedJobSummary


class RolePackage(MongoModel):
    """Role and compensation details in a placement offer."""

    role: str
    package: Optional[float] = None
    package_details: Optional[str] = None


class PlacementStudent(MongoModel):
    """Student-level placement offer row."""

    name: str
    enrollment_number: Optional[str] = None
    enrollment: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    package: Optional[float] = None
    location: Optional[str] = None
    joining_date: Optional[str] = None
    offer_received_at: Optional[datetime] = None
    offerReceivedAt: Optional[int] = None


class PlacementOfferDocument(MongoModel):
    """Placement offer/result stored in PlacementOffers."""

    company: str
    company_key: Optional[str] = None
    roles: List[RolePackage] = Field(default_factory=list)
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
    students_selected: List[PlacementStudent] = Field(default_factory=list)
    number_of_offers: int = 0
    additional_info: Optional[str] = None

    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    time_sent: Optional[str] = None

    createdAt: Optional[int] = None
    created_at: Optional[datetime] = None
    saved_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    matched_job_id: Optional[str] = None
    related_job_id: Optional[str] = None
    matched_job: Optional[MatchedJobSummary] = None

    details: Dict[str, Any] = Field(default_factory=dict)
