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
    notices: List[Notice] = [notice for notice in client.get_notices(users, num_posts=20) if not db.notice_exists(notice.id)]
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

    # Process jobs and upsert into DB - using the jobs already fetched above
    inserted_jobs = 0
    updated_jobs = 0
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
                pprint(f"Failed to upsert structured job {structured.get('id')}: {info}")

        except Exception as e:
            pprint(f"Error structuring/upserting job: {e}")

    print(f"Structured jobs - inserted: {inserted_jobs}, updated: {updated_jobs}")

    # placement updating
    update_placement_records()


if __name__ == "__main__":
    run_update()
