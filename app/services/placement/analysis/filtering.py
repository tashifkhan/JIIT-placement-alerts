"""Filtering helpers for placement statistics."""

from typing import Any

from services.placement.analysis.config import EXCLUDED_BRANCHES
from services.placement.analysis.helpers import get_student_package


class PlacementStatsFilteringMixin:
    """Student flattening and filtering behavior."""

    def _flatten_students(
        self, placements: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Flatten placements into students with placement context.

        Each student dict includes original student fields, company, roles,
        job_location, joining_date, and a reference to the parent placement.
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
        students: list[dict[str, Any]],
        exclude_branches: bool = True,
        companies: list[str] | None = None,
        roles: list[str] | None = None,
        locations: list[str] | None = None,
        package_range: tuple[float, float] | None = None,
        search_query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter students by branch, company, role, location, package, and search."""
        result = []

        for student in students:
            if exclude_branches:
                branch = self._get_branch(student.get("enrollment_number", ""))
                if branch in EXCLUDED_BRANCHES:
                    continue

            if search_query:
                query = search_query.lower()
                searchable = [
                    str(student.get("name", "")).lower(),
                    str(student.get("enrollment_number", "")).lower(),
                    str(student.get("role", "")).lower(),
                    str(student.get("company", "")).lower(),
                ]
                if not any(query in value for value in searchable):
                    continue

            if companies and student.get("company") not in companies:
                continue

            if roles and student.get("role") not in roles:
                continue

            if locations:
                student_locations = student.get("job_location") or []
                if not any(location in student_locations for location in locations):
                    continue

            if package_range:
                package = get_student_package(student, student.get("placement", {}))
                if package is not None:
                    min_package, max_package = package_range
                    if package < min_package or package > max_package:
                        continue

            result.append(student)

        return result

    def _extract_filter_options(
        self, placements: list[dict[str, Any]]
    ) -> dict[str, list[str]]:
        """Extract available company, role, and location filters from placements."""
        companies: set[str] = set()
        roles: set[str] = set()
        locations: set[str] = set()

        for placement in placements:
            if placement.get("company"):
                companies.add(placement["company"])

            for role in placement.get("roles", []):
                if role.get("role"):
                    roles.add(role["role"])

            for location in placement.get("job_location", []) or []:
                if location:
                    locations.add(location)

        return {
            "companies": sorted(companies),
            "roles": sorted(roles),
            "locations": sorted(locations),
        }
