"""Users and placement-year repository methods."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.config import safe_print
from core.year_context import get_default_year, label_for_year, normalize_year
from model.placement_years import PlacementYearDocument
from model.users import UserDocument
from services.database.base import RepositoryMixin


class UserRepository(RepositoryMixin):
    """User and placement-year persistence operations."""

    def add_user(
        self,
        user_id: int,
        chat_id: Optional[int] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Add or reactivate a user."""
        try:
            if self.users_collection is None:
                return False, "Users collection not initialized"

            existing_user = self.users_collection.find_one({"user_id": user_id})
            default_year = get_default_year(self._settings_for_defaults())

            if existing_user:
                if not existing_user.get("is_active", False):
                    result = self.users_collection.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "is_active": True,
                                "chat_id": chat_id,
                                "username": username,
                                "first_name": first_name,
                                "last_name": last_name,
                                "selected_placement_year": existing_user.get(
                                    "selected_placement_year"
                                ) or default_year,
                                "updated_at": datetime.now(timezone.utc),
                            }
                        },
                    )
                    if result.modified_count > 0:
                        safe_print(f"Reactivated user: {user_id} (@{username})")
                        return True, "User reactivated"

                safe_print(f"User {user_id} already exists and is active")
                return False, "User already exists and is active"

            now = datetime.now(timezone.utc)
            user_data = self._validated_doc(
                UserDocument(
                    user_id=user_id,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True,
                    selected_placement_year=default_year,
                    created_at=now,
                    updated_at=now,
                )
            )
            result = self.users_collection.insert_one(user_data)
            safe_print(f"Added new user: {user_id} (@{username})")
            return True, str(result.inserted_id)

        except Exception as e:
            safe_print(f"Error adding user: {e}")
            return False, str(e)

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate a user (soft delete)."""
        try:
            if self.users_collection is None:
                return False
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as e:
            safe_print(f"Error deactivating user: {e}")
            return False

    def get_active_users(
        self, placement_year: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get active users, optionally scoped to their selected placement year."""
        try:
            if self.users_collection is None:
                return []

            query: Dict[str, Any] = {"is_active": True}
            if placement_year:
                normalized_year = normalize_year(placement_year)
                if not normalized_year:
                    return []
                year_filters: List[Dict[str, Any]] = [
                    {"selected_placement_year": normalized_year}
                ]
                default_year = get_default_year(self._settings_for_defaults())
                if normalized_year == default_year:
                    year_filters.extend(
                        [
                            {"selected_placement_year": {"$exists": False}},
                            {"selected_placement_year": None},
                        ]
                    )
                query["$or"] = year_filters

            return list(self.users_collection.find(query))
        except Exception as e:
            safe_print(f"Error getting users: {e}")
            return []

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users for admin views."""
        try:
            if self.users_collection is None:
                return []
            return list(self.users_collection.find({}))
        except Exception as e:
            safe_print(f"Error getting users: {e}")
            return []

    def import_legacy_users(
        self,
        users: List[Dict[str, Any]],
        placement_year: str,
    ) -> int:
        """Insert users missing from the global DB without overwriting preferences."""
        if self.users_collection is None:
            return 0

        normalized_year = normalize_year(placement_year)
        if not normalized_year:
            return 0

        imported = 0
        now = datetime.now(timezone.utc)
        for raw_user in users:
            user_id = raw_user.get("user_id")
            if user_id is None:
                continue

            selected_year = raw_user.get("selected_placement_year")
            try:
                selected_year = normalize_year(selected_year) or normalized_year
            except ValueError:
                selected_year = normalized_year

            user_data = self._validated_doc(
                UserDocument(
                    **{
                        **raw_user,
                        "mongo_id": None,
                        "selected_placement_year": selected_year,
                        "created_at": raw_user.get("created_at") or now,
                        "updated_at": raw_user.get("updated_at") or now,
                    }
                )
            )
            user_data.pop("_id", None)
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {"$setOnInsert": user_data},
                upsert=True,
            )
            if result.upserted_id is not None:
                imported += 1

        if imported:
            safe_print(f"Imported {imported} legacy users into the global database")
        return imported

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user by their ID."""
        try:
            if self.users_collection is None:
                return None
            return self.users_collection.find_one({"user_id": user_id})
        except Exception as e:
            safe_print(f"Error getting user by ID: {e}")
            return None

    def get_users_stats(self) -> Dict[str, Any]:
        """Get user statistics."""
        try:
            if self.users_collection is None:
                return {}
            total_users = self.users_collection.count_documents({})
            active_users = self.users_collection.count_documents({"is_active": True})
            return {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": total_users - active_users,
            }
        except Exception as e:
            safe_print(f"Error getting user stats: {e}")
            return {}

    def set_user_placement_year(self, user_id: int, placement_year: str) -> bool:
        """Set a user's selected placement year."""
        try:
            if self.users_collection is None:
                return False
            normalized_year = normalize_year(placement_year)
            if not normalized_year:
                return False
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "selected_placement_year": normalized_year,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=False,
            )
            return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            safe_print(f"Error setting user placement year: {e}")
            return False

    def get_user_placement_year(self, user_id: int, default_year: str = "202526") -> str:
        """Get a user's selected placement year, falling back to default_year."""
        try:
            user = self.get_user_by_id(user_id)
            if not user:
                return normalize_year(default_year) or "202526"
            return normalize_year(user.get("selected_placement_year") or default_year) or "202526"
        except Exception as e:
            safe_print(f"Error getting user placement year: {e}")
            return normalize_year(default_year) or "202526"

    def upsert_placement_years(self, years: List[str]) -> None:
        """Ensure placement year documents exist in the global database."""
        try:
            if self.placement_years_collection is None:
                return
            now = datetime.now(timezone.utc)
            default_year = get_default_year(self._settings_for_defaults())
            for year in years:
                normalized_year = normalize_year(year)
                if not normalized_year:
                    continue
                doc = self._validated_doc(
                    PlacementYearDocument(
                        year=normalized_year,
                        label=label_for_year(normalized_year),
                        database_name=label_for_year(normalized_year),
                        is_active=True,
                        is_default=normalized_year == default_year,
                        updated_at=now,
                    )
                )
                self.placement_years_collection.update_one(
                    {"year": normalized_year},
                    {
                        "$set": doc,
                        "$setOnInsert": {"created_at": now},
                    },
                    upsert=True,
                )
        except Exception as e:
            safe_print(f"Error upserting placement years: {e}")

    def get_active_placement_years(self) -> List[Dict[str, Any]]:
        """Get active placement year documents from global database."""
        try:
            if self.placement_years_collection is None:
                return []
            return list(
                self.placement_years_collection.find({"is_active": True}).sort(
                    "year", 1
                )
            )
        except Exception as e:
            safe_print(f"Error getting active placement years: {e}")
            return []

    def _settings_for_defaults(self):
        """Load settings lazily to avoid config import work during tests."""
        from core.config import get_settings

        return get_settings()
