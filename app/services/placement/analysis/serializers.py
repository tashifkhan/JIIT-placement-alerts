"""Serialization helpers for placement statistics."""


from services.placement.analysis.models import BranchStats, CompanyStats


def serialize_branch_stats(
    branch_stats: dict[str, BranchStats],
) -> dict[str, dict[str, object]]:
    """Convert BranchStats objects to serializable dictionaries."""
    return {
        key: {
            "branch": value.branch,
            "total_offers": value.total_offers,
            "unique_students": value.unique_students,
            "total_students_in_branch": value.total_students_in_branch,
            "avg_package": round(value.avg_package, 2),
            "median_package": round(value.median_package, 2),
            "highest_package": round(value.highest_package, 2),
            "placement_percentage": round(value.placement_percentage, 2),
        }
        for key, value in branch_stats.items()
    }


def serialize_company_stats(
    company_stats: dict[str, CompanyStats],
) -> dict[str, dict[str, object]]:
    """Convert CompanyStats objects to serializable dictionaries."""
    return {
        key: {
            "company": value.company,
            "students_count": value.students_count,
            "profiles": sorted(value.profiles),
            "avg_package": round(value.avg_package, 2),
        }
        for key, value in company_stats.items()
    }
