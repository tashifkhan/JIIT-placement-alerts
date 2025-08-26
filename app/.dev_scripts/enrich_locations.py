import json
import os
from typing import Any, Dict, List


def main() -> None:
    # Resolve data directory relative to this script (../data)
    script_dir = os.path.dirname(__file__)
    data_dir = os.path.abspath(os.path.join(script_dir, "..", "data"))

    final_path = os.path.join(data_dir, "final_notices.json")
    jobs_path = os.path.join(data_dir, "structured_job_listings.json")

    # Load files
    with open(final_path, "r", encoding="utf-8") as f:
        final_notices: List[Dict[str, Any]] = json.load(f)

    with open(jobs_path, "r", encoding="utf-8") as f:
        jobs: List[Dict[str, Any]] = json.load(f)

    # Build job id -> location map (fallback to None if missing)
    id_to_location: Dict[str, Any] = {}
    for j in jobs:
        jid = j.get("id")
        if isinstance(jid, str) and jid:
            id_to_location[jid] = j.get("location")

    updated_count = 0
    missing_jobs = 0

    for entry in final_notices:
        job_id = entry.get("matched_job_id")
        if not job_id:
            continue

        loc = id_to_location.get(job_id)
        if loc is None:
            missing_jobs += 1
            continue

        # Add/overwrite a concise 'location' field as requested
        if entry.get("location") != loc:
            entry["location"] = loc
            updated_count += 1

    # Backup then write in place
    backup_path = final_path + ".backup"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(final_notices, f, ensure_ascii=False, indent=2)

    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final_notices, f, ensure_ascii=False, indent=2)

    print(f"Updated entries: {updated_count}")
    print(f"Missing job ids: {missing_jobs}")
    print(f"Wrote updated file to: {final_path}\nBackup at: {backup_path}")


if __name__ == "__main__":
    main()
