"""
Test script to verify the complete workflow with MongoDB integration
"""

import os
import sys

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def test_complete_workflow():
    """Test the complete workflow: scraping -> formatting -> telegram"""
    print("🚀 Testing Complete Workflow with MongoDB")
    print("=" * 60)

    # Test 1: Database Connection
    print("\n1️⃣  Testing Database Connection...")
    try:
        from modules.database import MongoDBManager

        db_manager = MongoDBManager()
        stats = db_manager.get_posts_stats()
        print(f"✅ Database connected successfully!")
        print(f"   Current posts in database: {stats.get('total_posts', 0)}")
        print(f"   Unsent posts: {stats.get('pending_to_send', 0)}")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

    # Test 2: Check if we have scraped data
    print("\n2️⃣  Checking for scraped data...")
    output_dir = os.path.join(project_root, "output")
    job_posts_file = os.path.join(output_dir, "job_posts.txt")

    if os.path.exists(job_posts_file):
        with open(job_posts_file, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"✅ Found scraped data ({len(content)} characters)")
    else:
        print("⚠️  No scraped data found. Run scraping first:")
        print("   python main_modular.py scrape")
        return False

    # Test 3: Test Formatting (which saves to database)
    print("\n3️⃣  Testing Formatting with Database...")
    try:
        from modules.formatting import TextFormatter

        formatter = TextFormatter()
        result = formatter.format_content()

        if isinstance(result, dict) and result.get("success"):
            new_posts = result.get("new_posts", 0)
            total_processed = result.get("total_processed", 0)
            print(f"✅ Formatting completed!")
            print(f"   New posts saved: {new_posts}")
            print(f"   Total processed: {total_processed}")
        else:
            print(f"❌ Formatting failed: {result}")
            return False
    except Exception as e:
        print(f"❌ Formatting test failed: {e}")
        return False

    # Test 4: Test Telegram (which reads from database)
    print("\n4️⃣  Testing Telegram Integration...")
    try:
        from modules.telegram import TelegramBot

        telegram_bot = TelegramBot()

        # Test connection
        if not telegram_bot.test_connection():
            print("❌ Telegram connection failed")
            return False

        print("✅ Telegram connection successful")

        # Show database stats
        telegram_bot.get_database_stats()

        # Test sending (comment out if you don't want to actually send)
        print("\n   Testing message sending...")
        print("   (This will send actual messages to your Telegram chat)")

        confirm = input("   Send messages to Telegram? (y/N): ")
        if confirm.lower() == "y":
            result = telegram_bot.send_new_posts_from_db()
            if result:
                print("✅ Messages sent successfully!")
            else:
                print("⚠️  No new messages to send or sending failed")
        else:
            print("   Skipping actual message sending")

    except Exception as e:
        print(f"❌ Telegram test failed: {e}")
        return False

    print("\n🎉 Complete workflow test finished!")
    return True


def show_database_info():
    """Show current database information"""
    print("\n📊 Current Database Status")
    print("=" * 40)

    try:
        from modules.database import MongoDBManager

        db_manager = MongoDBManager()

        stats = db_manager.get_posts_stats()
        print(f"Total posts: {stats.get('total_posts', 0)}")
        print(f"Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
        print(f"Pending to send: {stats.get('pending_to_send', 0)}")

        post_types = stats.get("post_types", [])
        if post_types:
            print("\nPost types:")
            for pt in post_types:
                print(f"  - {pt['_id']}: {pt['count']}")

        # Show recent unsent posts
        unsent_posts = db_manager.get_unsent_posts()
        if unsent_posts:
            print(f"\nRecent unsent posts (showing first 5):")
            for i, post in enumerate(unsent_posts[:5], 1):
                title = post.get("title", "No Title")[:50]
                print(f"  {i}. {title}...")

    except Exception as e:
        print(f"❌ Error getting database info: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "db-info":
        show_database_info()
    else:
        test_complete_workflow()
