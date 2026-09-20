"""Placement statistics calculator service."""

import logging
from typing import Any

from core.config import safe_print
from services.placement.analysis.aggregations import PlacementStatsAggregationMixin
from services.placement.analysis.config import (
    get_enrollment_ranges_for_year,
    get_student_counts_for_year,
    normalize_batch_year,
)
from services.placement.analysis.filtering import PlacementStatsFilteringMixin
from services.placement.analysis.helpers import (
    build_branch_ranges,
    get_branch_ranges_for_year,
    get_student_package,
)
from services.placement.analysis.models import PlacementStats
from services.placement.analysis.serializers import (
    serialize_branch_stats,
    serialize_company_stats,
)


class PlacementStatsCalculatorService(
    PlacementStatsFilteringMixin,
    PlacementStatsAggregationMixin,
):
    """
    Service for calculating comprehensive placement statistics.

    Supports overall statistics, branch-wise breakdowns, company-wise
    aggregations, and filtering by company, role, location, and package range.
    """

    def __init__(
        self,
        db_service: Any | None = None,
        enrollment_ranges: dict | None = None,
        student_counts: dict | None = None,
        placement_year: str | None = None,
    ):
        """
        Initialize the stats calculator service.

        Args:
            db_service: Optional DatabaseService for fetching placements.
            enrollment_ranges: Custom enrollment ranges (overrides per-year config).
            student_counts: Custom student counts (overrides per-year config).
            placement_year: Placement year selecting the batch config
                (e.g. "202526", "202627"). Defaults to the configured batch.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        self.placement_year = normalize_batch_year(placement_year)
        self.enrollment_ranges = (
            enrollment_ranges or get_enrollment_ranges_for_year(self.placement_year)
        )
        self.student_counts = (
            student_counts or get_student_counts_for_year(self.placement_year)
        )

        if enrollment_ranges:
            self._branch_ranges = build_branch_ranges(enrollment_ranges)
        else:
            self._branch_ranges = get_branch_ranges_for_year(self.placement_year)

        self.logger.info("PlacementStatsCalculatorService initialized")

    def _get_branch(self, enrollment: str) -> str:
        """Get branch for enrollment number using configured ranges."""
        if not enrollment:
            return "Other"

        has_alpha = any(char.isalpha() for char in enrollment)
        digits = "".join(char for char in enrollment if char.isdigit())

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

        for branch_range in self._branch_ranges:
            if branch_range.start <= num < branch_range.end:
                return branch_range.branch

        return "Other"

    def calculate_all_stats(
        self, placements: list[dict[str, Any]] | None = None
    ) -> PlacementStats:
        """
        Calculate comprehensive placement statistics.

        Args:
            placements: Placement dicts. If None, fetches from db_service.

        Returns:
            PlacementStats with all calculated metrics.
        """
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

        all_students = self._flatten_students(placements)
        included_students = self._filter_students(all_students, exclude_branches=True)

        unique_enrollments: set[str] = set()
        for student in included_students:
            if student.get("enrollment_number"):
                unique_enrollments.add(student["enrollment_number"])

        unique_students_placed = len(unique_enrollments)
        total_offers = len(included_students)
        unique_companies = len({student.get("company") for student in all_students})

        _, avg_package, median_package, highest_package = self._calculate_package_stats(
            included_students
        )

        branch_stats = self._calculate_branch_stats(included_students)
        branch_totals = self._get_branch_total_counts()
        total_eligible = sum(branch_totals.values())

        tracked_branches = set(branch_totals.keys())
        unique_in_tracked: set[str] = set()
        for student in included_students:
            branch = self._get_branch(student.get("enrollment_number", ""))
            if branch in tracked_branches and student.get("enrollment_number"):
                unique_in_tracked.add(student["enrollment_number"])

        placement_percentage = (
            (len(unique_in_tracked) / total_eligible * 100) if total_eligible else 0.0
        )

        company_stats = self._calculate_company_stats(all_students)

        return PlacementStats(
            unique_students_placed=unique_students_placed,
            total_offers=total_offers,
            unique_companies=unique_companies,
            average_package=round(avg_package, 2),
            median_package=round(median_package, 2),
            highest_package=round(highest_package, 2),
            placement_percentage=round(placement_percentage, 2),
            total_eligible_students=total_eligible,
            branch_stats=serialize_branch_stats(branch_stats),
            company_stats=serialize_company_stats(company_stats),
            available_filters=self._extract_filter_options(placements),
        )

    def calculate_filtered_stats(
        self,
        placements: list[dict[str, Any]],
        companies: list[str] | None = None,
        roles: list[str] | None = None,
        locations: list[str] | None = None,
        package_range: tuple[float, float] | None = None,
        search_query: str | None = None,
    ) -> PlacementStats:
        """
        Calculate placement statistics with filters applied.

        Args:
            placements: Placement dicts.
            companies: Company names to include.
            roles: Role names to include.
            locations: Job locations to include.
            package_range: Tuple of (min_lpa, max_lpa).
            search_query: Search string for name/enrollment/role/company.

        Returns:
            PlacementStats for filtered data.
        """
        all_students = self._flatten_students(placements)
        filtered = self._filter_students(
            students=all_students,
            exclude_branches=True,
            companies=companies,
            roles=roles,
            locations=locations,
            package_range=package_range,
            search_query=search_query,
        )

        unique_enrollments: set[str] = set()
        for student in filtered:
            if student.get("enrollment_number"):
                unique_enrollments.add(student["enrollment_number"])

        _, avg_package, median_package, highest_package = self._calculate_package_stats(
            filtered
        )

        branch_stats = self._calculate_branch_stats(filtered)
        branch_totals = self._get_branch_total_counts()
        total_eligible = sum(branch_totals.values())

        unique_companies = len({student.get("company") for student in filtered})

        tracked_branches = set(branch_totals.keys())
        unique_in_tracked: set[str] = set()
        for student in filtered:
            branch = self._get_branch(student.get("enrollment_number", ""))
            if branch in tracked_branches and student.get("enrollment_number"):
                unique_in_tracked.add(student["enrollment_number"])

        placement_percentage = (
            (len(unique_in_tracked) / total_eligible * 100) if total_eligible else 0.0
        )

        company_stats = self._calculate_company_stats(filtered)

        return PlacementStats(
            unique_students_placed=len(unique_enrollments),
            total_offers=len(filtered),
            unique_companies=unique_companies,
            average_package=round(avg_package, 2),
            median_package=round(median_package, 2),
            highest_package=round(highest_package, 2),
            placement_percentage=round(placement_percentage, 2),
            total_eligible_students=total_eligible,
            branch_stats=serialize_branch_stats(branch_stats),
            company_stats=serialize_company_stats(company_stats),
            available_filters=self._extract_filter_options(placements),
        )

    def get_students_by_branch(
        self,
        placements: list[dict[str, Any]],
        branch: str,
    ) -> list[dict[str, Any]]:
        """Get all students for a specific branch."""
        all_students = self._flatten_students(placements)
        return [
            student
            for student in all_students
            if self._get_branch(student.get("enrollment_number", "")) == branch
        ]

    def get_students_by_company(
        self,
        placements: list[dict[str, Any]],
        company: str,
    ) -> list[dict[str, Any]]:
        """Get all students for a specific company."""
        all_students = self._flatten_students(placements)
        return [student for student in all_students if student.get("company") == company]

    def export_to_csv_data(
        self,
        placements: list[dict[str, Any]],
        filtered: bool = False,
        **filter_kwargs,
    ) -> list[list[str]]:
        """Generate CSV-ready rows with a header row."""
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
                "Offer Received At",
            ]
        ]

        for student in sorted(students, key=lambda item: item.get("name", "")):
            package = get_student_package(student, student.get("placement", {}))
            package_text = f"₹{package:.1f} LPA" if package else "TBD"
            locations = ", ".join(student.get("job_location") or []) or "N/A"

            rows.append(
                [
                    student.get("name", ""),
                    student.get("enrollment_number", ""),
                    student.get("company", ""),
                    student.get("role", "") or "N/A",
                    package_text,
                    locations,
                    student.get("joining_date", "") or "TBD",
                    str(
                        student.get("offer_received_at")
                        or student.get("offerReceivedAt")
                        or "TBD"
                    ),
                ]
            )

        return rows
