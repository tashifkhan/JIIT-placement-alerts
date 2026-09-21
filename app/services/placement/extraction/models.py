"""Models and graph state for placement offer extraction."""

from typing import TypedDict

from pydantic import BaseModel


class Student(BaseModel):
    """Student model for placement offers."""

    name: str
    enrollment_number: str | None = None
    email: str | None = None
    role: str | None = None
    package: float | None = None
    location: str | None = None
    joining_date: str | None = None
    offer_received_at: str | None = None
    offerReceivedAt: int | None = None


class RolePackage(BaseModel):
    """Role and package model."""

    role: str
    package: float | None = None
    package_details: str | None = None


class PlacementOffer(BaseModel):
    """Placement offer data model."""

    company: str
    roles: list[RolePackage]
    job_location: list[str] | None = None
    joining_date: str | None = None
    students_selected: list[Student]
    number_of_offers: int
    additional_info: str | None = None
    email_subject: str | None = None
    email_sender: str | None = None
    time_sent: str | None = None
    created_at: str | None = None
    createdAt: int | None = None
    likely_on_campus: bool = False
    on_campus_confidence: float | None = None


class GraphState(TypedDict):
    """LangGraph state for placement email processing."""

    email: dict[str, str]
    is_relevant: bool | None
    confidence_score: float | None
    classification_reason: str | None
    rejection_reason: str | None
    extracted_offer: PlacementOffer | None
    validation_errors: list[str] | None
    retry_count: int | None
