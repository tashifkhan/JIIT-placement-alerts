"""
Test script for SuperSet Telegram Bot

This script tests the user management functionality and database connections.
"""

import os
import sys
from datetime import datetime

# Add the project root to the path (parent directory of scripts)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from modules.database import MongoDBManager
from modules.telegram import TelegramBot


def test_database_connection():
    """Test MongoDB connection"""
    print("🔍 Testing MongoDB connection...")
    try:
        db = MongoDBManager()
        print("✅ MongoDB connection successful")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False


def test_user_management():
    """Test user management functions"""
    print("\n🔍 Testing user management...")
    try:
        db = MongoDBManager()

        # Test adding a user
        test_user_id = 12345678
        test_username = "testuser"

        success, message = db.add_user(
            user_id=test_user_id,
            username=test_username,
            first_name="Test",
            last_name="User",
        )

        if success:
            print("✅ User added successfully")
        else:
            print(f"ℹ️  User already exists: {message}")

        # Test getting users
        users = db.get_all_users()
        print(f"✅ Found {len(users)} active users")

        # Test user stats
        stats = db.get_users_stats()
        print(f"📊 User stats: {stats}")

        return True

    except Exception as e:
        print(f"❌ User management test failed: {e}")
        return False


def test_telegram_bot():
    """Test Telegram bot configuration"""
    print("\n🔍 Testing Telegram bot configuration...")
    try:
        bot = TelegramBot()
        if bot.test_connection():
            print("✅ Telegram bot configuration is valid")
            return True
        else:
            print("❌ Telegram bot configuration failed")
            return False
    except Exception as e:
        print(f"❌ Telegram bot test failed: {e}")
        return False


def show_environment_check():
    """Show environment variables status"""
    print("\n🔍 Environment Variables Check:")

    required_vars = ["MONGO_CONNECTION_STR", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]

    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Show only first few characters for security
            masked_value = value[:8] + "..." if len(value) > 8 else value
            print(f"✅ {var}: {masked_value}")
        else:
            print(f"❌ {var}: Not set")


def main():
    """Run all tests"""
    print("🧪 SuperSet Telegram Bot - Test Suite")
    print("=" * 50)

    show_environment_check()

    # Run tests
    tests = [
        ("Database Connection", test_database_connection),
        ("User Management", test_user_management),
        ("Telegram Bot", test_telegram_bot),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)

    passed = 0
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
        if result:
            passed += 1

    print(f"\nOverall: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("\n🎉 All tests passed! The bot is ready to run.")
        print("\nNext steps:")
        print("1. Run 'python app.py' to start the bot server")
        print("2. Send /start to your bot on Telegram to register")
        print("3. The bot will automatically run 3 times a day to send updates")
    else:
        print("\n⚠️  Some tests failed. Please fix the issues before running the bot.")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
