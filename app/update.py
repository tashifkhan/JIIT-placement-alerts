import os
import json
from typing import List, Dict, Any
import requests
from dotenv import load_dotenv
from pprint import pprint

from main import SupersetClient, User, Notice, Job
from llm_formater import NoticeFormatter


load_dotenv()


def run_update() -> None:
    client = SupersetClient()

    # Login multiple users (CSE, ECE)
    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    ece_email = os.getenv("ECE_EMAIL")
    ece_password = os.getenv("ECE_ENCRYPTION_PASSWORD")

    cse_user: User = client.login(cse_email, cse_password)
    ece_user: User = client.login(ece_email, ece_password)

    users: List[User] = [cse_user, ece_user]

    # Fetch data for notices
    notices: List[Notice] = client.get_notices(users, num_posts=30)
    jobs: List[Job] = client.get_job_listings(users, limit=20)

    # Format using LLM pipeline
    formatter = NoticeFormatter()
    enriched = formatter.format_many(notices, jobs)

    # Save enriched notices (append only new by notice id)
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    final_out_path = os.path.join(data_dir, "final_notices.json")

    existing: List[dict] = []
    if os.path.exists(final_out_path):
        try:
            with open(final_out_path, "r") as f:
                existing = json.load(f) or []
                if not isinstance(existing, list):
                    existing = []
        except Exception:
            existing = []

    existing_ids = {item.get("id") for item in existing if isinstance(item, dict)}
    new_records = [
        rec
        for rec in enriched
        if isinstance(rec, dict) and rec.get("id") not in existing_ids
    ]

    if not new_records:
        print("No new notices to append. File unchanged.")
        print(f"Path: {final_out_path}")
        return

    merged = existing + new_records
    with open(final_out_path, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

    print(f"Appended {len(new_records)} new notices. Saved to: {final_out_path}")

    # ----- Also update job_listings.json (raw) and structured_job_listings.json -----
    base_url = f"{client.BASE_URL}"

    def _common_headers() -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:141.0) Gecko/20100101 Firefox/141.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "x-requester-client": "webapp",
            "x-superset-tenant-id": client.tenant_id,
            "x-superset-tenant-type": client.tenant_type,
            "DNT": "1",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
        }

    # Fetch raw job listings
    raw_jobs: List[Dict[str, Any]] = []
    for u in users:
        url = f"{base_url}/students/{u.uuid}/job_profiles"
        params = {"_loader_": "false"}
        headers = {
            **_common_headers(),
            "Referer": "https://app.joinsuperset.com/students/jobprofiles",
            "Authorization": f"Custom {u.sessionKey}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
        }
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        lst = resp.json()
        if lst:
            raw_jobs.extend(lst)

    # Deduplicate by jobProfileIdentifier while preserving order (latest first)
    raw_jobs_sorted = sorted(
        raw_jobs, key=lambda x: x.get("createdAt", 0), reverse=True
    )
    seen_ids = set()
    dedup_raw_jobs: List[Dict[str, Any]] = []
    for j in raw_jobs_sorted:
        jid = j.get("jobProfileIdentifier")
        if jid and jid not in seen_ids:
            seen_ids.add(jid)
            dedup_raw_jobs.append(j)

    # Add jobDetails using the first user
    detail_user = users[0]
    for j in dedup_raw_jobs:
        jid = j.get("jobProfileIdentifier")
        if not jid:
            continue
        det_url = f"{base_url}/students/{detail_user.uuid}/job_profiles/{jid}"
        det_headers = {
            **_common_headers(),
            "Referer": "https://app.joinsuperset.com/students/jobprofiles",
            "Authorization": f"Custom {detail_user.sessionKey}",
        }
        det_resp = requests.get(
            det_url, headers=det_headers, params={"_loader_": "false"}
        )
        det_resp.raise_for_status()
        j["jobDetails"] = det_resp.json()

    # Update data/job_listings.json (append only new by jobProfileIdentifier)
    job_listings_path = os.path.join(data_dir, "job_listings.json")
    existing_raw: List[dict] = []
    if os.path.exists(job_listings_path):
        try:
            with open(job_listings_path, "r") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    existing_raw = loaded
        except Exception:
            existing_raw = []

    existing_raw_ids = {
        it.get("jobProfileIdentifier") for it in existing_raw if isinstance(it, dict)
    }
    new_raw_records = [
        it
        for it in dedup_raw_jobs
        if it.get("jobProfileIdentifier") not in existing_raw_ids
    ]
    if new_raw_records:
        merged_raw = existing_raw + new_raw_records
        with open(job_listings_path, "w") as f:
            json.dump(merged_raw, f, ensure_ascii=False, indent=4)
        print(
            f"Appended {len(new_raw_records)} new raw jobs. Saved to: {job_listings_path}"
        )
    else:
        print("No new raw jobs to append. job_listings.json unchanged.")

    # Build structured entries from newly added raw ones
    new_structured_jobs: List[Dict[str, Any]] = []
    for raw in new_raw_records:
        job_model: Job = client.structure_job_listing(raw)
        pprint(f"Structured job: {job_model.job_profile} ({job_model.id})")
        new_structured_jobs.append(job_model.model_dump())

    # Update data/structured_job_listings.json (append only new by structured id)
    structured_path = os.path.join(data_dir, "structured_job_listings.json")
    existing_structured: List[dict] = []
    if os.path.exists(structured_path):
        try:
            with open(structured_path, "r") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    existing_structured = loaded
        except Exception:
            existing_structured = []

    existing_struct_ids = {
        it.get("id") for it in existing_structured if isinstance(it, dict)
    }
    new_structured_records = [
        it for it in new_structured_jobs if it.get("id") not in existing_struct_ids
    ]
    if new_structured_records:
        merged_struct = existing_structured + new_structured_records
        with open(structured_path, "w") as f:
            json.dump(merged_struct, f, ensure_ascii=False, indent=4)
        print(
            f"Appended {len(new_structured_records)} new structured jobs. Saved to: {structured_path}"
        )
    else:
        print(
            "No new structured jobs to append. structured_job_listings.json unchanged."
        )


if __name__ == "__main__":
    run_update()
