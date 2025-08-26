import os
import json
from typing import List, Dict, Any
import requests
from dotenv import load_dotenv
from pprint import pprint

from scrapper import SupersetClient, User, Notice, Job
from notice_formater import NoticeFormatter
from database import MongoDBManager
from placement_stats import update_placement_records


load_dotenv()


def run_update() -> None:
    client = SupersetClient()
    db = MongoDBManager()

    # Login multiple users (CSE, ECE)
    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    ece_email = os.getenv("ECE_EMAIL")
    ece_password = os.getenv("ECE_ENCRYPTION_PASSWORD")

    cse_user: User = client.login(cse_email, cse_password)
    ece_user: User = client.login(ece_email, ece_password)

    users: List[User] = [cse_user, ece_user]

    # Fetch data for notices
    notices: List[Notice] = client.get_notices(users, num_posts=10)
    pprint(notices)
    jobs: List[Job] = client.get_job_listings(users, limit=20)

    # Format using LLM pipeline
    formatter = NoticeFormatter()
    enriched = formatter.format_many(notices, jobs)

    # Persist enriched notices into DB (save only new by notice id)
    inserted_notices = 0
    for rec in enriched:
        if not isinstance(rec, dict):
            continue
        success, info = db.save_notice(rec)
        
        if success:
            inserted_notices += 1
        else:
            # ignore already exists and log other errors
            if info and "already exists" in str(info).lower():
                pass
            else:
                pprint(f"Notice save error: {info}")

    if inserted_notices:
        print(f"Inserted {inserted_notices} new notices into DB")
    else:
        print("No new notices to insert into DB.")

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

    # Convert deduped raw jobs into structured jobs and upsert into DB
    inserted_jobs = 0
    updated_jobs = 0
    for raw in dedup_raw_jobs:
        try:
            job_model: Job = client.structure_job_listing(raw)
            structured = job_model.model_dump()
            pprint(f"Structured job: {job_model.job_profile} ({job_model.id})")
            success, info = db.upsert_structured_job(structured)
            if success:
                if info == "updated":
                    updated_jobs += 1
                else:
                    inserted_jobs += 1
            else:
                pprint(f"Failed to upsert structured job {structured.get('id')}: {info}")

        except Exception as e:
            pprint(f"Error structuring/upserting job: {e}")

    print(f"Structured jobs - inserted: {inserted_jobs}, updated: {updated_jobs}")

    # placement updating
    update_placement_records()


if __name__ == "__main__":
    run_update()
