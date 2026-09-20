"""Policies collection repository methods."""

import logging
from typing import Any

from core.config import safe_print
from model.policies import PolicyDocument
from services.database.base import RepositoryMixin

logger = logging.getLogger(__name__)


class PolicyRepository(RepositoryMixin):
    """Persistence operations for placement policies."""

    def get_policy_by_year(self, year: int) -> dict[str, Any] | None:
        """Get a policy document by year."""
        try:
            if self.policies_collection is None:
                return None
            return self.policies_collection.find_one({"year": year})
        except Exception as e:
            safe_print(f"Error fetching policy for year {year}: {e}")
            logger.exception("Error fetching policy for year %s", year)
            return None

    def upsert_policy(self, policy: dict[str, Any]) -> tuple[bool, str]:
        """Insert or update a policy document."""
        try:
            if self.policies_collection is None:
                return False, "Policies collection not initialized"

            validated_policy = self._validated_doc(PolicyDocument(**policy))
            validated_policy.pop("_id", None)
            year = validated_policy.get("year")
            if not year:
                return False, "Missing policy year"

            result = self.policies_collection.update_one(
                {"year": year}, {"$set": validated_policy}, upsert=True
            )

            if result.upserted_id:
                safe_print(f"Created new policy for year {year}")
                return True, str(result.upserted_id)

            if result.modified_count > 0:
                safe_print(f"Updated policy for year {year}")
                return True, "updated"

            safe_print(f"Policy for year {year} unchanged")
            return True, "unchanged"

        except Exception as e:
            safe_print(f"Error upserting policy: {e}")
            logger.exception("Error upserting policy")
            return False, str(e)

    def get_all_policies(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get all published policies with optional limit."""
        try:
            if self.policies_collection is None:
                return []

            cursor = (
                self.policies_collection.find({"published": True})
                .sort("year", -1)
                .limit(limit)
            )
            return list(cursor)

        except Exception as e:
            safe_print(f"Error getting all policies: {e}")
            logger.exception("Error getting all policies")
            return []
