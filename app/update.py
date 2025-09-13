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


def run_update() -> dict:
    """Run update pipeline and return per-step success status.

    Returns a dict with keys: notices, jobs, placements indicating whether
    each sub-step completed without an unhandled exception.
    """
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
    notices: List[Notice] = [
        notice
        for notice in client.get_notices(users, num_posts=20)
        if not db.notice_exists(notice.id)
    ]
    pprint(notices)
    jobs: List[Job] = client.get_job_listings(users, limit=10)

    # Format using LLM pipeline
    formatter = NoticeFormatter()
    enriched = formatter.format_many(notices, jobs)  # type: ignore

    # Track step success flags
    notices_success = False
    jobs_success = False
    placements_success = False

    # Persist enriched notices into DB (save only new by notice id)
    inserted_notices = 0
    try:
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

        notices_success = True
    except Exception as e:
        pprint(f"Notices processing failed: {e}")
        notices_success = False

    # Process jobs and upsert into DB - using the jobs already fetched above
    inserted_jobs = 0
    updated_jobs = 0
    try:
        for job_model in jobs:
            try:
                structured = job_model.model_dump()
                pprint(f"Structured job: {job_model.job_profile} ({job_model.id})")
                success, info = db.upsert_structured_job(structured)
                if success:
                    if info == "updated":
                        updated_jobs += 1
                    else:
                        inserted_jobs += 1
                else:
                    pprint(
                        f"Failed to upsert structured job {structured.get('id')}: {info}"
                    )

            except Exception as e:
                pprint(f"Error structuring/upserting job: {e}")

        print(f"Structured jobs - inserted: {inserted_jobs}, updated: {updated_jobs}")
        jobs_success = True
    except Exception as e:
        pprint(f"Jobs processing failed: {e}")
        jobs_success = False

    # placement updating
    try:
        update_placement_records()
        placements_success = True
    except Exception as e:
        pprint(f"Placement updating failed: {e}")
        placements_success = False

    return {
        "notices": notices_success,
        "jobs": jobs_success,
        "placements": placements_success,
    }


if __name__ == "__main__":
    run_update()
