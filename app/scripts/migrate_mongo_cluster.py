"""Copy a MongoDB database between the clusters configured in the root .env.

The source cluster is read from ``TO_MIGRATE_MONGO`` and the destination
cluster is read from ``MONGO_CONNECTION_STR``. By default this migrates all
collections from ``SupersetPlacement`` to ``2025-26``. It then imports users
from ``2025-26.Users`` into ``PlacementGlobal.Users`` and copies official
placement snapshots into ``PlacementGlobal.OfficialPlacementData``.

Examples:
    cd app
    python -m scripts.migrate_mongo_cluster --dry-run
    python -m scripts.migrate_mongo_cluster
    python -m scripts.migrate_mongo_cluster --replace-destination
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient, ReplaceOne, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError, PyMongoError

DEFAULT_SOURCE_DATABASE = "SupersetPlacement"
DEFAULT_DESTINATION_DATABASE = "2025-26"
DEFAULT_GLOBAL_DATABASE = "PlacementGlobal"
DEFAULT_PLACEMENT_YEAR = "202526"
DEFAULT_BATCH_SIZE = 500


def batched(items: Iterable[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    """Yield document batches of at most ``batch_size`` items."""
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def copy_indexes(source: Database, destination: Database, collection_name: str) -> None:
    """Create source collection indexes that do not already exist at destination."""
    source_indexes = source[collection_name].index_information()
    destination_indexes = destination[collection_name].index_information()

    for index_name, index in source_indexes.items():
        if index_name == "_id_" or index_name in destination_indexes:
            continue

        keys = index.pop("key")
        index.pop("ns", None)
        index.pop("v", None)
        destination[collection_name].create_index(keys, name=index_name, **index)


def copy_collection(
    source: Database,
    destination: Database,
    collection_name: str,
    batch_size: int,
) -> int:
    """Upsert all source documents into a destination collection by ``_id``."""
    copied = 0
    cursor = source[collection_name].find({}).batch_size(batch_size)
    try:
        for documents in batched(cursor, batch_size):
            operations = [
                ReplaceOne({"_id": document["_id"]}, document, upsert=True)
                for document in documents
            ]
            destination[collection_name].bulk_write(operations, ordered=False)
            copied += len(documents)
    finally:
        cursor.close()

    copy_indexes(source, destination, collection_name)
    return copied


def migrate_users_to_global(
    client: MongoClient,
    year_database_name: str,
    global_database_name: str,
    placement_year: str,
    batch_size: int,
    dry_run: bool,
) -> bool:
    """Import year-database users into the shared global Users collection."""
    source = client[year_database_name]["Users"]
    destination = client[global_database_name]["Users"]
    source_count = source.count_documents({"user_id": {"$exists": True}})
    existing_count = destination.count_documents({})

    print(
        f"Global user migration: {year_database_name}.Users -> "
        f"{global_database_name}.Users"
    )
    print(
        f"  source users={source_count}, existing global users={existing_count}, "
        f"placement year={placement_year}"
    )
    if dry_run:
        print("  Dry run: global users were not changed.")
        return True

    imported = 0
    source_user_ids: list[int] = []
    cursor = source.find({"user_id": {"$exists": True}}).batch_size(batch_size)
    try:
        for documents in batched(cursor, batch_size):
            operations = []
            for document in documents:
                user_id = document.get("user_id")
                if user_id is None:
                    continue
                source_user_ids.append(user_id)
                user_data = dict(document)
                user_data.pop("_id", None)
                user_data["selected_placement_year"] = (
                    user_data.get("selected_placement_year") or placement_year
                )
                operations.append(
                    UpdateOne(
                        {"user_id": user_id},
                        {"$setOnInsert": user_data},
                        upsert=True,
                    )
                )
            if operations:
                result = destination.bulk_write(operations, ordered=False)
                imported += result.upserted_count
    finally:
        cursor.close()

    destination.create_index(
        [("user_id", ASCENDING)],
        unique=True,
        name="users_user_id_unique",
        partialFilterExpression={"user_id": {"$type": "number"}},
    )

    verified = 0
    for offset in range(0, len(source_user_ids), batch_size):
        user_ids = source_user_ids[offset : offset + batch_size]
        verified += destination.count_documents({"user_id": {"$in": user_ids}})

    print(
        f"  imported={imported}, already present={len(source_user_ids) - imported}, "
        f"verified={verified}/{len(source_user_ids)}"
    )
    if verified != len(source_user_ids):
        print("Global user verification failed.")
        return False

    print("Global user migration completed successfully.")
    return True


def migrate_official_data_to_global(
    client: MongoClient,
    year_database_name: str,
    global_database_name: str,
    batch_size: int,
    dry_run: bool,
) -> bool:
    """Copy official placement snapshots into the shared global database."""
    collection_name = "OfficialPlacementData"
    source_database = client[year_database_name]
    destination_database = client[global_database_name]
    source = source_database[collection_name]
    destination = destination_database[collection_name]
    source_ids = source.distinct("_id")

    print(
        f"Global official-data migration: {year_database_name}.{collection_name} "
        f"-> {global_database_name}.{collection_name}"
    )
    print(
        f"  source snapshots={len(source_ids)}, "
        f"existing global snapshots={destination.count_documents({})}"
    )
    if dry_run:
        print("  Dry run: global official placement data was not changed.")
        return True

    copied = copy_collection(
        source_database,
        destination_database,
        collection_name,
        batch_size,
    )
    verified = 0
    for offset in range(0, len(source_ids), batch_size):
        ids = source_ids[offset : offset + batch_size]
        verified += destination.count_documents({"_id": {"$in": ids}})

    print(f"  copied={copied}, verified={verified}/{len(source_ids)}")
    if verified != len(source_ids):
        print("Global official placement data verification failed.")
        return False

    print("Global official placement data migration completed successfully.")
    return True


def migrate_database(
    source_client: MongoClient,
    destination_client: MongoClient,
    source_database_name: str,
    destination_database_name: str,
    batch_size: int,
    dry_run: bool,
    replace_destination: bool,
) -> bool:
    """Copy all regular collections and verify destination document counts."""
    source = source_client[source_database_name]
    destination = destination_client[destination_database_name]
    collection_names = sorted(
        collection["name"]
        for collection in source.list_collections()
        if collection.get("type") == "collection"
        and not collection["name"].startswith("system.")
    )

    if not collection_names:
        raise RuntimeError(f"Source database {source_database_name!r} has no collections")

    print(
        f"Source database {source_database_name!r}: "
        f"{len(collection_names)} collection(s)"
    )
    for collection_name in collection_names:
        count = source[collection_name].count_documents({})
        print(f"  {collection_name}: {count} document(s)")

    if dry_run:
        print("Dry run complete; destination was not changed.")
        return True

    if replace_destination:
        print(f"Dropping destination database {destination_database_name!r}...")
        destination_client.drop_database(destination_database_name)
        destination = destination_client[destination_database_name]

    print(f"Migrating into destination database {destination_database_name!r}...")
    for collection_name in collection_names:
        copied = copy_collection(source, destination, collection_name, batch_size)
        print(f"  {collection_name}: copied {copied} document(s)")

    mismatches = []
    for collection_name in collection_names:
        source_count = source[collection_name].count_documents({})
        destination_count = destination[collection_name].count_documents({})
        if source_count != destination_count:
            mismatches.append((collection_name, source_count, destination_count))

    if mismatches:
        print("Migration finished, but document-count verification failed:")
        for collection_name, source_count, destination_count in mismatches:
            print(
                f"  {collection_name}: source={source_count}, "
                f"destination={destination_count}"
            )
        print(
            "The destination may contain pre-existing documents. Use "
            "--replace-destination for an exact replacement."
        )
        return False

    print("Migration completed and all collection document counts match.")
    return True


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Migrate a MongoDB database between clusters using .env URIs."
    )
    parser.add_argument(
        "--source-database",
        default=DEFAULT_SOURCE_DATABASE,
        help=f"Source database name (default: {DEFAULT_SOURCE_DATABASE})",
    )
    parser.add_argument(
        "--destination-database",
        default=DEFAULT_DESTINATION_DATABASE,
        help=f"Destination database name (default: {DEFAULT_DESTINATION_DATABASE})",
    )
    parser.add_argument(
        "--global-database",
        default=None,
        help=(
            "Shared database for Users (default: GLOBAL_DATABASE_NAME from .env, "
            f"or {DEFAULT_GLOBAL_DATABASE})"
        ),
    )
    parser.add_argument(
        "--placement-year",
        default=DEFAULT_PLACEMENT_YEAR,
        help=f"Year assigned to imported users (default: {DEFAULT_PLACEMENT_YEAR})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Documents per bulk write (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect and show what would be copied without writing data",
    )
    parser.add_argument(
        "--replace-destination",
        action="store_true",
        help="Drop the destination database before copying (destructive)",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.dry_run and args.replace_destination:
        parser.error("--dry-run and --replace-destination cannot be used together")
    return args


def main() -> int:
    """Load configuration, connect to both clusters, and run the migration."""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    source_uri = os.getenv("TO_MIGRATE_MONGO", "").strip()
    destination_uri = os.getenv("MONGO_CONNECTION_STR", "").strip()
    if not source_uri:
        raise RuntimeError("TO_MIGRATE_MONGO is missing from the root .env")
    if not destination_uri:
        raise RuntimeError("MONGO_CONNECTION_STR is missing from the root .env")
    if source_uri == destination_uri:
        raise RuntimeError("Source and destination MongoDB URIs must be different")

    source_client = MongoClient(source_uri, serverSelectionTimeoutMS=15_000)
    destination_client = MongoClient(destination_uri, serverSelectionTimeoutMS=15_000)
    try:
        source_client.admin.command("ping")
        destination_client.admin.command("ping")
        database_success = migrate_database(
            source_client=source_client,
            destination_client=destination_client,
            source_database_name=args.source_database,
            destination_database_name=args.destination_database,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            replace_destination=args.replace_destination,
        )
        global_database_name = (
            args.global_database
            or os.getenv("GLOBAL_DATABASE_NAME", "").strip()
            or DEFAULT_GLOBAL_DATABASE
        )
        users_success = migrate_users_to_global(
            client=destination_client,
            year_database_name=args.destination_database,
            global_database_name=global_database_name,
            placement_year=args.placement_year,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        official_data_success = migrate_official_data_to_global(
            client=destination_client,
            year_database_name=args.destination_database,
            global_database_name=global_database_name,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        return 0 if all(
            (database_success, users_success, official_data_success)
        ) else 1
    except (BulkWriteError, PyMongoError) as exc:
        print(f"MongoDB migration failed: {exc}")
        return 1
    finally:
        source_client.close()
        destination_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
