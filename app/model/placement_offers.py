"""Schemas for the PlacementOffers collection."""

from datetime import datetime
from typing import Any

from pydantic import Field

from model.base import MongoModel
from model.notices import MatchedJobSummary


class RolePackage(MongoModel):
    """Role and compensation details in a placement offer."""

    role: str
    package: float | None = None
    package_details: str | None = None


class PlacementStudent(MongoModel):
    """Student-level placement offer row."""

    name: str
    enrollment_number: str | None = None
    enrollment: str | None = None
    email: str | None = None
    role: str | None = None
    package: float | None = None
    location: str | None = None
    joining_date: str | None = None
    offer_received_at: datetime | None = None
    offerReceivedAt: int | None = None


class PlacementOfferDocument(MongoModel):
    """Placement offer/result stored in PlacementOffers."""

    company: str
    company_key: str | None = None
    roles: list[RolePackage] = Field(default_factory=list)
    job_location: list[str] | None = None
    joining_date: str | None = None
    students_selected: list[PlacementStudent] = Field(default_factory=list)
    number_of_offers: int = 0
    additional_info: str | None = None

    email_subject: str | None = None
    email_sender: str | None = None
    time_sent: str | None = None

    createdAt: int | None = None
    created_at: datetime | None = None
    saved_at: datetime | None = None
    updated_at: datetime | None = None

    matched_job_id: str | None = None
    related_job_id: str | None = None
    matched_job: MatchedJobSummary | None = None
    likely_on_campus: bool = False
    on_campus_confidence: float | None = Field(default=None, ge=0, le=1)
    # Why the judge decided, kept so a wrong tag can be traced and corrected.
    on_campus_reason: str | None = None
    on_campus_signals: list[str] = Field(default_factory=list)
    on_campus_job_id: str | None = None
    on_campus_ppo: bool | None = None
    on_campus_model: str | None = None
    # Raw model reasoning from the backfill gateway, trimmed. Absent otherwise.
    on_campus_reasoning: str | None = None

    details: dict[str, Any] = Field(default_factory=dict)
