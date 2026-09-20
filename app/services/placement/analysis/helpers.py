"""Helper functions for placement statistics."""

from typing import Any

from services.placement.analysis.config import (
    ENROLLMENT_RANGES,
    get_enrollment_ranges_for_year,
    normalize_batch_year,
)
from services.placement.analysis.models import BranchRange


def build_branch_ranges(
    config: dict[str, dict[str, dict[str, int]]],
) -> list[BranchRange]:
    """
    Build flattened branch ranges from configuration.

    Args:
        config: Nested dict of branch -> batch/sub -> {start, end}.

    Returns:
        Sorted list of BranchRange objects for efficient lookup.
    """
    ranges: list[BranchRange] = []

    for branch, data in config.items():
        if branch == "Intg. MTech":
            for sub_data in data.values():
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
            for batch_data in data.values():
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

    ranges.sort(key=lambda branch_range: branch_range.start)
    return ranges


_BRANCH_RANGES: list[BranchRange] = build_branch_ranges(ENROLLMENT_RANGES)

_BRANCH_RANGES_BY_YEAR: dict[str, list[BranchRange]] = {}


def get_branch_ranges_for_year(year: str | None = None) -> list[BranchRange]:
    """
    Get cached branch ranges for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Sorted list of BranchRange objects for the year.
    """
    normalized = normalize_batch_year(year)
    cached = _BRANCH_RANGES_BY_YEAR.get(normalized)
    if cached is None:
        cached = build_branch_ranges(get_enrollment_ranges_for_year(normalized))
        _BRANCH_RANGES_BY_YEAR[normalized] = cached
    return cached


def get_branch_for_year(enrollment: str, year: str | None = None) -> str:
    """
    Resolve branch from enrollment number using a placement year's ranges.

    Logic:
    - If contains alpha characters or is 9-digit numeric -> "JUIT".
    - If starts with "24" -> "MTech".
    - Otherwise, match against the year's configured ranges.
    - Default: "Other".
    """
    if not enrollment:
        return "Other"

    has_alpha = any(char.isalpha() for char in enrollment)
    digits = "".join(char for char in enrollment if char.isdigit())

    if has_alpha:
        return "JUIT"

    if digits.startswith("24"):
        return "MTech"

    if len(digits) == 9:
        return "JUIT"

    if not digits:
        return "Other"

    try:
        num = int(digits)
    except ValueError:
        return "Other"

    for branch_range in get_branch_ranges_for_year(year):
        if branch_range.start <= num < branch_range.end:
            return branch_range.branch

    return "Other"


def get_branch(enrollment: str) -> str:
    """
    Resolve branch from enrollment number.

    Logic:
    - If contains alpha characters or is 9-digit numeric -> "JUIT".
    - If starts with "24" -> "MTech".
    - Otherwise, match against configured ranges.
    - Default: "Other".
    """
    if not enrollment:
        return "Other"

    has_alpha = any(char.isalpha() for char in enrollment)
    digits = "".join(char for char in enrollment if char.isdigit())

    if has_alpha:
        return "JUIT"

    if digits.startswith("24"):
        return "MTech"

    if len(digits) == 9:
        return "JUIT"

    if not digits:
        return "Other"

    try:
        num = int(digits)
    except ValueError:
        return "Other"

    for branch_range in _BRANCH_RANGES:
        if branch_range.start <= num < branch_range.end:
            return branch_range.branch

    return "Other"


def to_float(val: Any) -> float | None:
    """Convert package values to LPA while rejecting ambiguous large values."""
    if val is None:
        return None
    try:
        value = float(val)
        if value >= 100_000:
            return value / 100_000
        if value > 1_000:
            return None
        return value
    except (ValueError, TypeError):
        return None


def get_student_package(
    student: dict[str, Any], placement: dict[str, Any]
) -> float | None:
    """
    Get the package for a student from placement data.

    Priority:
    1. Student's own package field.
    2. Matching role's package.
    3. Single role's package.
    4. Max of all roles' packages.
    """
    student_pkg = to_float(student.get("package"))
    if student_pkg is not None:
        return student_pkg

    roles = placement.get("roles") or []
    student_role = student.get("role")

    if student_role:
        for role in roles:
            if role.get("role") == student_role:
                role_pkg = to_float(role.get("package"))
                if role_pkg is not None:
                    return role_pkg

    viable_pkgs = [to_float(role.get("package")) for role in roles]
    viable_pkgs = [package for package in viable_pkgs if package is not None]

    if len(viable_pkgs) == 1:
        return viable_pkgs[0]
    if len(viable_pkgs) > 1:
        return max(viable_pkgs)

    return None


def calculate_median(values: list[float]) -> float:
    """Calculate median of a list of values."""
    if not values:
        return 0.0

    sorted_values = sorted(values)
    count = len(sorted_values)

    if count % 2 == 1:
        return sorted_values[count // 2]
    return (sorted_values[count // 2 - 1] + sorted_values[count // 2]) / 2
