"""OfficialPlacementData and OfficialPlacementBatches repository methods."""

import datetime
import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

from core.config import safe_print
from model.official_placement import (
    OfficialPlacementBatchDocument,
    OfficialPlacementDataDocument,
)
from services.database.base import RepositoryMixin

logger = logging.getLogger(__name__)


class OfficialPlacementRepository(RepositoryMixin):
    """Persistence for scraped official JIIT placement data."""

    def save_official_placement_data(self, data: dict[str, Any]) -> bool:
        """Save a full-page scrape snapshot and upsert live per-year batches."""
        try:
            if self.db_client.db is None:
                safe_print("Database not initialized")
                return False

            collection = self.db_client.official_placement_data_collection
            if collection is None:
                safe_print("OfficialPlacementData collection not initialized")
                return False

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
                    {
                        "$set": {
                            "scrape_timestamp": validated_data.get("scrape_timestamp")
                        }
                    },
                )
                snapshot_ok = bool(result.acknowledged)
                safe_print(
                    f"Official placement data unchanged (hash: {content_hash[:12]}...). Updated timestamp."
                )
            else:
                validated_data["content_hash"] = content_hash
                result = collection.insert_one(validated_data)
                snapshot_ok = result.inserted_id is not None
                safe_print(
                    f"New official placement data inserted (hash: {content_hash[:12]}...). ID: {result.inserted_id}"
                )

            batches_ok = self.sync_official_placement_batches_from_scrape(
                validated_data.get("batches") or [],
                scrape_timestamp=str(validated_data.get("scrape_timestamp") or ""),
            )
            return snapshot_ok and batches_ok
        except Exception as e:
            safe_print(f"Error saving official placement data: {e}")
            logger.exception("Error saving official placement data")
            return False

    def sync_official_placement_batches_from_scrape(
        self,
        batches: Iterable[dict[str, Any]],
        scrape_timestamp: str,
    ) -> bool:
        """Upsert live batches and freeze any live years missing from this scrape."""
        try:
            collection = self.db_client.official_placement_batches_collection
            if collection is None:
                safe_print("OfficialPlacementBatches collection not initialized")
                return False

            now = datetime.datetime.now(datetime.UTC).isoformat()
            live_names: list[str] = []
            for raw in batches:
                batch_name = str(raw.get("batch_name") or "").strip()
                if not batch_name:
                    continue
                live_names.append(batch_name)
                existing = collection.find_one({"batch_name": batch_name})
                if existing and existing.get("source") == "seeded":
                    safe_print(
                        f"Skipping live overwrite of seeded official batch {batch_name}"
                    )
                    continue

                doc = OfficialPlacementBatchDocument(
                    batch_name=batch_name,
                    is_active=bool(raw.get("is_active")),
                    source="live",
                    placement_pointers=list(raw.get("placement_pointers") or []),
                    package_distribution=list(raw.get("package_distribution") or []),
                    highlights=list(raw.get("highlights") or []),
                    updated_at=now,
                    scrape_timestamp=scrape_timestamp or now,
                )
                payload = self._validated_doc(doc)
                payload.pop("_id", None)
                collection.update_one(
                    {"batch_name": batch_name},
                    {"$set": payload},
                    upsert=True,
                )
                safe_print(f"Upserted live official batch {batch_name}")

            # Years that were live but disappeared from JIIT stay forever as seeded.
            if live_names:
                freeze_result = collection.update_many(
                    {
                        "source": "live",
                        "batch_name": {"$nin": live_names},
                    },
                    {
                        "$set": {
                            "source": "seeded",
                            "is_active": False,
                            "updated_at": now,
                        }
                    },
                )
                if freeze_result.modified_count:
                    safe_print(
                        f"Froze {freeze_result.modified_count} official batch(es) no longer on JIIT"
                    )

            # Only years present in this scrape may stay marked active.
            collection.update_many(
                {"batch_name": {"$nin": live_names}},
                {"$set": {"is_active": False}},
            )
            return True
        except Exception as e:
            safe_print(f"Error syncing official placement batches: {e}")
            logger.exception("Error syncing official placement batches")
            return False

    def upsert_seeded_official_placement_batches(
        self,
        batches: Iterable[dict[str, Any]],
        *,
        seed_version: str = "1",
        overwrite_seeded: bool = False,
    ) -> dict[str, int]:
        """Insert frozen historical batches without clobbering live docs."""
        stats = {"inserted": 0, "updated": 0, "skipped_live": 0, "skipped_existing": 0}
        try:
            collection = self.db_client.official_placement_batches_collection
            if collection is None:
                safe_print("OfficialPlacementBatches collection not initialized")
                return stats

            now = datetime.datetime.now(datetime.UTC).isoformat()
            for raw in batches:
                batch_name = str(raw.get("batch_name") or "").strip()
                if not batch_name:
                    continue
                existing = collection.find_one({"batch_name": batch_name})
                if existing and existing.get("source") == "live":
                    stats["skipped_live"] += 1
                    safe_print(
                        f"Seed skipped live official batch {batch_name}"
                    )
                    continue
                if existing and not overwrite_seeded:
                    stats["skipped_existing"] += 1
                    safe_print(
                        f"Seed skipped existing seeded batch {batch_name}"
                    )
                    continue

                doc = OfficialPlacementBatchDocument(
                    batch_name=batch_name,
                    is_active=False,
                    source="seeded",
                    placement_pointers=list(raw.get("placement_pointers") or []),
                    package_distribution=list(raw.get("package_distribution") or []),
                    highlights=list(raw.get("highlights") or []),
                    updated_at=now,
                    seed_version=str(raw.get("seed_version") or seed_version),
                    provenance=raw.get("provenance"),
                )
                payload = self._validated_doc(doc)
                payload.pop("_id", None)
                result = collection.update_one(
                    {"batch_name": batch_name},
                    {"$set": payload},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
                safe_print(f"Seeded official batch {batch_name}")
            return stats
        except Exception as e:
            safe_print(f"Error seeding official placement batches: {e}")
            logger.exception("Error seeding official placement batches")
            return stats

    def list_official_placement_batches(self) -> list[dict[str, Any]]:
        """Return all graduating-year batches newest-first."""
        collection = self.db_client.official_placement_batches_collection
        if collection is None:
            return []
        docs = list(collection.find({}, {"_id": 0}))
        docs.sort(key=lambda item: str(item.get("batch_name") or ""), reverse=True)
        return docs
