#!/usr/bin/env python3
"""
Script to fetch all posts from SuperSet and update MongoDB entries with documents
"""
import os
import json
from typing import List, Dict, Any
from dotenv import load_dotenv
from pprint import pprint

from scrapper import SupersetClient, User, Job, Document
from database import MongoDBManager
from config import safe_print

load_dotenv()


def update_all_jobs_with_documents():
    """Fetch all jobs from SuperSet and update MongoDB with document information"""
    
    client = SupersetClient()
    db = MongoDBManager()
    
    # Login multiple users
    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    ece_email = os.getenv("ECE_EMAIL")
    ece_password = os.getenv("ECE_ENCRYPTION_PASSWORD")
    
    if not all([cse_email, cse_password, ece_email, ece_password]):
        safe_print("❌ Missing credentials in environment variables")
        return
    
    try:
        # Login both users
        cse_user = client.login(cse_email, cse_password)
        ece_user = client.login(ece_email, ece_password)
        users = [cse_user, ece_user]
        
        safe_print(f"✅ Logged in as {cse_user.name} and {ece_user.name}")
        
        # Fetch ALL job listings (no limit)
        safe_print("📥 Fetching all job listings from SuperSet...")
        all_jobs = client.get_job_listings(users, limit=None)
        safe_print(f"📊 Found {len(all_jobs)} jobs total")
        
        # Update MongoDB with new job data including documents
        inserted_count = 0
        updated_count = 0
        error_count = 0
        
        safe_print("💾 Updating MongoDB with job data and documents...")
        
        for i, job in enumerate(all_jobs, 1):
            try:
                # Convert job to dict for MongoDB storage
                job_dict = job.model_dump()
                
                # Log progress
                if i % 10 == 0 or i == len(all_jobs):
                    safe_print(f"Processing job {i}/{len(all_jobs)}: {job.job_profile} at {job.company}")
                
                # Log document info
                if job.documents:
                    safe_print(f"  📄 Found {len(job.documents)} documents:")
                    for doc in job.documents:
                        safe_print(f"    - {doc.name} (URL: {'✅' if doc.url else '❌'})")
                
                # Upsert to MongoDB
                success, info = db.upsert_structured_job(job_dict)
                
                if success:
                    if info == "updated":
                        updated_count += 1
                    else:
                        inserted_count += 1
                else:
                    safe_print(f"❌ Failed to save job {job.id}: {info}")
                    error_count += 1
                    
            except Exception as e:
                safe_print(f"❌ Error processing job {job.id}: {e}")
                error_count += 1
        
        # Print summary
        safe_print("\n" + "="*50)
        safe_print("📊 SUMMARY:")
        safe_print(f"  Total jobs processed: {len(all_jobs)}")
        safe_print(f"  New jobs inserted: {inserted_count}")
        safe_print(f"  Existing jobs updated: {updated_count}")
        safe_print(f"  Errors: {error_count}")
        safe_print("="*50)
        
        # Show sample of jobs with documents
        jobs_with_docs = [job for job in all_jobs if job.documents]
        if jobs_with_docs:
            safe_print(f"\n📄 Sample jobs with documents ({len(jobs_with_docs)} total):")
            for job in jobs_with_docs[:3]:  # Show first 3
                safe_print(f"  🏢 {job.job_profile} at {job.company}")
                for doc in job.documents[:2]:  # Show first 2 docs
                    safe_print(f"    📎 {doc.name}")
                    if doc.url:
                        safe_print(f"      🔗 URL available")
                    else:
                        safe_print(f"      ❌ No URL")
        
    except Exception as e:
        safe_print(f"❌ Fatal error: {e}")
        
    finally:
        db.close_connection()


def update_existing_jobs_with_documents():
    """Update existing jobs in MongoDB that don't have document information"""
    
    client = SupersetClient()
    db = MongoDBManager()
    
    try:
        # Login users
        cse_email = os.getenv("CSE_EMAIL")
        cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
        
        if not cse_email or not cse_password:
            safe_print("❌ Missing CSE credentials")
            return
            
        user = client.login(cse_email, cse_password)
        safe_print(f"✅ Logged in as {user.name}")
        
        # Get all existing jobs from MongoDB
        safe_print("📥 Fetching existing jobs from MongoDB...")
        existing_jobs = db.get_all_jobs(limit=1000)  # Get more jobs
        safe_print(f"📊 Found {len(existing_jobs)} existing jobs in MongoDB")
        
        # Filter jobs that don't have documents or have empty documents
        jobs_needing_update = []
        for job in existing_jobs:
            if not job.get("documents") or len(job.get("documents", [])) == 0:
                jobs_needing_update.append(job)
        
        safe_print(f"🔄 {len(jobs_needing_update)} jobs need document updates")
        
        if not jobs_needing_update:
            safe_print("✅ All jobs already have document information")
            return
        
        updated_count = 0
        error_count = 0
        
        for i, job in enumerate(jobs_needing_update, 1):
            try:
                job_id = job.get("id")
                if not job_id:
                    continue
                    
                safe_print(f"🔄 Updating job {i}/{len(jobs_needing_update)}: {job.get('job_profile', 'Unknown')} at {job.get('company', 'Unknown')}")
                
                # Fetch fresh job details from SuperSet
                job_details = client.get_job_details(user, job_id)
                
                # Extract documents
                documents = []
                for doc in job_details.get("documents", []):
                    if doc.get("name") and doc.get("identifier"):
                        doc_url = client.get_document_url(user, job_id, doc.get("identifier"))
                        documents.append({
                            "name": doc.get("name"),
                            "identifier": doc.get("identifier"),
                            "url": doc_url
                        })
                
                if documents:
                    safe_print(f"  📄 Found {len(documents)} documents")
                    for doc in documents:
                        safe_print(f"    - {doc['name']} (URL: {'✅' if doc['url'] else '❌'})")
                
                # Update the job in MongoDB
                updated_job = {**job, "documents": documents}
                success, info = db.upsert_structured_job(updated_job)
                
                if success:
                    updated_count += 1
                else:
                    safe_print(f"❌ Failed to update job {job_id}: {info}")
                    error_count += 1
                    
            except Exception as e:
                safe_print(f"❌ Error updating job {job.get('id', 'Unknown')}: {e}")
                error_count += 1
        
        safe_print(f"\n✅ Update complete: {updated_count} jobs updated, {error_count} errors")
        
    except Exception as e:
        safe_print(f"❌ Fatal error: {e}")
        
    finally:
        db.close_connection()


def main():
    """Main function with options"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--existing-only":
        safe_print("🔄 Updating existing jobs with documents...")
        update_existing_jobs_with_documents()
    else:
        safe_print("🔄 Fetching all jobs and updating MongoDB...")
        update_all_jobs_with_documents()


if __name__ == "__main__":
    main()
