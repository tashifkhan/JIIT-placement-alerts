"""Placement analysis and statistics package."""

from services.placement.analysis.config import (
    ENROLLMENT_RANGES,
    EXCLUDED_BRANCHES,
    STUDENT_COUNTS,
)
from services.placement.analysis.helpers import (
    _BRANCH_RANGES,
    build_branch_ranges,
    calculate_median,
    get_branch,
    get_student_package,
    to_float,
)
from services.placement.analysis.models import (
    BranchRange,
    BranchStats,
    CompanyStats,
    PlacementStats,
)
from services.placement.analysis.service import PlacementStatsCalculatorService

__all__ = [
    "BranchRange",
    "BranchStats",
    "CompanyStats",
    "ENROLLMENT_RANGES",
    "EXCLUDED_BRANCHES",
    "PlacementStats",
    "PlacementStatsCalculatorService",
    "STUDENT_COUNTS",
    "_BRANCH_RANGES",
    "build_branch_ranges",
    "calculate_median",
    "get_branch",
    "get_student_package",
    "to_float",
]
