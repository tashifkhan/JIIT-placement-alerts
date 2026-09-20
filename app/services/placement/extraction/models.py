"""Models and graph state for placement offer extraction."""

from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel


class Student(BaseModel):
    """Student model for placement offers."""

    name: str
    enrollment_number: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    package: Optional[float] = None
    location: Optional[str] = None
    joining_date: Optional[str] = None
    offer_received_at: Optional[str] = None
    offerReceivedAt: Optional[int] = None


class RolePackage(BaseModel):
    """Role and package model."""

    role: str
    package: Optional[float] = None
    package_details: Optional[str] = None


class PlacementOffer(BaseModel):
    """Placement offer data model."""

    company: str
    roles: List[RolePackage]
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
    students_selected: List[Student]
    number_of_offers: int
    additional_info: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    time_sent: Optional[str] = None
    created_at: Optional[str] = None
    createdAt: Optional[int] = None


class GraphState(TypedDict):
    """LangGraph state for placement email processing."""

    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
    rejection_reason: Optional[str]
    extracted_offer: Optional[PlacementOffer]
    validation_errors: Optional[List[str]]
    retry_count: Optional[int]
