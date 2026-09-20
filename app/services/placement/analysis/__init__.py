"""Placement analysis and statistics package."""

from services.placement.analysis.config import (
    BATCH_CONFIGS,
    DEFAULT_PLACEMENT_YEAR,
    ENROLLMENT_RANGES,
    EXCLUDED_BRANCHES,
    STUDENT_COUNTS,
    get_batch_config,
    get_branch_totals_for_year,
    get_branches_for_year,
    get_enrollment_ranges_for_year,
    get_excluded_branches_for_year,
    get_student_counts_for_year,
    get_total_students_for_year,
    normalize_batch_year,
)
from services.placement.analysis.helpers import (
    _BRANCH_RANGES,
    build_branch_ranges,
    calculate_median,
    get_branch,
    get_branch_for_year,
    get_branch_ranges_for_year,
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
    "BATCH_CONFIGS",
    "DEFAULT_PLACEMENT_YEAR",
    "ENROLLMENT_RANGES",
    "EXCLUDED_BRANCHES",
    "STUDENT_COUNTS",
    "_BRANCH_RANGES",
    "BranchRange",
    "BranchStats",
    "CompanyStats",
    "PlacementStats",
    "PlacementStatsCalculatorService",
    "build_branch_ranges",
    "calculate_median",
    "get_batch_config",
    "get_branch",
    "get_branch_for_year",
    "get_branch_ranges_for_year",
    "get_branch_totals_for_year",
    "get_branches_for_year",
    "get_enrollment_ranges_for_year",
    "get_excluded_branches_for_year",
    "get_student_counts_for_year",
    "get_student_package",
    "get_total_students_for_year",
    "normalize_batch_year",
    "to_float",
]
