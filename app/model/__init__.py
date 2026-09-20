"""Mongo collection schemas used by the placement alerts app."""

from model.jobs import EligibilityMark, JobDocument, JobDocumentAttachment
from model.notices import MatchedJobSummary, NoticeDocument, StudentNoticeRow
from model.official_placement import (
    BatchInfo,
    OfficialPlacementBatchDocument,
    OfficialPlacementDataDocument,
    PackageDistribution,
    PlacementHighlight,
    RecruiterLogo,
)
from model.placement_offers import (
    PlacementOfferDocument,
    PlacementStudent,
    RolePackage,
)
from model.placement_years import PlacementYearDocument
from model.policies import PolicyDocument, PolicySource, TOCItem
from model.users import UserDocument

__all__ = [
    "BatchInfo",
    "EligibilityMark",
    "JobDocument",
    "JobDocumentAttachment",
    "MatchedJobSummary",
    "NoticeDocument",
    "OfficialPlacementBatchDocument",
    "OfficialPlacementDataDocument",
    "PackageDistribution",
    "PlacementHighlight",
    "PlacementOfferDocument",
    "PlacementStudent",
    "PlacementYearDocument",
    "PolicyDocument",
    "PolicySource",
    "RecruiterLogo",
    "RolePackage",
    "StudentNoticeRow",
    "TOCItem",
    "UserDocument",
]
