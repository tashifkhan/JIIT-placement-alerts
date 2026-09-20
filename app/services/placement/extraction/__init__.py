"""Placement extraction service package."""

from services.placement.extraction.constants import (
    COMPANY_INDICATORS,
    NEGATIVE_KEYWORDS,
    PLACEMENT_KEYWORDS,
)
from services.placement.extraction.email_utils import (
    extract_forwarded_date,
    extract_forwarded_sender,
    extract_json_from_response,
    strip_headers_and_forwarded_markers,
)
from services.placement.extraction.models import (
    GraphState,
    PlacementOffer,
    RolePackage,
    Student,
)
from services.placement.extraction.prompts import EXTRACTION_PROMPT
from services.placement.extraction.service import PlacementService

__all__ = [
    "COMPANY_INDICATORS",
    "EXTRACTION_PROMPT",
    "GraphState",
    "NEGATIVE_KEYWORDS",
    "PLACEMENT_KEYWORDS",
    "PlacementOffer",
    "PlacementService",
    "RolePackage",
    "Student",
    "extract_forwarded_date",
    "extract_forwarded_sender",
    "extract_json_from_response",
    "strip_headers_and_forwarded_markers",
]
