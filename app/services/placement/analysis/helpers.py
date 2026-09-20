"""Helper functions for placement statistics."""

from typing import Any, Dict, List, Optional

from services.placement.analysis.config import ENROLLMENT_RANGES
from services.placement.analysis.models import BranchRange


def build_branch_ranges(
    config: Dict[str, Dict[str, Dict[str, int]]],
) -> List[BranchRange]:
    """
    Build flattened branch ranges from configuration.

    Args:
        config: Nested dict of branch -> batch/sub -> {start, end}.

    Returns:
        Sorted list of BranchRange objects for efficient lookup.
    """
    ranges: List[BranchRange] = []

    for branch, data in config.items():
        if branch == "Intg. MTech":
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

    ranges.sort(key=lambda branch_range: branch_range.start)
    return ranges


_BRANCH_RANGES: List[BranchRange] = build_branch_ranges(ENROLLMENT_RANGES)


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


def to_float(val: Any) -> Optional[float]:
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
    student: Dict[str, Any], placement: Dict[str, Any]
) -> Optional[float]:
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


def calculate_median(values: List[float]) -> float:
    """Calculate median of a list of values."""
    if not values:
        return 0.0

    sorted_values = sorted(values)
    count = len(sorted_values)

    if count % 2 == 1:
        return sorted_values[count // 2]
    return (sorted_values[count // 2 - 1] + sorted_values[count // 2]) / 2
