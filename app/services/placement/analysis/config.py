"""Configuration constants for placement statistics.

Per-year batch configs live in ``BATCH_CONFIGS``, keyed by compact placement
year (``202526`` = AY 2025-26, graduating batch 2026). The legacy
``ENROLLMENT_RANGES`` / ``STUDENT_COUNTS`` aliases describe the default year
(202526) and are kept for backward compatibility.
"""

ENROLLMENT_RANGES: dict[str, dict[str, dict[str, int]]] = {
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

STUDENT_COUNTS: dict[str, dict[str, int]] = {
    "CSE": {
        "62": 354,
        "128": 268,
    },
    "ECE": {
        "62": 231,
        "128": 147,
    },
    "IT": {
        "62": 64,
    },
    "BT": {
        "62": 45,
    },
    "Intg. MTech": {
        "CSE": 28,
        "ECE": 3,
        "BT": 9,
    },
}

EXCLUDED_BRANCHES: set[str] = {
    "JUIT",
    "Other",
    "MTech",
}

DEFAULT_PLACEMENT_YEAR = "202526"

# Per-year batch config. student_counts is the single source for branch
# strength; per-branch totals and the year total are derived as sums.
# enrollment_ranges maps enrollment numbers -> branch.
BATCH_CONFIGS: dict[str, dict] = {
    "202526": {
        "label": "2025-26",
        "graduating_batch": "2026",
        "student_counts": {
            "CSE": {
                "62": 354,
                "128": 268,
            },
            "ECE": {
                "62": 231,
                "128": 147,
            },
            "IT": {
                "62": 64,
            },
            "BT": {
                "62": 45,
            },
            "Intg. MTech": {
                "CSE": 28,
                "ECE": 3,
                "BT": 9,
            },
        },
        "enrollment_ranges": {
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
                }
            },
            "BT": {
                "62": {
                    "start": 22101000,
                    "end": 22102000,
                }
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
        },
        "excluded_branches": ["JUIT", "Other", "MTech"],
    },
    "202627": {
        "label": "2026-27",
        "graduating_batch": "2027",
        "student_counts": {
            "CSE": {
                "62": 386,
                "128": 323,
            },
            "ECE": {
                "62": 217,
                "128": 108,
            },
            "EC-ACT": {
                "62": 52,
            },
            "EE-VLSI": {
                "62": 62,
            },
            "IT": {
                "62": 62,
            },
            "BT": {
                "62": 55,
            },
            "Intg. MTech": {
                "CSE": 31,
                "ECE": 15,
                "BT": 11,
            },
        },
        "enrollment_ranges": {
            "CSE": {
                "62": {
                    "start": 23103000,
                    "end": 23104000,
                },
                "128": {
                    "start": 9923103000,
                    "end": 9923104000,
                },
            },
            "ECE": {
                "62": {
                    "start": 23102000,
                    "end": 23103000,
                },
                "128": {
                    "start": 9923102000,
                    "end": 9923103000,
                },
            },
            "EC-ACT": {
                "62": {
                    "start": 23119000,
                    "end": 23120000,
                }
            },
            "EE-VLSI": {
                "62": {
                    "start": 23118000,
                    "end": 23119000,
                }
            },
            "IT": {
                "62": {
                    "start": 23104000,
                    "end": 23105000,
                }
            },
            "BT": {
                "62": {
                    "start": 23101000,
                    "end": 23102000,
                }
            },
            "Intg. MTech": {
                "CSE": {
                    "start": 22903000,
                    "end": 22904000,
                },
                "ECE": {
                    "start": 22802000,
                    "end": 22803000,
                },
                "BT": {
                    "start": 22801000,
                    "end": 22802000,
                },
            },
        },
        "excluded_branches": ["JUIT", "Other", "MTech"],
    },
}


def normalize_batch_year(year: str | None) -> str:
    """
    Normalize a placement year to compact YYYYYY format.

    Args:
        year: Year value such as 202526, 2025-26, or 2025_26.

    Returns:
        Normalized year string, falling back to the default year.
    """
    if not year:
        return DEFAULT_PLACEMENT_YEAR
    digits = "".join(char for char in str(year) if char.isdigit())

    if len(digits) == 6:
        return digits

    return DEFAULT_PLACEMENT_YEAR


def get_batch_config(year: str | None = None) -> dict:
    """
    Get the batch config for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Batch config dict for the year, falling back to the default year.
    """
    normalized = normalize_batch_year(year)
    config = BATCH_CONFIGS.get(normalized)

    if config is not None:
        return config

    return BATCH_CONFIGS[DEFAULT_PLACEMENT_YEAR]


def get_enrollment_ranges_for_year(
    year: str | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Get enrollment ranges for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Nested branch -> campus/sub -> {start, end} mapping.
    """
    return get_batch_config(year)["enrollment_ranges"]


def get_student_counts_for_year(
    year: str | None = None,
) -> dict[str, dict[str, int]]:
    """
    Get student counts for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Nested branch -> campus/sub -> count mapping.
    """
    return get_batch_config(year)["student_counts"]


def get_excluded_branches_for_year(year: str | None = None) -> set[str]:
    """
    Get excluded branches for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Set of branch names excluded from stats.
    """
    return set(get_batch_config(year).get("excluded_branches", EXCLUDED_BRANCHES))


def get_branch_totals_for_year(year: str | None = None) -> dict[str, int]:
    """
    Get total student counts per branch for a placement year.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Mapping of branch -> total students (excluded branches omitted).
    """
    counts = get_student_counts_for_year(year)
    excluded = get_excluded_branches_for_year(year)
    totals: dict[str, int] = {}

    for branch, sub in counts.items():
        if branch in excluded:
            continue

        if isinstance(sub, dict):
            totals[branch] = sum(int(count) for count in sub.values() if count)

        elif isinstance(sub, (int, float)):
            totals[branch] = int(sub)

    return totals


def get_total_students_for_year(year: str | None = None) -> int:
    """
    Get the total eligible students for a placement year.

    Derived from student_counts (single source): sum of per-branch totals.

    Args:
        year: Placement year in any accepted format.

    Returns:
        Total student count.
    """
    return sum(get_branch_totals_for_year(year).values())


def get_branches_for_year(year: str | None = None) -> dict[str, dict[str, int]]:
    """
    Get the branch breakdown (with totals) for a placement year.

    Derived from student_counts (single source).

    Args:
        year: Placement year in any accepted format.

    Returns:
        Mapping of branch -> {total, ...campus/sub counts}.
    """
    counts = get_student_counts_for_year(year)
    derived: dict[str, dict[str, int]] = {}

    for branch, sub in counts.items():
        if isinstance(sub, dict):
            derived[branch] = {
                "total": sum(int(count) for count in sub.values() if count),
                **{key: int(value) for key, value in sub.items()},
            }

    return derived
