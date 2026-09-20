"""OfficialPlacementData collection repository methods."""

import hashlib
import json
from typing import Any, Dict

from core.config import safe_print
from model.official_placement import OfficialPlacementDataDocument
from services.database.base import RepositoryMixin


class OfficialPlacementRepository(RepositoryMixin):
    """Persistence for scraped official JIIT placement data."""

    def save_official_placement_data(self, data: Dict[str, Any]) -> bool:
        """Save official placement data from JIIT website."""
        try:
            if self.db_client.db is None:
                safe_print("Database not initialized")
                return False

            collection = self.db_client.official_placement_data_collection
            validated_data = self._validated_doc(OfficialPlacementDataDocument(**data))
            data_for_hash = {
                k: v
                for k, v in validated_data.items()
                if k not in ("scrape_timestamp", "_id", "content_hash")
            }
            content_hash = hashlib.sha256(
                json.dumps(data_for_hash, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest()

            latest_doc = collection.find_one(sort=[("scrape_timestamp", -1)])

            if latest_doc and latest_doc.get("content_hash") == content_hash:
                result = collection.update_one(
                    {"_id": latest_doc["_id"]},
                    {"$set": {"scrape_timestamp": validated_data.get("scrape_timestamp")}},
                )
                safe_print(
                    f"Official placement data unchanged (hash: {content_hash[:12]}...). Updated timestamp."
                )
                return bool(result.acknowledged)
            else:
                validated_data["content_hash"] = content_hash
                result = collection.insert_one(validated_data)
                safe_print(
                    f"New official placement data inserted (hash: {content_hash[:12]}...). ID: {result.inserted_id}"
                )
                return result.inserted_id is not None
        except Exception as e:
            safe_print(f"Error saving official placement data: {e}")
            self.logger.error("Error saving official placement data", exc_info=True)
            return False
