"""
Placement Stats Calculator Service

Provides comprehensive placement statistics calculation from placement offers data.
Translates React stats page logic into a modular Python service with DI support.

Features:
- Overall stats (unique students, total offers, avg/median/highest packages)
- Branch-wise statistics with enrollment range mapping
- Company-wise statistics
- Filtering capabilities (by company, role, location, package range)
"""

import logging
from typing import Dict, List, Any, Optional, Set, Tuple, TypedDict
from dataclasses import dataclass, field

from core.config import safe_print


# =============================================================================
# Configuration Constants (embedded as Python dicts per user request)
# =============================================================================

ENROLLMENT_RANGES: Dict[str, Dict[str, Dict[str, int]]] = {
    "CSE": {
        "62": {
            "start": 22103000,
            "end": 22104000,
        },
        "128": {
            "start": 9922103000,
            "end": 9922104000,
        },
    },
    "ECE": {
        "62": {
            "start": 22102000,
            "end": 22103000,
        },
        "128": {
            "start": 9922102000,
            "end": 9922103000,
        },
    },
    "IT": {
        "62": {
            "start": 22104000,
            "end": 22105000,
        },
    },
    "BT": {
        "62": {
            "start": 22101000,
            "end": 22102000,
        },
    },
    "Intg. MTech": {
        "CSE": {
            "start": 21803000,
            "end": 21804000,
        },
        "ECE": {
            "start": 21802000,
            "end": 21803000,
        },
        "BT": {
            "start": 21801000,
            "end": 21802000,
        },
    },
}

STUDENT_COUNTS: Dict[str, Dict[str, int]] = {
    "CSE": {
        "62": 342,
        "128": 270,
    },
    "ECE": {
        "62": 240,
        "128": 147,
    },
    "IT": {
        "62": 66,
    },
    "BT": {
        "62": 47,
    },
    "Intg. MTech": {
        "CSE": 28,
        "ECE": 3,
        "BT": 10,
    },
}

# Branches to exclude from most calculations
EXCLUDED_BRANCHES: Set[str] = {
    "JUIT",
    "Other",
    "MTech",
}


# =============================================================================
# Data Models
# =============================================================================


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


# =============================================================================
# Branch Range Builder and Resolver
# =============================================================================


def build_branch_ranges(
    config: Dict[str, Dict[str, Dict[str, int]]],
) -> List[BranchRange]:
    """
    Build flattened branch ranges from configuration.

    Args:
        config: Nested dict of branch -> batch/sub -> {start, end}

    Returns:
        Sorted list of BranchRange objects for efficient lookup
    """
    ranges: List[BranchRange] = []

    for branch, data in config.items():
        if branch == "Intg. MTech":
            # Nested per sub-branch
            for sub_branch, sub_data in data.items():
                if (
                    isinstance(sub_data, dict)
                    and "start" in sub_data
                    and "end" in sub_data
                ):
                    ranges.append(
                        BranchRange(
                            branch="Intg. MTech",
                            start=sub_data["start"],
                            end=sub_data["end"],
                        )
                    )
        elif isinstance(data, dict):
            # Regular branches with batch keys (e.g., "62", "128")
            for batch, batch_data in data.items():
                if (
                    isinstance(batch_data, dict)
                    and "start" in batch_data
                    and "end" in batch_data
                ):
                    ranges.append(
                        BranchRange(
                            branch=branch,
                            start=batch_data["start"],
                            end=batch_data["end"],
                        )
                    )

    # Sort by start for early exit optimization
    ranges.sort(key=lambda r: r.start)
    return ranges


# Pre-built ranges for efficient lookup
_BRANCH_RANGES: List[BranchRange] = build_branch_ranges(ENROLLMENT_RANGES)


def get_branch(enrollment: str) -> str:
    """
    Resolve branch from enrollment number.

    Logic:
    - If contains alpha characters or is 9-digit numeric -> "JUIT"
    - If starts with "24" -> "MTech"
    - Otherwise, match against configured ranges
    - Default: "Other"

    Args:
        enrollment: Enrollment number string

    Returns:
        Branch name
    """
    if not enrollment:
        return "Other"

    # Check for alpha characters -> JUIT
    has_alpha = any(c.isalpha() for c in enrollment)

    # Extract digits only
    digits = "".join(c for c in enrollment if c.isdigit())

    # Alpha chars present -> JUIT
    if has_alpha:
        return "JUIT"

    # MTech rule: first two digits are "24" (must check BEFORE 9-digit JUIT rule)
    if digits.startswith("24"):
        return "MTech"

    # JUIT rule: 9-digit numeric id
    if len(digits) == 9:
        return "JUIT"

    if not digits:
        return "Other"

    try:
        num = int(digits)
    except ValueError:
        return "Other"

    # Match against configured ranges
    for r in _BRANCH_RANGES:
        if r.start <= num < r.end:
            return r.branch

    return "Other"


# =============================================================================
# Package Calculation Utility
# =============================================================================


def to_float(val: Any) -> Optional[float]:
    """Safely convert value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_student_package(
    student: Dict[str, Any], placement: Dict[str, Any]
) -> Optional[float]:
    """
    Get the package for a student from placement data.

    Priority:
    1. Student's own package field
    2. Matching role's package
    3. Single role's package
    4. Max of all roles' packages

    Args:
        student: Student dict with optional 'package' and 'role' fields
        placement: Placement dict with 'roles' list

    Returns:
        Package in LPA or None
    """
    # Check student's direct package
    student_pkg = to_float(student.get("package"))
    if student_pkg is not None:
        return student_pkg

    roles = placement.get("roles") or []
    student_role = student.get("role")

    # Try to match exact role
    if student_role:
        for role in roles:
            if role.get("role") == student_role:
                role_pkg = to_float(role.get("package"))
                if role_pkg is not None:
                    return role_pkg

    # Get all viable packages from roles
    viable_pkgs = [to_float(r.get("package")) for r in roles]
    viable_pkgs = [p for p in viable_pkgs if p is not None]

    if len(viable_pkgs) == 1:
        return viable_pkgs[0]
    if len(viable_pkgs) > 1:
        return max(viable_pkgs)

    return None


def calculate_median(values: List[float]) -> float:
    """Calculate median of a list of values."""
    if not values:
        return 0.0

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    if n % 2 == 1:
        return sorted_vals[n // 2]
    else:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2


# =============================================================================
# Placement Stats Calculator Service
# =============================================================================


class PlacementStatsCalculatorService:
    """
    Service for calculating comprehensive placement statistics.

    Supports:
    - Overall statistics (unique students, packages, companies)
    - Branch-wise breakdowns with placement percentages
    - Company-wise aggregations
    - Filtering by company, role, location, package range
    """

    def __init__(
        self,
        db_service: Optional[Any] = None,
        enrollment_ranges: Optional[Dict] = None,
        student_counts: Optional[Dict] = None,
    ):
        """
        Initialize the stats calculator service.

        Args:
            db_service: Optional DatabaseService for fetching placements
            enrollment_ranges: Custom enrollment ranges (uses default if None)
            student_counts: Custom student counts (uses default if None)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        self.enrollment_ranges = enrollment_ranges or ENROLLMENT_RANGES
        self.student_counts = student_counts or STUDENT_COUNTS

        # Rebuild ranges if custom config provided
        if enrollment_ranges:
            self._branch_ranges = build_branch_ranges(enrollment_ranges)
        else:
            self._branch_ranges = _BRANCH_RANGES

        self.logger.info("PlacementStatsCalculatorService initialized")

    def _get_branch(self, enrollment: str) -> str:
        """Get branch for enrollment number using configured ranges."""
        if not enrollment:
            return "Other"

        has_alpha = any(c.isalpha() for c in enrollment)
        digits = "".join(c for c in enrollment if c.isdigit())

        if has_alpha or len(digits) == 9:
            return "JUIT"
        if digits.startswith("24"):
            return "MTech"
        if not digits:
            return "Other"

        try:
            num = int(digits)
        except ValueError:
            return "Other"

        for r in self._branch_ranges:
            if r.start <= num < r.end:
                return r.branch

        return "Other"

    def _flatten_students(
        self, placements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Flatten placements into a list of students with placement context.

        Each student dict will include:
        - Original student fields
        - company, roles, job_location, joining_date from placement
        - placement: reference to parent placement
        """
        students = []
        for placement in placements:
            for student in placement.get("students_selected", []):
                enriched = {
                    **student,
                    "company": placement.get("company"),
                    "roles": placement.get("roles", []),
                    "job_location": placement.get("job_location"),
                    "joining_date": placement.get("joining_date"),
                    "placement": placement,
                }
                students.append(enriched)
        return students

    def _filter_students(
        self,
        students: List[Dict[str, Any]],
        exclude_branches: bool = True,
        companies: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        package_range: Optional[Tuple[float, float]] = None,
        search_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter students based on various criteria.

        Args:
            students: List of enriched student dicts
            exclude_branches: Whether to exclude JUIT, Other, MTech branches
            companies: Filter by company names
            roles: Filter by role names
            locations: Filter by job locations
            package_range: Tuple of (min_lpa, max_lpa)
            search_query: Search in name, enrollment, role, company

        Returns:
            Filtered list of students
        """
        result = []

        for student in students:
            # Exclude branches filter
            if exclude_branches:
                branch = self._get_branch(student.get("enrollment_number", ""))
                if branch in EXCLUDED_BRANCHES:
                    continue

            # Search query filter
            if search_query:
                q = search_query.lower()
                searchable = [
                    str(student.get("name", "")).lower(),
                    str(student.get("enrollment_number", "")).lower(),
                    str(student.get("role", "")).lower(),
                    str(student.get("company", "")).lower(),
                ]
                if not any(q in s for s in searchable):
                    continue

            # Company filter
            if companies and student.get("company") not in companies:
                continue

            # Role filter
            if roles and student.get("role") not in roles:
                continue

            # Location filter
            if locations:
                student_locs = student.get("job_location") or []
                if not any(loc in student_locs for loc in locations):
                    continue

            # Package range filter
            if package_range:
                pkg = get_student_package(student, student.get("placement", {}))
                if pkg is not None:
                    min_pkg, max_pkg = package_range
                    if pkg < min_pkg or pkg > max_pkg:
                        continue

            result.append(student)

        return result

    def _get_branch_total_counts(self) -> Dict[str, int]:
        """
        Get total student counts per branch (excluding JUIT, Other, MTech).

        Returns:
            Dict mapping branch name to total students
        """
        totals: Dict[str, int] = {}

        for branch, counts in self.student_counts.items():
            if branch in EXCLUDED_BRANCHES:
                continue

            if isinstance(counts, dict):
                total = sum(int(c) for c in counts.values() if c)
            elif isinstance(counts, (int, float)):
                total = int(counts)
            else:
                continue

            totals[branch] = total

        return totals

    def _calculate_package_stats(
        self, students: List[Dict[str, Any]]
    ) -> Tuple[List[float], float, float, float]:
        """
        Calculate package statistics for a list of students.

        Uses highest package per unique student for calculations.

        Returns:
            Tuple of (all_packages, average, median, highest)
        """
        # Track highest package per unique student
        student_max_pkgs: Dict[str, float] = {}

        for student in students:
            enrollment = student.get("enrollment_number")
            if not enrollment:
                continue

            pkg = get_student_package(student, student.get("placement", {}))
            if pkg is not None and pkg > 0:
                current_max = student_max_pkgs.get(enrollment, 0)
                if pkg > current_max:
                    student_max_pkgs[enrollment] = pkg

        all_pkgs = list(student_max_pkgs.values())

        if not all_pkgs:
            return [], 0.0, 0.0, 0.0

        avg = sum(all_pkgs) / len(all_pkgs)
        median = calculate_median(all_pkgs)
        highest = max(all_pkgs)

        return all_pkgs, avg, median, highest

    def _calculate_branch_stats(
        self, students: List[Dict[str, Any]]
    ) -> Dict[str, BranchStats]:
        """
        Calculate statistics per branch.

        Args:
            students: List of enriched student dicts (already filtered)

        Returns:
            Dict mapping branch name to BranchStats
        """
        branch_totals = self._get_branch_total_counts()
        stats: Dict[str, BranchStats] = {}

        # Track unique enrollments and max packages per branch
        branch_enrollments: Dict[str, Set[str]] = {}
        branch_max_pkgs: Dict[str, Dict[str, float]] = {}

        for student in students:
            branch = self._get_branch(student.get("enrollment_number", ""))

            if branch not in stats:
                stats[branch] = BranchStats(
                    branch=branch, total_students_in_branch=branch_totals.get(branch, 0)
                )
                branch_enrollments[branch] = set()
                branch_max_pkgs[branch] = {}

            stats[branch].total_offers += 1

            enrollment = student.get("enrollment_number")
            if enrollment:
                branch_enrollments[branch].add(enrollment)

                pkg = get_student_package(student, student.get("placement", {}))
                if pkg is not None and pkg > 0:
                    current = branch_max_pkgs[branch].get(enrollment, 0)
                    if pkg > current:
                        branch_max_pkgs[branch][enrollment] = pkg

        # Calculate final stats for each branch
        for branch, branch_stat in stats.items():
            branch_stat.unique_students = len(branch_enrollments.get(branch, set()))
            branch_stat.packages = list(branch_max_pkgs.get(branch, {}).values())

            if branch_stat.packages:
                branch_stat.avg_package = sum(branch_stat.packages) / len(
                    branch_stat.packages
                )
                branch_stat.highest_package = max(branch_stat.packages)
                branch_stat.median_package = calculate_median(branch_stat.packages)

            if branch_stat.total_students_in_branch > 0:
                branch_stat.placement_percentage = (
                    branch_stat.unique_students / branch_stat.total_students_in_branch
                ) * 100

        return stats

    def _calculate_company_stats(
        self, students: List[Dict[str, Any]]
    ) -> Dict[str, CompanyStats]:
        """
        Calculate statistics per company.

        Args:
            students: List of enriched student dicts

        Returns:
            Dict mapping company name to CompanyStats
        """
        stats: Dict[str, CompanyStats] = {}

        for student in students:
            company = student.get("company", "Unknown")

            if company not in stats:
                stats[company] = CompanyStats(company=company)

            stats[company].students_count += 1

            # Collect profiles (roles)
            for role in student.get("roles", []):
                role_name = role.get("role")
                if role_name:
                    stats[company].profiles.add(role_name)

            # Collect packages
            pkg = get_student_package(student, student.get("placement", {}))
            if pkg is not None and pkg > 0:
                stats[company].packages.append(pkg)

        # Calculate averages
        for company_stat in stats.values():
            if company_stat.packages:
                company_stat.avg_package = sum(company_stat.packages) / len(
                    company_stat.packages
                )

        return stats

    def _extract_filter_options(
        self, placements: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """
        Extract available filter options from placements.

        Returns:
            Dict with companies, roles, locations lists
        """
        companies: Set[str] = set()
        roles: Set[str] = set()
        locations: Set[str] = set()

        for placement in placements:
            if placement.get("company"):
                companies.add(placement["company"])

            for role in placement.get("roles", []):
                if role.get("role"):
                    roles.add(role["role"])

            for loc in placement.get("job_location", []) or []:
                if loc:
                    locations.add(loc)

        return {
            "companies": sorted(companies),
            "roles": sorted(roles),
            "locations": sorted(locations),
        }

    def calculate_all_stats(
        self, placements: Optional[List[Dict[str, Any]]] = None
    ) -> PlacementStats:
        """
        Calculate comprehensive placement statistics.

        Args:
            placements: List of placement dicts. If None, fetches from db_service.

        Returns:
            PlacementStats with all calculated metrics
        """
        # Get placements from DB if not provided
        if placements is None:
            if self.db_service is None:
                safe_print("No placements provided and no db_service available")
                return PlacementStats()
            placements = self.db_service.get_all_offers(limit=1000)

        if not placements:
            return PlacementStats(
                unique_students_placed=0,
                total_offers=0,
                unique_companies=0,
                average_package=0.0,
                median_package=0.0,
                highest_package=0.0,
                placement_percentage=0.0,
                total_eligible_students=0,
                branch_stats={},
                company_stats={},
                available_filters={"companies": [], "roles": [], "locations": []},
            )

        # Flatten students and filter out excluded branches
        all_students = self._flatten_students(placements)
        included_students = self._filter_students(all_students, exclude_branches=True)

        # Calculate unique students
        unique_enrollments: Set[str] = set()
        for s in included_students:
            if s.get("enrollment_number"):
                unique_enrollments.add(s["enrollment_number"])

        unique_students_placed = len(unique_enrollments)
        total_offers = len(included_students)

        # Unique companies (from all students including excluded)
        unique_companies = len(set(s.get("company") for s in all_students))

        # Package calculations
        _, avg_pkg, median_pkg, highest_pkg = self._calculate_package_stats(
            included_students
        )

        # Branch stats
        branch_stats = self._calculate_branch_stats(included_students)
        branch_totals = self._get_branch_total_counts()

        # Overall placement percentage (only for tracked branches)
        total_eligible = sum(branch_totals.values())

        # Count placed students in tracked branches only
        placed_in_tracked = 0
        tracked_branches = set(branch_totals.keys())
        for s in included_students:
            branch = self._get_branch(s.get("enrollment_number", ""))
            if branch in tracked_branches and s.get("enrollment_number"):
                placed_in_tracked += 1

        # Use unique count for placement percentage
        unique_in_tracked: Set[str] = set()
        for s in included_students:
            branch = self._get_branch(s.get("enrollment_number", ""))
            if branch in tracked_branches and s.get("enrollment_number"):
                unique_in_tracked.add(s["enrollment_number"])

        placement_pct = (
            (len(unique_in_tracked) / total_eligible * 100) if total_eligible else 0.0
        )

        # Company stats
        company_stats = self._calculate_company_stats(all_students)

        # Convert to serializable dicts
        branch_stats_dict = {
            k: {
                "branch": v.branch,
                "total_offers": v.total_offers,
                "unique_students": v.unique_students,
                "total_students_in_branch": v.total_students_in_branch,
                "avg_package": round(v.avg_package, 2),
                "median_package": round(v.median_package, 2),
                "highest_package": round(v.highest_package, 2),
                "placement_percentage": round(v.placement_percentage, 2),
            }
            for k, v in branch_stats.items()
        }

        company_stats_dict = {
            k: {
                "company": v.company,
                "students_count": v.students_count,
                "profiles": sorted(v.profiles),
                "avg_package": round(v.avg_package, 2),
            }
            for k, v in company_stats.items()
        }

        return PlacementStats(
            unique_students_placed=unique_students_placed,
            total_offers=total_offers,
            unique_companies=unique_companies,
            average_package=round(avg_pkg, 2),
            median_package=round(median_pkg, 2),
            highest_package=round(highest_pkg, 2),
            placement_percentage=round(placement_pct, 2),
            total_eligible_students=total_eligible,
            branch_stats=branch_stats_dict,
            company_stats=company_stats_dict,
            available_filters=self._extract_filter_options(placements),
        )

    def calculate_filtered_stats(
        self,
        placements: List[Dict[str, Any]],
        companies: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        package_range: Optional[Tuple[float, float]] = None,
        search_query: Optional[str] = None,
    ) -> PlacementStats:
        """
        Calculate statistics with filters applied.

        Args:
            placements: List of placement dicts
            companies: Filter by company names
            roles: Filter by role names
            locations: Filter by job locations
            package_range: Tuple of (min_lpa, max_lpa)
            search_query: Search string for name/enrollment/role/company

        Returns:
            PlacementStats for filtered data
        """
        all_students = self._flatten_students(placements)

        # Apply filters
        filtered = self._filter_students(
            students=all_students,
            exclude_branches=True,
            companies=companies,
            roles=roles,
            locations=locations,
            package_range=package_range,
            search_query=search_query,
        )

        # Calculate unique students
        unique_enrollments: Set[str] = set()
        for s in filtered:
            if s.get("enrollment_number"):
                unique_enrollments.add(s["enrollment_number"])

        # Package stats
        _, avg_pkg, median_pkg, highest_pkg = self._calculate_package_stats(filtered)

        # Branch stats
        branch_stats = self._calculate_branch_stats(filtered)
        branch_totals = self._get_branch_total_counts()
        total_eligible = sum(branch_totals.values())

        # Unique companies in filtered
        unique_companies = len(set(s.get("company") for s in filtered))

        # Placement percentage
        tracked_branches = set(branch_totals.keys())
        unique_in_tracked: Set[str] = set()
        for s in filtered:
            branch = self._get_branch(s.get("enrollment_number", ""))
            if branch in tracked_branches and s.get("enrollment_number"):
                unique_in_tracked.add(s["enrollment_number"])

        placement_pct = (
            (len(unique_in_tracked) / total_eligible * 100) if total_eligible else 0.0
        )

        # Company stats
        company_stats = self._calculate_company_stats(filtered)

        # Convert to serializable dicts
        branch_stats_dict = {
            k: {
                "branch": v.branch,
                "total_offers": v.total_offers,
                "unique_students": v.unique_students,
                "total_students_in_branch": v.total_students_in_branch,
                "avg_package": round(v.avg_package, 2),
                "median_package": round(v.median_package, 2),
                "highest_package": round(v.highest_package, 2),
                "placement_percentage": round(v.placement_percentage, 2),
            }
            for k, v in branch_stats.items()
        }

        company_stats_dict = {
            k: {
                "company": v.company,
                "students_count": v.students_count,
                "profiles": sorted(v.profiles),
                "avg_package": round(v.avg_package, 2),
            }
            for k, v in company_stats.items()
        }

        return PlacementStats(
            unique_students_placed=len(unique_enrollments),
            total_offers=len(filtered),
            unique_companies=unique_companies,
            average_package=round(avg_pkg, 2),
            median_package=round(median_pkg, 2),
            highest_package=round(highest_pkg, 2),
            placement_percentage=round(placement_pct, 2),
            total_eligible_students=total_eligible,
            branch_stats=branch_stats_dict,
            company_stats=company_stats_dict,
            available_filters=self._extract_filter_options(placements),
        )

    def get_students_by_branch(
        self,
        placements: List[Dict[str, Any]],
        branch: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all students for a specific branch.

        Args:
            placements: List of placement dicts
            branch: Branch name to filter by

        Returns:
            List of enriched student dicts
        """
        all_students = self._flatten_students(placements)
        return [
            s
            for s in all_students
            if self._get_branch(s.get("enrollment_number", "")) == branch
        ]

    def get_students_by_company(
        self,
        placements: List[Dict[str, Any]],
        company: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all students for a specific company.

        Args:
            placements: List of placement dicts
            company: Company name to filter by

        Returns:
            List of enriched student dicts
        """
        all_students = self._flatten_students(placements)
        return [s for s in all_students if s.get("company") == company]

    def export_to_csv_data(
        self,
        placements: List[Dict[str, Any]],
        filtered: bool = False,
        **filter_kwargs,
    ) -> List[List[str]]:
        """
        Generate CSV-ready data rows.

        Args:
            placements: List of placement dicts
            filtered: Whether to apply filters
            **filter_kwargs: Filter arguments if filtered=True

        Returns:
            List of rows, first row is headers
        """
        all_students = self._flatten_students(placements)

        if filtered:
            students = self._filter_students(
                all_students, exclude_branches=True, **filter_kwargs
            )
        else:
            students = self._filter_students(all_students, exclude_branches=True)

        rows = [
            [
                "Student Name",
                "Enrollment Number",
                "Company",
                "Role",
                "Package (LPA)",
                "Job Location",
                "Joining Date",
            ]
        ]

        for s in sorted(students, key=lambda x: x.get("name", "")):
            pkg = get_student_package(s, s.get("placement", {}))
            pkg_str = f"₹{pkg:.1f} LPA" if pkg else "TBD"
            locations = ", ".join(s.get("job_location") or []) or "N/A"

            rows.append(
                [
                    s.get("name", ""),
                    s.get("enrollment_number", ""),
                    s.get("company", ""),
                    s.get("role", "") or "N/A",
                    pkg_str,
                    locations,
                    s.get("joining_date", "") or "TBD",
                ]
            )

        return rows
