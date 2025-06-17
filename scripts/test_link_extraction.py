#!/usr/bin/env python3
"""
Test script for the link extraction functionality in the TextFormatter class
"""

import sys
import os
import re

# Add the parent directory to sys.path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Create a mock MongoDBManager class to avoid database dependency
class MockDBManager:
    def __init__(self):
        pass


# Patch the module imports
import importlib.util
import types

# Import the re module which we need
sys.modules["re"] = re

# Create a mock for database module
mock_db_module = types.ModuleType("database")
mock_db_module.MongoDBManager = MockDBManager
sys.modules["modules.database"] = mock_db_module

# Now we can import TextFormatter
from modules.formatting import TextFormatter


def test_link_extraction():
    """Test the link extraction functionality"""
    formatter = TextFormatter()
    # Replace the db_manager with our mock
    formatter.db_manager = MockDBManager()
    # Debug: Print to confirm the object was created
    print("TextFormatter instance created successfully")

    # Test cases
    test_cases = [
        # Plain URL in text
        {
            "input": "Check out this website: https://example.com for more information",
            "expected": "Check out this website: https://example.com for more information\nhttps://example.com",
        },
        # HTML link
        {
            "input": "Click <a href='https://register.example.com'>here</a> to register",
            "expected": "Click <a href='https://register.example.com'>here</a> to register\nhttps://register.example.com",
        },
        # Click here text with a URL
        {
            "input": "Click here to apply: https://apply.example.com",
            "expected": "Click here to apply: https://apply.example.com\nhttps://apply.example.com",
        },
        # Multiple URLs in one line
        {
            "input": "Main site: https://main.example.com and docs: https://docs.example.com",
            "expected": "Main site: https://main.example.com and docs: https://docs.example.com\nhttps://main.example.com\nhttps://docs.example.com",
        },
        # Link already on its own line
        {
            "input": "https://standalone.example.com",
            "expected": "https://standalone.example.com",
        },
        # URL with parameters
        {
            "input": "Register at https://example.com/register?id=123&source=email",
            "expected": "Register at https://example.com/register?id=123&source=email\nhttps://example.com/register?id=123&source=email",
        },
        # HTML link with attributes
        {
            "input": '<a href="https://example.com/path" class="btn" target="_blank">Click me</a>',
            "expected": '<a href="https://example.com/path" class="btn" target="_blank">Click me</a>\nhttps://example.com/path',
        },
        # URL with special characters
        {
            "input": "Check this: https://example.com/search?q=job+postings&category=tech",
            "expected": "Check this: https://example.com/search?q=job+postings&category=tech\nhttps://example.com/search?q=job+postings&category=tech",
        },
        # Multiple lines with URLs
        {
            "input": "First link: https://example.com/first\nSecond link: https://example.com/second",
            "expected": "First link: https://example.com/first\nhttps://example.com/first\nSecond link: https://example.com/second\nhttps://example.com/second",
        },
        # www URL format
        {
            "input": "Visit www.example.com for more details",
            "expected": "Visit www.example.com for more details\nwww.example.com",
        },
        # Subdomain without http/www prefix (like apple.adobe)
        {
            "input": "Please register at careers.adobe.com for the webinar",
            "expected": "Please register at careers.adobe.com for the webinar\ncareers.adobe.com",
        },
        # Subdomain with three parts (like team.hiring.justpay)
        {
            "input": "Apply at team.hiring.justpay.in before the deadline",
            "expected": "Apply at team.hiring.justpay.in before the deadline\nteam.hiring.justpay.in",
        },
        # Multiple subdomains in text
        {
            "input": "Check both jobs.microsoft.com and careers.google.com for openings",
            "expected": "Check both jobs.microsoft.com and careers.google.com for openings\njobs.microsoft.com\ncareers.google.com",
        },
        # False positive tests (should not extract these)
        {
            "input": "The software version is 1.2.3 and it was released on 17.06.2023",
            "expected": "The software version is 1.2.3 and it was released on 17.06.2023",
        },
        # Standalone subdomain
        {"input": "careers.adobe.com", "expected": "careers.adobe.com"},
        # Different TLD
        {
            "input": "Visit campus.iit.ac.in for more information",
            "expected": "Visit campus.iit.ac.in for more information\ncampus.iit.ac.in",
        },
    ]

    # Run tests
    passed = 0
    failed = 0

    print("Starting tests...")

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest #{i}: Processing input: {test['input']}")
        try:
            result = formatter.extract_and_add_links(test["input"])
            print(f"Result: {result}")
            if result.strip() == test["expected"].strip():
                print(f"✅ Test #{i} passed")
                passed += 1
            else:
                print(f"❌ Test #{i} failed")
                print(f"  Expected: {test['expected']}")
                print(f"  Got: {result}")
                failed += 1
        except Exception as e:
            print(f"❌ Test #{i} threw an exception: {e}")
            failed += 1

    # Summary
    print(f"\nResults: {passed} passed, {failed} failed")
    return passed, failed


if __name__ == "__main__":
    print("Testing link extraction functionality...")
    test_link_extraction()
