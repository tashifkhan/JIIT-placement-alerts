"""
Manual User Registration Script

This script allows you to manually add users to the database for testing purposes.
"""

import os
import sys
from datetime import datetime


project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from modules.database import MongoDBManager


def add_test_user():
    """Add a test user manually"""
    try:
        db = MongoDBManager()

        print("Add a test user to the database")
        print("-" * 40)

        user_id = input("Enter Telegram User ID (numeric): ").strip()
        if not user_id.isdigit():
            print("❌ User ID must be numeric")
            return False

        user_id = int(user_id)
        username = input("Enter username (without @): ").strip()
        first_name = input("Enter first name: ").strip()
        last_name = input("Enter last name (optional): ").strip()

        success, message = db.add_user(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name if last_name else None,
        )

        if success:
            print(f"✅ User {user_id} (@{username}) added successfully!")
        else:
            print(f"❌ Failed to add user: {message}")

        return success

    except Exception as e:
        print(f"❌ Error adding user: {e}")
        return False


def list_users():
    """List all registered users"""
    try:
        db = MongoDBManager()
        users = db.get_all_users()

        if not users:
            print("No users registered yet.")
            return

        print(f"\n📋 Registered Users ({len(users)} total):")
        print("-" * 60)

        for i, user in enumerate(users, 1):
            user_id = user.get("user_id", "Unknown")
            username = user.get("username", "Unknown")
            first_name = user.get("first_name", "Unknown")
            last_name = user.get("last_name", "")
            created_at = user.get("created_at", datetime.utcnow())
            is_active = user.get("is_active", False)

            status = "✅ Active" if is_active else "❌ Inactive"
            full_name = f"{first_name} {last_name}".strip()

            print(f"{i:2d}. {full_name} (@{username})")
            print(f"    ID: {user_id} | Status: {status}")
            print(f"    Joined: {created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print()

    except Exception as e:
        print(f"❌ Error listing users: {e}")


def show_stats():
    """Show user statistics"""
    try:
        db = MongoDBManager()
        stats = db.get_users_stats()

        print("\n📊 User Statistics:")
        print("-" * 30)
        print(f"Total users: {stats.get('total_users', 0)}")
        print(f"Active users: {stats.get('active_users', 0)}")
        print(f"Inactive users: {stats.get('inactive_users', 0)}")

    except Exception as e:
        print(f"❌ Error getting stats: {e}")


def main():
    """Main menu"""
    while True:
        print("\n" + "=" * 50)
        print("SuperSet Telegram Bot - User Management")
        print("=" * 50)

        print("1. Add test user")
        print("2. List all users")
        print("3. Show statistics")
        print("4. Exit")

        choice = input("\nSelect an option (1-4): ").strip()

        if choice == "1":
            add_test_user()
        elif choice == "2":
            list_users()
        elif choice == "3":
            show_stats()
        elif choice == "4":
            print("Goodbye!")
            break
        else:
            print("❌ Invalid choice. Please select 1-4.")


if __name__ == "__main__":
    main()
