"""Notice collection repository methods."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from core.config import safe_print
from model.notices import NoticeDocument
from services.database.base import RepositoryMixin


class NoticeRepository(RepositoryMixin):
    """CRUD and stats operations for the Notices collection."""

    def notice_exists(self, notice_id: str) -> bool:
        """Check if a notice with given id exists."""
        if not notice_id:
            return False
        try:
            return (
                self.notices_collection is not None
                and self.notices_collection.find_one({"id": notice_id}) is not None
            )
        except Exception as e:
            safe_print(f"Error checking notice existence: {e}")
            return False

    def get_all_notice_ids(self) -> set:
        """Get all notice IDs as a set for efficient lookup."""
        try:
            if self.notices_collection is None:
                return set()
            cursor = self.notices_collection.find({}, {"id": 1})
            return {doc.get("id") for doc in cursor if doc.get("id")}
        except Exception as e:
            safe_print(f"Error getting notice IDs: {e}")
            return set()

    def save_notice(self, notice: Dict[str, Any]) -> Tuple[bool, str]:
        """Atomically insert a notice, relying on the unique source-id index."""
        try:
            nid = notice.get("id") if isinstance(notice, dict) else None
            if not nid:
                return False, "Missing notice id"

            if self.notices_collection is None:
                return False, "Notices collection not initialized"

            doc = self._validated_doc(NoticeDocument(**notice))
            doc["saved_at"] = datetime.now(timezone.utc)
            doc["sent_to_telegram"] = False
            doc["delivery_status"] = {}
            res = self.notices_collection.insert_one(doc)
            safe_print(f"Saved notice {nid} -> {res.inserted_id}")
            return True, str(res.inserted_id)

        except DuplicateKeyError:
            return False, "Notice already exists"
        except Exception as e:
            safe_print(f"Error saving notice: {e}")
            return False, str(e)

    def get_notice_by_id(self, notice_id: str) -> Optional[Dict[str, Any]]:
        """Get a notice by its ID."""
        try:
            if self.notices_collection is None:
                return None
            return self.notices_collection.find_one({"id": notice_id})
        except Exception as e:
            safe_print(f"Error fetching notice {notice_id}: {e}")
            return None

    @staticmethod
    def _pending_channel_query(channel: str) -> Dict[str, Any]:
        """Build a backward-compatible query for one pending channel."""
        clauses: List[Dict[str, Any]] = [
            {f"delivery_status.{channel}": {"$ne": True}}
        ]
        if channel == "telegram":
            clauses.append({"sent_to_telegram": {"$ne": True}})
        return {"$and": clauses}

    def get_pending_notices(self, channels: List[str]) -> List[Dict[str, Any]]:
        """Get notices pending delivery for any selected channel."""
        try:
            if self.notices_collection is None:
                safe_print("Notices collection not initialized")
                return []

            selected_channels = list(dict.fromkeys(channel for channel in channels if channel))
            if not selected_channels:
                return []

            channel_queries = [
                self._pending_channel_query(channel) for channel in selected_channels
            ]
            query = channel_queries[0] if len(channel_queries) == 1 else {"$or": channel_queries}
            cursor = self.notices_collection.find(query).sort("createdAt", 1)
            posts = list(cursor)
            safe_print(f"Found {len(posts)} notices pending {selected_channels}")
            return posts

        except Exception as e:
            safe_print(f"Error getting pending notices: {e}")
            return []

    def get_unsent_notices(self) -> List[Dict[str, Any]]:
        """Get notices not yet sent to Telegram (legacy API)."""
        return self.get_pending_notices(["telegram"])

    def mark_channel_delivered(self, post_id: Any, channel: str) -> bool:
        """Atomically mark one channel delivered without affecting other channels."""
        try:
            if self.notices_collection is None or not channel:
                return False

            now = datetime.now(timezone.utc)
            set_fields: Dict[str, Any] = {
                f"delivery_status.{channel}": True,
                f"delivery_timestamps.{channel}": now,
            }
            if channel == "telegram":
                set_fields.update({"sent_to_telegram": True, "sent_at": now})

            result = self.notices_collection.update_one(
                {"$and": [{"_id": post_id}, self._pending_channel_query(channel)]},
                {"$set": set_fields},
            )
            return result.modified_count > 0
        except Exception as e:
            safe_print(f"Error marking {channel} delivery for post: {e}")
            return False

    def mark_as_sent(self, post_id: Any) -> bool:
        """Mark a notice as sent to Telegram (legacy API)."""
        return self.mark_channel_delivered(post_id, "telegram")

    def get_all_notices(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all notices with optional limit."""
        try:
            if self.notices_collection is None:
                return []
            cursor = self.notices_collection.find().sort("saved_at", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            safe_print(f"Error getting all notices: {e}")
            return []

    def get_notice_stats(self) -> Dict[str, Any]:
        """Return statistics about the Notices collection."""
        try:
            if self.notices_collection is None:
                return {}

            total_posts = self.notices_collection.count_documents({})
            sent_to_telegram = self.notices_collection.count_documents(
                {"sent_to_telegram": True}
            )
            pending_to_send = self.notices_collection.count_documents(
                {"sent_to_telegram": {"$ne": True}}
            )

            try:
                pipeline = [
                    {
                        "$group": {
                            "_id": {"$ifNull": ["$type", "unknown"]},
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1}},
                ]
                post_types = list(self.notices_collection.aggregate(pipeline))
            except Exception:
                post_types = []

            return {
                "total_posts": int(total_posts),
                "sent_to_telegram": int(sent_to_telegram),
                "pending_to_send": int(pending_to_send),
                "post_types": post_types,
            }
        except Exception as e:
            safe_print(f"Error getting notice stats: {e}")
            return {"error": str(e)}
