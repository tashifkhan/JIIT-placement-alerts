"""
Placement year scoping helpers.

Centralizes conversion between compact config keys like 202526 and MongoDB
database names like 2025-26.
"""

import json
import re
from typing import Any

DEFAULT_PLACEMENT_YEAR = "202526"


def normalize_year(year: str | None) -> str | None:
    """
    Normalize a placement year to compact YYYYYY format.

    Args:
        year: Year value such as 202526, 2025-26, or 2025_26.

    Returns:
        Normalized year string, or None if no year was provided.
    """
    if not year:
        return None

    digits = re.sub(r"\D", "", str(year))
    if len(digits) != 6:
        raise ValueError(f"Invalid placement year: {year}")
    start_year = int(digits[:4])
    end_year = int(digits[4:])
    if not 2000 <= start_year <= 2099 or end_year != (start_year + 1) % 100:
        raise ValueError(f"Invalid placement year: {year}")
    return digits


def database_name_for_year(year: str) -> str:
    """
    Convert compact placement year to MongoDB database name.

    Args:
        year: Placement year in compact format, e.g. 202526.

    Returns:
        MongoDB database name, e.g. 2025-26.
    """
    normalized = normalize_year(year)
    if not normalized:
        raise ValueError("Placement year is required")
    return f"{normalized[:4]}-{normalized[4:]}"


def label_for_year(year: str) -> str:
    """
    Convert compact placement year to display label.

    Args:
        year: Placement year in compact format.

    Returns:
        Display label, e.g. 2025-26.
    """
    return database_name_for_year(year)


def get_active_year(settings: Any, override: str | None = None) -> str:
    """
    Resolve active placement year from override or settings.

    Args:
        settings: Application settings object.
        override: Optional explicit year.

    Returns:
        Normalized active year.
    """
    year = (
        override
        or getattr(settings, "active_placement_year", None)
        or getattr(settings, "default_placement_year", None)
        or DEFAULT_PLACEMENT_YEAR
    )
    normalized = normalize_year(year)
    if not normalized:
        raise ValueError("Placement year is required for year-scoped ingestion")
    return normalized


def get_default_year(settings: Any) -> str:
    """
    Resolve default placement year.

    Args:
        settings: Application settings object.

    Returns:
        Normalized default placement year.
    """
    return get_active_year(settings, getattr(settings, "default_placement_year", None))


def get_configured_placement_years(settings: Any) -> list[str]:
    """
    Resolve configured placement years for bot UI.

    Args:
        settings: Application settings object.

    Returns:
        Ordered list of normalized placement years.
    """
    years = []

    placement_years_raw = getattr(settings, "placement_years", "")
    if placement_years_raw:
        parsed_years = json.loads(placement_years_raw)
        if not isinstance(parsed_years, list):
            raise ValueError("PLACEMENT_YEARS must be a JSON list")
        years.extend(normalize_year(str(year)) for year in parsed_years)

    credentials_by_year_raw = getattr(settings, "superset_credentials_by_year", "")
    if credentials_by_year_raw:
        credentials_by_year = json.loads(credentials_by_year_raw)
        if isinstance(credentials_by_year, dict):
            years.extend(normalize_year(str(year)) for year in credentials_by_year)

    years.append(get_default_year(settings))

    seen = set()
    unique_years = []
    for year in years:
        if year and year not in seen:
            seen.add(year)
            unique_years.append(year)

    return unique_years


def get_database_name(settings: Any, year: str) -> str:
    """
    Resolve MongoDB database name for a placement year.

    Args:
        settings: Application settings object.
        year: Placement year.

    Returns:
        Database name.
    """
    # Explicit legacy database names are only appropriate when no year context
    # exists. A year-aware caller must never collapse multiple years into one DB.
    return database_name_for_year(year)


def get_superset_credentials_for_year(settings: Any, year: str) -> list[dict[str, Any]]:
    """
    Resolve SuperSet credentials for a placement year.

    Args:
        settings: Application settings object.
        year: Placement year.

    Returns:
        List of SuperSet credential dictionaries.
    """
    normalized = get_active_year(settings, year)
    credentials_by_year_raw = getattr(settings, "superset_credentials_by_year", "")

    if credentials_by_year_raw:
        credentials_by_year = json.loads(credentials_by_year_raw)
        credentials = credentials_by_year.get(normalized, [])
        if not isinstance(credentials, list):
            raise ValueError(f"SUPERSET_CREDENTIALS_BY_YEAR[{normalized}] must be a list")
        return credentials

    credentials_raw = getattr(settings, "superset_credentials", "[]")
    credentials = json.loads(credentials_raw)
    if not isinstance(credentials, list):
        raise ValueError("SUPERSET_CREDENTIALS must be a list")
    return credentials


def get_superset_credentials_by_year(
    settings: Any,
    year: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Resolve SuperSet credentials grouped by placement year.

    If a year is provided, only that year's credentials are returned. Without a
    year, all years from SUPERSET_CREDENTIALS_BY_YEAR are returned. If the nested
    config is absent, the legacy SUPERSET_CREDENTIALS value is assigned to the
    default active year.

    Args:
        settings: Application settings object.
        year: Optional placement year to scope to.

    Returns:
        Mapping of normalized placement year to credential list.
    """
    if year:
        normalized = get_active_year(settings, year)
        return {normalized: get_superset_credentials_for_year(settings, normalized)}

    credentials_by_year_raw = getattr(settings, "superset_credentials_by_year", "")
    if credentials_by_year_raw:
        raw_credentials_by_year = json.loads(credentials_by_year_raw)
        if not isinstance(raw_credentials_by_year, dict):
            raise ValueError("SUPERSET_CREDENTIALS_BY_YEAR must be a JSON object")

        credentials_by_year = {}
        for raw_year, credentials in raw_credentials_by_year.items():
            normalized = get_active_year(settings, str(raw_year))
            if not isinstance(credentials, list):
                raise ValueError(
                    f"SUPERSET_CREDENTIALS_BY_YEAR[{normalized}] must be a list"
                )
            credentials_by_year[normalized] = credentials
        return credentials_by_year

    normalized = get_active_year(settings)
    return {normalized: get_superset_credentials_for_year(settings, normalized)}


def _year_from_plus_alias(text: str) -> str | None:
    """
    Extract a placement year from a Gmail plus-alias suffix without regex.

    Handles all separator styles, e.g. ``+2025_26@``, ``+2026-27@`` and
    ``+202526@``. Scans each ``+suffix@`` occurrence and returns the first that
    normalizes to a valid 6-digit year.

    Args:
        text: A string that may contain one or more email addresses.

    Returns:
        Normalized placement year if a valid alias is found, otherwise None.
    """
    # Walk every '+...' segment and inspect the chunk up to the next '@'.
    for segment in text.split("+")[1:]:
        suffix = segment.split("@", 1)[0]
        if not suffix:
            continue
        try:
            normalized = normalize_year(suffix)
        except ValueError:
            continue
        if normalized:
            return normalized
    return None


def extract_year_from_email_data(email_data: dict[str, Any]) -> str | None:
    """
    Extract placement year from Gmail plus alias headers.

    Args:
        email_data: Parsed email data.

    Returns:
        Normalized placement year if present, otherwise None.
    """
    fields = [
        "to",
        "cc",
        "delivered_to",
        "x_original_to",
        "recipients",
    ]
    haystack = "\n".join(str(email_data.get(field, "")) for field in fields)
    return _year_from_plus_alias(haystack)
