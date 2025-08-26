import json
import os
import hashlib
from typing import Any, Dict, List, Tuple


def _fingerprint(entry: Dict[str, Any]) -> Tuple:
    """Return a stable fingerprint for a job entry to detect duplicates.
    Prefer the explicit id; otherwise, use a composite key.
    """
    jid = entry.get("id")
    if isinstance(jid, str) and jid:
        return ("id", jid)

    company = str(entry.get("company", "")).strip().lower()
    role = str(entry.get("job_profile", "")).strip().lower()
    deadline = entry.get("deadline") or entry.get("createdAt") or 0
    desc = str(entry.get("job_description") or entry.get("content") or "")
    desc_hash = hashlib.sha256(desc.encode("utf-8")).hexdigest()[:12] if desc else ""
    return ("composite", company, role, str(deadline), desc_hash)


def main() -> None:
    # Paths
    script_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(script_dir, "..", "data"))
    jobs_path = os.path.join(data_dir, "structured_job_listings.json")

    # Load
    with open(jobs_path, "r", encoding="utf-8") as f:
        jobs: List[Dict[str, Any]] = json.load(f)

    seen: set = set()
    unique: List[Dict[str, Any]] = []

    dup_by_id = 0
    dup_by_composite = 0

    for entry in jobs:
        fp = _fingerprint(entry)
        if fp in seen:
            # Count duplicates by category
            if fp and fp[0] == "id":
                dup_by_id += 1
            else:
                dup_by_composite += 1
            continue
        seen.add(fp)
        unique.append(entry)

    removed = len(jobs) - len(unique)

    # Backup
    backup_path = jobs_path + ".backup"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    # Write cleaned
    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    print(f"Original entries: {len(jobs)}")
    print(f"Unique entries:   {len(unique)}")
    print(
        f"Removed:          {removed} (by id: {dup_by_id}, by composite: {dup_by_composite})"
    )
    print(f"Updated file:     {jobs_path}\nBackup at:       {backup_path}")


if __name__ == "__main__":
    main()
