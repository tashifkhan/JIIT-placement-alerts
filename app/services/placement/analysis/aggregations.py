"""Aggregation helpers for placement statistics."""

from typing import Any, Dict, List, Set, Tuple

from services.placement.analysis.config import EXCLUDED_BRANCHES
from services.placement.analysis.helpers import calculate_median, get_student_package
from services.placement.analysis.models import BranchStats, CompanyStats


class PlacementStatsAggregationMixin:
    """Branch, company, and package aggregation behavior."""

    def _get_branch_total_counts(self) -> Dict[str, int]:
        """Get total student counts per branch excluding unsupported branches."""
        totals: Dict[str, int] = {}

        for branch, counts in self.student_counts.items():
            if branch in EXCLUDED_BRANCHES:
                continue

            if isinstance(counts, dict):
                total = sum(int(count) for count in counts.values() if count)
            elif isinstance(counts, (int, float)):
                total = int(counts)
            else:
                continue

            totals[branch] = total

        return totals

    def _calculate_package_stats(
        self, students: List[Dict[str, Any]]
    ) -> Tuple[List[float], float, float, float]:
        """Calculate package stats using highest package per unique student."""
        student_max_packages: Dict[str, float] = {}

        for student in students:
            enrollment = student.get("enrollment_number")
            if not enrollment:
                continue

            package = get_student_package(student, student.get("placement", {}))
            if package is not None and package > 0:
                current_max = student_max_packages.get(enrollment, 0)
                if package > current_max:
                    student_max_packages[enrollment] = package

        all_packages = list(student_max_packages.values())

        if not all_packages:
            return [], 0.0, 0.0, 0.0

        average = sum(all_packages) / len(all_packages)
        median = calculate_median(all_packages)
        highest = max(all_packages)

        return all_packages, average, median, highest

    def _calculate_branch_stats(
        self, students: List[Dict[str, Any]]
    ) -> Dict[str, BranchStats]:
        """Calculate placement statistics per branch."""
        branch_totals = self._get_branch_total_counts()
        stats: Dict[str, BranchStats] = {}
        branch_enrollments: Dict[str, Set[str]] = {}
        branch_max_packages: Dict[str, Dict[str, float]] = {}

        for student in students:
            branch = self._get_branch(student.get("enrollment_number", ""))

            if branch not in stats:
                stats[branch] = BranchStats(
                    branch=branch, total_students_in_branch=branch_totals.get(branch, 0)
                )
                branch_enrollments[branch] = set()
                branch_max_packages[branch] = {}

            stats[branch].total_offers += 1

            enrollment = student.get("enrollment_number")
            if enrollment:
                branch_enrollments[branch].add(enrollment)

                package = get_student_package(student, student.get("placement", {}))
                if package is not None and package > 0:
                    current = branch_max_packages[branch].get(enrollment, 0)
                    if package > current:
                        branch_max_packages[branch][enrollment] = package

        for branch, branch_stat in stats.items():
            branch_stat.unique_students = len(branch_enrollments.get(branch, set()))
            branch_stat.packages = list(branch_max_packages.get(branch, {}).values())

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
        """Calculate placement statistics per company."""
        stats: Dict[str, CompanyStats] = {}

        for student in students:
            company = student.get("company", "Unknown")

            if company not in stats:
                stats[company] = CompanyStats(company=company)

            stats[company].students_count += 1

            for role in student.get("roles", []):
                role_name = role.get("role")
                if role_name:
                    stats[company].profiles.add(role_name)

            package = get_student_package(student, student.get("placement", {}))
            if package is not None and package > 0:
                stats[company].packages.append(package)

        for company_stat in stats.values():
            if company_stat.packages:
                company_stat.avg_package = sum(company_stat.packages) / len(
                    company_stat.packages
                )

        return stats
