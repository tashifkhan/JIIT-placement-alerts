#!/usr/bin/env python3
"""
Comprehensive Test Suite for Exact Content Matching

This script thoroughly tests the exact content matching functionality
to ensure only posts with 100% identical content are rejected as duplicates.
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from modules.database import MongoDBManager
from modules.webscraping import WebScraper
from modules.formatting import TextFormatter


def test_content_hash_generation():
    """Test content hash generation with various inputs"""
    print("🔐 TESTING CONTENT HASH GENERATION")
    print("=" * 40)

    db_manager = MongoDBManager()

    test_cases = [
        {
            "name": "Identical Content",
            "content1": "Software Engineer Position - Join our team today!",
            "content2": "Software Engineer Position - Join our team today!",
            "should_match": True,
        },
        {
            "name": "Different Content",
            "content1": "Software Engineer Position - Join our team today!",
            "content2": "Data Scientist Position - Join our team today!",
            "should_match": False,
        },
        {
            "name": "Same Content Different Case",
            "content1": "Software Engineer Position - Join our team today!",
            "content2": "software engineer position - join our team today!",
            "should_match": False,  # Exact matching should be case-sensitive
        },
        {
            "name": "Same Content Extra Spaces",
            "content1": "Software Engineer Position - Join our team today!",
            "content2": "Software Engineer Position  -  Join our team today!",
            "should_match": False,  # Exact matching should be whitespace-sensitive
        },
        {
            "name": "Same Content Extra Characters",
            "content1": "Software Engineer Position - Join our team today!",
            "content2": "Software Engineer Position - Join our team today!!",
            "should_match": False,
        },
    ]

    results = []

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['name']}")
        print("-" * 30)

        hash1 = db_manager.create_post_hash(test["content1"])
        hash2 = db_manager.create_post_hash(test["content2"])

        hashes_match = hash1 == hash2
        test_passed = hashes_match == test["should_match"]

        print(f"Content 1: {test['content1'][:50]}...")
        print(f"Content 2: {test['content2'][:50]}...")
        print(f"Hash 1: {hash1[:16]}...")
        print(f"Hash 2: {hash2[:16]}...")
        print(f"Hashes match: {hashes_match}")
        print(f"Expected match: {test['should_match']}")
        print(f"Test result: {'✅ PASS' if test_passed else '❌ FAIL'}")

        results.append(test_passed)

    passed = sum(results)
    total = len(results)
    print(f"\n📊 Hash Generation Tests: {passed}/{total} passed")

    return passed == total


def test_database_exact_matching():
    """Test database duplicate detection with exact matching"""
    print("\n💾 TESTING DATABASE EXACT MATCHING")
    print("=" * 40)

    db_manager = MongoDBManager()

    # Clean up any existing test posts
    cleanup_result = db_manager.collection.delete_many(
        {"title": {"$regex": "EXACT_MATCH_TEST"}}
    )
    if cleanup_result.deleted_count > 0:
        print(f"🧹 Cleaned up {cleanup_result.deleted_count} existing test posts")

    test_scenarios = [
        {
            "name": "Save Original Post",
            "post": {
                "title": "EXACT_MATCH_TEST: Original Job Posting",
                "content": "We are looking for a Python developer with 3+ years experience.",
                "raw_content": "We are looking for a Python developer with 3+ years experience.",
                "author": "HR Team",
                "posted_time": "1 hour ago",
            },
            "should_save": True,
            "should_be_duplicate": False,
        },
        {
            "name": "Save Identical Post",
            "post": {
                "title": "EXACT_MATCH_TEST: Original Job Posting",
                "content": "We are looking for a Python developer with 3+ years experience.",
                "raw_content": "We are looking for a Python developer with 3+ years experience.",
                "author": "HR Team",
                "posted_time": "1 hour ago",
            },
            "should_save": False,
            "should_be_duplicate": True,
        },
        {
            "name": "Save Similar But Different Title",
            "post": {
                "title": "EXACT_MATCH_TEST: Updated Job Posting",  # Different title
                "content": "We are looking for a Python developer with 3+ years experience.",
                "raw_content": "We are looking for a Python developer with 3+ years experience.",
                "author": "HR Team",
                "posted_time": "1 hour ago",
            },
            "should_save": True,
            "should_be_duplicate": False,
        },
        {
            "name": "Save Similar But Different Content",
            "post": {
                "title": "EXACT_MATCH_TEST: Original Job Posting",
                "content": "We are looking for a Python developer with 5+ years experience.",  # Different content
                "raw_content": "We are looking for a Python developer with 5+ years experience.",
                "author": "HR Team",
                "posted_time": "1 hour ago",
            },
            "should_save": True,
            "should_be_duplicate": False,
        },
    ]

    results = []

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\nScenario {i}: {scenario['name']}")
        print("-" * 40)

        post = scenario["post"]

        # Check if duplicate exists
        content_hash = db_manager.create_post_hash(post["content"])
        existing_post = db_manager.post_exists(content_hash)
        is_duplicate = existing_post is not None

        print(f"Content hash: {content_hash[:16]}...")
        print(f"Duplicate found: {is_duplicate}")
        print(f"Expected duplicate: {scenario['should_be_duplicate']}")

        duplicate_check_passed = is_duplicate == scenario["should_be_duplicate"]

        if not is_duplicate:
            # Try to save
            success, result_msg = db_manager.save_post(
                title=post["title"],
                content=post["content"],
                raw_content=post["raw_content"],
                author=post["author"],
                posted_time=post["posted_time"],
            )
            print(f"Save result: {success}")
            print(f"Expected save: {scenario['should_save']}")

            save_check_passed = success == scenario["should_save"]
        else:
            save_check_passed = True  # If duplicate detected, we don't try to save
            print("Save skipped (duplicate detected)")

        scenario_passed = duplicate_check_passed and save_check_passed
        print(f"Scenario result: {'✅ PASS' if scenario_passed else '❌ FAIL'}")

        results.append(scenario_passed)

    # Clean up test posts
    cleanup_result = db_manager.collection.delete_many(
        {"title": {"$regex": "EXACT_MATCH_TEST"}}
    )
    print(f"\n🧹 Cleaned up {cleanup_result.deleted_count} test posts")

    passed = sum(results)
    total = len(results)
    print(f"\n📊 Database Exact Matching Tests: {passed}/{total} passed")

    return passed == total


def test_webscraping_integration():
    """Test integration with webscraping module"""
    print("\n🕷️ TESTING WEBSCRAPING INTEGRATION")
    print("=" * 40)

    try:
        # Create a webscraper instance (but don't actually scrape)
        scraper = WebScraper()

        # Test the process_single_post method with mock data
        test_content = """
Test Job Posting for Integration
Posted by HR Team
2 hours ago
We are seeking a qualified candidate for our software engineering position.
Requirements:
- Bachelor's degree in Computer Science
- 3+ years of experience
- Proficiency in Python
        """.strip()

        print("Testing process_single_post method...")
        print(f"Test content: {test_content[:100]}...")

        # First processing should save
        result1 = scraper.process_single_post(test_content, 1)
        print(f"First processing result: {result1}")

        # Second processing should detect duplicate
        result2 = scraper.process_single_post(test_content, 2)
        print(f"Second processing result: {result2}")

        # Test passed if first saves and second detects duplicate
        test_passed = (result1 == "saved") and (result2 == "duplicate")

        print(f"Integration test: {'✅ PASS' if test_passed else '❌ FAIL'}")

        # Clean up any test posts created
        db_manager = MongoDBManager()
        cleanup_result = db_manager.collection.delete_many(
            {"title": {"$regex": "Test Job Posting"}}
        )
        if cleanup_result.deleted_count > 0:
            print(f"🧹 Cleaned up {cleanup_result.deleted_count} test posts")

        return test_passed

    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False


def main():
    """Run all exact matching tests"""
    print("🧪 EXACT CONTENT MATCHING TEST SUITE")
    print("=" * 50)
    print(
        "Testing that ONLY posts with 100% identical content are rejected as duplicates"
    )
    print("=" * 50)

    tests = [
        ("Content Hash Generation", test_content_hash_generation),
        ("Database Exact Matching", test_database_exact_matching),
        ("Webscraping Integration", test_webscraping_integration),
    ]

    passed_tests = 0
    total_tests = len(tests)

    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            if test_func():
                passed_tests += 1
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")

    print(f"\n{'='*60}")
    print("🏁 FINAL TEST RESULTS")
    print("=" * 60)
    print(f"Tests passed: {passed_tests}/{total_tests}")

    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Exact content matching is working correctly")
        print("✅ Only 100% identical content will be rejected as duplicates")
        return 0
    else:
        print("⚠️ SOME TESTS FAILED!")
        print("❌ Exact content matching may not be working correctly")
        return 1


if __name__ == "__main__":
    exit(main())
