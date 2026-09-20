"""Data models for placement statistics."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, TypedDict


@dataclass
class BranchRange:
    """Enrollment number range for a branch."""

    branch: str
    start: int
    end: int


@dataclass
class BranchStats:
    """Statistics for a single branch."""

    branch: str
    total_offers: int = 0
    unique_students: int = 0
    total_students_in_branch: int = 0
    packages: List[float] = field(default_factory=list)
    avg_package: float = 0.0
    highest_package: float = 0.0
    median_package: float = 0.0
    placement_percentage: float = 0.0


@dataclass
class CompanyStats:
    """Statistics for a single company."""

    company: str
    students_count: int = 0
    profiles: Set[str] = field(default_factory=set)
    packages: List[float] = field(default_factory=list)
    avg_package: float = 0.0


class PlacementStats(TypedDict, total=False):
    """Overall placement statistics result."""

    unique_students_placed: int
    total_offers: int
    unique_companies: int
    average_package: float
    median_package: float
    highest_package: float
    placement_percentage: float
    total_eligible_students: int
    branch_stats: Dict[str, Dict[str, Any]]
    company_stats: Dict[str, Dict[str, Any]]
    available_filters: Dict[str, List[str]]
