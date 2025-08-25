"""
Script: add_sent_to_notices.py

Find all documents in the `Notices` collection that are missing the
`sent_to_telegram` field and set it to True. Safe default is to run in
live mode; pass --dry-run to preview changes.
"""

import argparse
from datetime import datetime

# Ensure the project root is on sys.path so `import app...` works when the
# script is executed directly (for example: `uv run app/scripts/...`).
# This makes the script more robust regardless of current working dir.
import sys
from pathlib import Path

# Insert the parent of the `app` directory (project root) at the front of sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import MongoDBManager
from app.config import safe_print


def main(dry_run: bool = False):
    mgr = MongoDBManager()
    try:
        query = {"sent_to_telegram": {"$exists": False}}
        missing = mgr.notices_collection.count_documents(query)
        safe_print(f"Found {missing} notices missing 'sent_to_telegram'")

        if missing == 0:
            safe_print("Nothing to do.")
            return

        if dry_run:
            safe_print("Dry run: listing up to 10 documents that would be updated:")
            for doc in mgr.notices_collection.find(query).limit(10):
                safe_print(f" - _id={doc.get('_id')} id={doc.get('id')} title={str(doc.get('title'))[:80]}")
            safe_print("Dry run complete. No changes made.")
            return

        update = {
            "$set": {
                "sent_to_telegram": True,
                "updated_at": datetime.utcnow(),
            }
        }

        result = mgr.notices_collection.update_many(query, update)
        safe_print(f"Updated {result.modified_count} documents (matched {result.matched_count}).")

    except Exception as e:
        safe_print(f"Error while updating notices: {e}")
    finally:
        mgr.close_connection()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ensure Notices documents have sent_to_telegram=True if the field is missing"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    args = parser.parse_args()

    main(dry_run=args.dry_run)
