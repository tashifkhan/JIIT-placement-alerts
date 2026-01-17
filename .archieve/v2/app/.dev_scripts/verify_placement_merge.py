import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from database import MongoDBManager
from placement_stats import PlacementOffer, RolePackage, Student


# Mock data for testing
def create_mock_offer(company, roles, students):
    return {
        "company": company,
        "roles": roles,
        "students_selected": students,
        "number_of_offers": len(students),
        "email_subject": f"Offer from {company}",
        "email_sender": "hr@example.com",
        "saved_at": datetime.utcnow(),
    }


def run_verification():
    print("--- Starting Verification for Placement Merge Logic ---")

    # Initialize DB Manager
    # NOTE: This assumes a local MongoDB instance is running and accessible via env vars
    # If not, we might need to mock the DB connection or use a test DB
    try:
        db_manager = MongoDBManager()
        print("Connected to MongoDB")
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        return

    # Use a specific test collection to avoid messing up real data
    # For this script, we'll just use the real collection but with a specific test company name
    # that we can clean up later.
    TEST_COMPANY = "TEST_COMPANY_VERIFICATION_123"

    # Cleanup previous runs
    db_manager.placement_offers_collection.delete_many({"company": TEST_COMPANY})
    print(f"Cleaned up previous data for {TEST_COMPANY}")

    # Scenario 1: New Company
    print("\n--- Scenario 1: New Company ---")
    roles_1 = [{"role": "SDE", "package": 10.0}]
    students_1 = [
        {"name": "Alice", "enrollment_number": "E001", "role": "SDE", "package": 10.0},
        {"name": "Bob", "enrollment_number": "E002", "role": "SDE", "package": 10.0},
    ]
    offer_1 = create_mock_offer(TEST_COMPANY, roles_1, students_1)

    result_1 = db_manager.save_placement_offers([offer_1])
    print(f"Result 1: {result_1}")

    doc = db_manager.placement_offers_collection.find_one({"company": TEST_COMPANY})
    if doc and len(doc["students_selected"]) == 2:
        print("PASS: New company created with 2 students")
    else:
        print("FAIL: New company creation failed")

    # Scenario 2: Existing Company, New Students
    print("\n--- Scenario 2: Existing Company, New Students ---")
    roles_2 = [{"role": "SDE", "package": 10.0}]
    students_2 = [
        {"name": "Charlie", "enrollment_number": "E003", "role": "SDE", "package": 10.0}
    ]
    offer_2 = create_mock_offer(TEST_COMPANY, roles_2, students_2)

    result_2 = db_manager.save_placement_offers([offer_2])
    print(f"Result 2: {result_2}")

    doc = db_manager.placement_offers_collection.find_one({"company": TEST_COMPANY})
    if doc and len(doc["students_selected"]) == 3:
        print("PASS: Students merged (2 + 1 = 3)")
    else:
        print(
            f"FAIL: Student merge failed. Count: {len(doc['students_selected']) if doc else 0}"
        )

    # Scenario 3: Existing Company, Overlapping Student (Higher Package)
    print(
        "\n--- Scenario 3: Existing Company, Overlapping Student (Higher Package) ---"
    )
    roles_3 = [{"role": "SDE", "package": 12.0}]  # Package increased
    students_3 = [
        {
            "name": "Alice",
            "enrollment_number": "E001",
            "role": "SDE",
            "package": 12.0,
        }  # Alice gets a raise
    ]
    offer_3 = create_mock_offer(TEST_COMPANY, roles_3, students_3)

    result_3 = db_manager.save_placement_offers([offer_3])
    print(f"Result 3: {result_3}")

    doc = db_manager.placement_offers_collection.find_one({"company": TEST_COMPANY})
    alice = next(
        (s for s in doc["students_selected"] if s["enrollment_number"] == "E001"), None
    )

    if alice and alice["package"] == 12.0:
        print("PASS: Alice's package updated to 12.0")
    else:
        print(
            f"FAIL: Alice's package update failed. Value: {alice['package'] if alice else 'None'}"
        )

    # Scenario 4: Existing Company, Overlapping Student (Lower Package)
    print("\n--- Scenario 4: Existing Company, Overlapping Student (Lower Package) ---")
    roles_4 = [
        {"role": "SDE", "package": 8.0}
    ]  # Lower package offer (maybe mistake or old data)
    students_4 = [
        {
            "name": "Bob",
            "enrollment_number": "E002",
            "role": "SDE",
            "package": 8.0,
        }  # Bob shouldn't be downgraded
    ]
    offer_4 = create_mock_offer(TEST_COMPANY, roles_4, students_4)

    result_4 = db_manager.save_placement_offers([offer_4])
    print(f"Result 4: {result_4}")

    doc = db_manager.placement_offers_collection.find_one({"company": TEST_COMPANY})
    bob = next(
        (s for s in doc["students_selected"] if s["enrollment_number"] == "E002"), None
    )

    if bob and bob["package"] == 10.0:  # Should remain 10.0
        print("PASS: Bob's package preserved at 10.0")
    else:
        print(
            f"FAIL: Bob's package incorrect. Value: {bob['package'] if bob else 'None'}"
        )

    # Scenario 5: Duplicate Company Entries (Handling Exception)
    print("\n--- Scenario 5: Duplicate Company Entries ---")
    DUPLICATE_COMPANY = "TEST_COMPANY_DUPLICATE"

    # Clean up first
    db_manager.placement_offers_collection.delete_many({"company": DUPLICATE_COMPANY})

    # Manually insert two documents
    doc1 = {
        "company": DUPLICATE_COMPANY,
        "roles": [{"role": "SDE", "package": 10.0}],
        "students_selected": [
            {"name": "Old", "enrollment_number": "OLD1", "role": "SDE", "package": 10.0}
        ],
        "number_of_offers": 1,
        "updated_at": datetime(2023, 1, 1),
    }
    doc2 = {
        "company": DUPLICATE_COMPANY,
        "roles": [{"role": "SDE", "package": 10.0}],
        "students_selected": [
            {
                "name": "Newer",
                "enrollment_number": "NEW1",
                "role": "SDE",
                "package": 10.0,
            }
        ],
        "number_of_offers": 1,
        "updated_at": datetime(2023, 1, 2),  # More recent
    }

    res1 = db_manager.placement_offers_collection.insert_one(doc1)
    res2 = db_manager.placement_offers_collection.insert_one(doc2)
    print(f"Inserted duplicates: {res1.inserted_id} (old), {res2.inserted_id} (new)")

    # Update with new student
    roles_5 = [{"role": "SDE", "package": 10.0}]
    students_5 = [
        {
            "name": "Latest",
            "enrollment_number": "LATEST1",
            "role": "SDE",
            "package": 10.0,
        }
    ]
    offer_5 = create_mock_offer(DUPLICATE_COMPANY, roles_5, students_5)

    result_5 = db_manager.save_placement_offers([offer_5])
    print(f"Result 5: {result_5}")

    # Check that the NEWER document was updated
    updated_doc = db_manager.placement_offers_collection.find_one(
        {"_id": res2.inserted_id}
    )
    old_doc = db_manager.placement_offers_collection.find_one({"_id": res1.inserted_id})

    if updated_doc and len(updated_doc["students_selected"]) == 2:  # Newer + Latest
        print("PASS: Merged into the most recent document")
    else:
        print(
            f"FAIL: Did not merge into most recent. Count: {len(updated_doc['students_selected']) if updated_doc else 0}"
        )

    if old_doc and len(old_doc["students_selected"]) == 1:
        print("PASS: Old document left untouched")
    else:
        print("FAIL: Old document was modified")

    # Cleanup
    print("\n--- Cleanup ---")
    db_manager.placement_offers_collection.delete_many({"company": TEST_COMPANY})
    db_manager.placement_offers_collection.delete_many({"company": DUPLICATE_COMPANY})
    print("Test data removed")


if __name__ == "__main__":
    run_verification()
