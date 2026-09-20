"""Shared helpers for database repositories."""

from typing import Any

from pydantic import BaseModel


class RepositoryMixin:
    """Common helpers shared by collection-specific repositories."""

    @staticmethod
    def _validated_doc(model: BaseModel) -> dict[str, Any]:
        """Return a Mongo-ready dict from a Pydantic model."""
        return model.model_dump(by_alias=True, exclude_none=True)

    @staticmethod
    def _has_value(value: Any) -> bool:
        """Return True when a value should overwrite stored structured data."""
        return value not in (None, "", [], {})

    @staticmethod
    def normalize_company_identity(value: Any) -> tuple[str, str]:
        """Return a clean display name and stable case-insensitive company key."""
        display_name = " ".join(str(value or "").split())
        return display_name, display_name.casefold()
