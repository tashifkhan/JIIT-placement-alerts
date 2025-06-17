"""
Test script to verify MongoDB integration works correctly
"""

import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from .database import MongoDBManager


def test_mongodb_connection():
    """Test MongoDB connection and basic operations"""
    print("🔍 Testing MongoDB Integration...")
    print("=" * 50)

    try:
        # Test connection
        print("\n1. Testing MongoDB connection...")
        db_manager = MongoDBManager()
        print("✅ Successfully connected to MongoDB!")

        # Test saving a sample post
        print("\n2. Testing post saving...")
        sample_title = "Test Job Posting - Python Developer"
        sample_content = """
## Python Developer Position Open

**Posted by:** Test User
**Time:** 2 hours ago

**Eligibility:**
- B.Tech in Computer Science
- Python experience required
- Good CGPA

**⚠️ DEADLINE:** December 31, 2024

This is a test job posting to verify database functionality.
        """

        success, result = db_manager.save_post(
            title=sample_title,
            content=sample_content,
            raw_content="Raw content here",
            author="Test User",
            posted_time="2 hours ago",
        )

        if success:
            print(f"✅ Successfully saved test post with ID: {result}")
        else:
            print(f"ℹ️  Post save result: {result}")

        # Test getting posts stats
        print("\n3. Testing database statistics...")
        stats = db_manager.get_posts_stats()
        print(f"   Total posts: {stats.get('total_posts', 0)}")
        print(f"   Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
        print(f"   Pending to send: {stats.get('pending_to_send', 0)}")

        # Test getting unsent posts
        print("\n4. Testing unsent posts retrieval...")
        unsent_posts = db_manager.get_unsent_posts()
        print(f"   Found {len(unsent_posts)} unsent posts")

        for post in unsent_posts[:3]:  # Show first 3
            print(f"   - {post.get('title', 'No Title')[:50]}...")

        print("\n✅ All MongoDB tests passed!")
        return True

    except Exception as e:
        print(f"❌ MongoDB test failed: {e}")
        return False


def test_formatting_with_database():
    """Test the formatting module with database integration"""
    print("\n🔍 Testing Formatting with Database...")
    print("=" * 40)

    try:
        from modules.formatting import TextFormatter

        formatter = TextFormatter()

        # Check if input file exists
        if not os.path.exists(formatter.input_file):
            print(f"⚠️  Input file not found: {formatter.input_file}")
            print("   Run scraping first to generate input data")
            return False

        print("✅ Input file exists, testing formatting...")
        result = formatter.format_content()

        if isinstance(result, dict) and result.get("success"):
            new_posts = result.get("new_posts", 0)
            total_processed = result.get("total_processed", 0)
            print(f"✅ Formatting completed!")
            print(f"   New posts saved: {new_posts}")
            print(f"   Total processed: {total_processed}")
            return True
        else:
            print(f"❌ Formatting failed: {result}")
            return False

    except Exception as e:
        print(f"❌ Formatting test failed: {e}")
        return False


def test_telegram_with_database():
    """Test the Telegram module with database integration"""
    print("\n🔍 Testing Telegram with Database...")
    print("=" * 40)

    try:
        from modules.telegram import TelegramBot

        telegram_bot = TelegramBot()

        # Test connection
        if not telegram_bot.test_connection():
            print("❌ Telegram connection test failed")
            return False

        print("✅ Telegram connection test passed")

        # Show database stats
        stats = telegram_bot.get_database_stats()

        return True

    except Exception as e:
        print(f"❌ Telegram test failed: {e}")
        return False


if __name__ == "__main__":
    print("🚀 MongoDB Integration Test Suite")
    print("=" * 60)

    # Test MongoDB
    if not test_mongodb_connection():
        print("\n❌ MongoDB tests failed. Exiting.")
        sys.exit(1)

    # Test Formatting with Database
    test_formatting_with_database()

    # Test Telegram with Database
    test_telegram_with_database()

    print("\n🎉 All tests completed!")
