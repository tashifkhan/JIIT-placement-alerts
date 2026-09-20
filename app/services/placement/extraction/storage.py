"""File storage fallback for placement offer extraction."""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from core.config import safe_print


class PlacementStorageMixin:
    """JSON storage fallback behavior for PlacementService."""

    def save_to_json(self, data: List[Dict], filename: Optional[str] = None) -> None:
        """Append placement offers to a JSON file with deduplication."""
        if filename is None:
            filename = self.output_file

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        existing = []
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as file:
                    existing = json.load(file)
                    if not isinstance(existing, list):
                        existing = []
            except (json.JSONDecodeError, IOError) as e:
                safe_print(f"Warning: Could not read existing file {filename}: {e}")
                backup_file = (
                    f"{filename}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                try:
                    os.rename(filename, backup_file)
                    safe_print(f"Corrupted file backed up to: {backup_file}")
                except Exception as backup_error:
                    safe_print(
                        f"Warning: Could not back up corrupted file: {backup_error}"
                    )
                existing = []

        existing_keys = set()
        for item in existing:
            if isinstance(item, dict):
                key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
                existing_keys.add(key)

        new_items_added = 0
        for item in data:
            if isinstance(item, dict):
                key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
                if key not in existing_keys:
                    existing.append(item)
                    existing_keys.add(key)
                    new_items_added += 1
                else:
                    safe_print(
                        f"Skipping duplicate offer: {item.get('email_subject', 'Unknown')}"
                    )

        try:
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(existing, file, indent=2, ensure_ascii=False)
            safe_print(f"Successfully saved {new_items_added} new offers to {filename}")
            safe_print(f"Total offers in file: {len(existing)}")
        except IOError as e:
            safe_print(f"Error saving to file {filename}: {e}")
            raise
