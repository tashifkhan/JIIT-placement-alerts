#!/usr/bin/env python3
"""
Test script to demonstrate document storage functionality
"""
import os
import json
from dotenv import load_dotenv
from scrapper import SupersetClient
from database import MongoDBManager

load_dotenv()

def test_document_functionality():
    """Test the document storage functionality"""
    client = SupersetClient()
    db = MongoDBManager()
    
    # Login
    cse_email = os.getenv("CSE_EMAIL")
    cse_password = os.getenv("CSE_ENCRYPTION_PASSWORD")
    
    if not cse_email or not cse_password:
        print("❌ Missing CSE credentials in environment variables")
        return
    
    try:
        user = client.login(cse_email, cse_password)
        print(f"✅ Logged in as {user.name} ({user.username})")
        
        # Fetch job listings with documents
        print("📥 Fetching job listings with documents...")
        jobs = client.get_job_listings([user], limit=5)
        
        print(f"📊 Found {len(jobs)} jobs")
        
        # Display jobs with documents
        for job in jobs:
            print(f"\n🏢 Job: {job.job_profile} at {job.company}")
            print(f"   ID: {job.id}")
            
            if job.documents:
                print(f"   📄 Documents ({len(job.documents)}):")
                for doc in job.documents:
                    print(f"     - {doc.name}")
                    print(f"       ID: {doc.identifier}")
                    if doc.url:
                        print(f"       URL: {doc.url[:100]}...")
                    else:
                        print(f"       URL: Not available")
            else:
                print("   📄 No documents found")
            
            # Save to MongoDB
            structured = job.model_dump()
            success, info = db.upsert_structured_job(structured)
            if success:
                print(f"   ✅ Saved to MongoDB: {info}")
            else:
                print(f"   ❌ Failed to save: {info}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    finally:
        db.close_connection()

if __name__ == "__main__":
    test_document_functionality()
