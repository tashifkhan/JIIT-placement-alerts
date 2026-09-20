"""Configuration constants for placement statistics."""

from typing import Dict, Set


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

EXCLUDED_BRANCHES: Set[str] = {
    "JUIT",
    "Other",
    "MTech",
}
