"""
Database Management Utility for SuperSet Telegram Bot

This utility provides commands to manage the MongoDB database:
- View statistics
- List posts
- Mark posts as sent/unsent
- Clear database (with confirmation)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from modules.database import MongoDBManager


def show_stats():
    """Show database statistics"""
    try:
        db_manager = MongoDBManager()
        stats = db_manager.get_posts_stats()

        print("\n📊 DATABASE STATISTICS")
        print("=" * 40)
        print(f"Total posts: {stats.get('total_posts', 0)}")
        print(f"Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
        print(f"Pending to send: {stats.get('pending_to_send', 0)}")

        post_types = stats.get("post_types", [])
        if post_types:
            print("\nPost types distribution:")
            for pt in post_types:
                print(f"  - {pt['_id']}: {pt['count']}")

    except Exception as e:
        print(f"❌ Error showing stats: {e}")


def list_posts(limit=10, sent_only=False, unsent_only=False):
    """List recent posts"""
    try:
        db_manager = MongoDBManager()

        if unsent_only:
            posts = db_manager.get_unsent_posts()
            title = f"📋 UNSENT POSTS (limit: {limit})"
        else:
            posts = db_manager.get_all_posts(limit=limit)
            if sent_only:
                posts = [p for p in posts if p.get("sent_to_telegram")]
                title = f"📋 SENT POSTS (limit: {limit})"
            else:
                title = f"📋 RECENT POSTS (limit: {limit})"

        print(f"\n{title}")
        print("=" * 60)

        if not posts:
            print("No posts found.")
            return

        for i, post in enumerate(posts[:limit], 1):
            sent_status = "✅ Sent" if post.get("sent_to_telegram") else "⏳ Pending"
            created_at = post.get("created_at", datetime.utcnow()).strftime(
                "%Y-%m-%d %H:%M"
            )
            title = post.get("title", "No Title")[:50]
            post_type = post.get("post_type", "general")

            print(f"{i:2d}. [{sent_status}] {title}...")
            print(f"     Type: {post_type} | Created: {created_at}")
            print(f"     ID: {post['_id']}")
            print()

    except Exception as e:
        print(f"❌ Error listing posts: {e}")


def mark_all_as_unsent():
    """Mark all posts as unsent (for re-sending)"""
    try:
        confirm = input("⚠️  This will mark ALL posts as unsent. Are you sure? (y/N): ")
        if confirm.lower() != "y":
            print("Operation cancelled.")
            return

        db_manager = MongoDBManager()

        # Update all posts to mark as unsent
        result = db_manager.collection.update_many(
            {},
            {
                "$set": {"sent_to_telegram": False, "updated_at": datetime.utcnow()},
                "$unset": {"sent_at": ""},
            },
        )

        print(f"✅ Marked {result.modified_count} posts as unsent")

    except Exception as e:
        print(f"❌ Error marking posts as unsent: {e}")


def clear_database():
    """Clear all posts from database (with multiple confirmations)"""
    try:
        print("⚠️  WARNING: This will permanently delete ALL posts from the database!")
        confirm1 = input("Are you absolutely sure? Type 'DELETE' to confirm: ")
        if confirm1 != "DELETE":
            print("Operation cancelled.")
            return

        confirm2 = input("This cannot be undone. Type 'YES' to proceed: ")
        if confirm2 != "YES":
            print("Operation cancelled.")
            return

        db_manager = MongoDBManager()
        result = db_manager.collection.delete_many({})

        print(f"✅ Deleted {result.deleted_count} posts from database")

    except Exception as e:
        print(f"❌ Error clearing database: {e}")


def show_help():
    """Show help information"""
    help_text = """
📚 Database Management Utility

Usage:
    python db_manager.py [command] [options]

Commands:
    stats                Show database statistics
    list [N]            List N recent posts (default: 10)
    list-sent [N]       List N sent posts
    list-unsent [N]     List N unsent posts  
    mark-unsent         Mark all posts as unsent (for re-sending)
    test-exact          Test exact content matching functionality
    clear               Clear all posts from database (DESTRUCTIVE!)
    help                Show this help message

Examples:
    python db_manager.py stats
    python db_manager.py list 20
    python db_manager.py list-unsent 5
    python db_manager.py test-exact
    python db_manager.py mark-unsent
    """
    print(help_text)


def test_exact_matching():
    """Test exact content matching functionality"""
    print("\n🧪 TESTING EXACT CONTENT MATCHING")
    print("=" * 40)

    try:
        db_manager = MongoDBManager()

        # Test posts with slight variations
        test_posts = [
            {
                "title": "Test Job: Software Engineer",
                "content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "raw_content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "author": "Test Author",
                "posted_time": "2 hours ago",
            },
            {
                "title": "Test Job: Software Engineer",
                "content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "raw_content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "author": "Test Author",
                "posted_time": "2 hours ago",
            },
            {
                "title": "Test Job: Senior Software Engineer",  # Different title
                "content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "raw_content": "We are hiring a software engineer to join our team. Requirements: 3+ years experience.",
                "author": "Test Author",
                "posted_time": "2 hours ago",
            },
            {
                "title": "Test Job: Software Engineer",
                "content": "We are hiring a software engineer to join our amazing team. Requirements: 3+ years experience.",  # Different content
                "raw_content": "We are hiring a software engineer to join our amazing team. Requirements: 3+ years experience.",
                "author": "Test Author",
                "posted_time": "2 hours ago",
            },
        ]

        # Clean up any existing test posts first
        cleanup_result = db_manager.collection.delete_many(
            {"title": {"$regex": "Test Job:"}}
        )
        if cleanup_result.deleted_count > 0:
            print(f"🧹 Cleaned up {cleanup_result.deleted_count} existing test posts")

        results = []

        for i, post in enumerate(test_posts, 1):
            print(f"\nTest {i}: {post['title']}")
            print("-" * 30)

            # Create content hash
            content_hash = db_manager.create_post_hash(post["content"])
            print(f"Content hash: {content_hash[:16]}...")

            # Check if duplicate exists
            existing = db_manager.post_exists(content_hash)
            is_duplicate = existing is not None

            print(f"Duplicate check result: {is_duplicate}")

            if not is_duplicate:
                # Try to save the post
                success, result_msg = db_manager.save_post(
                    title=post["title"],
                    content=post["content"],
                    raw_content=post["raw_content"],
                    author=post["author"],
                    posted_time=post["posted_time"],
                )
                print(f"Save attempt: {'SUCCESS' if success else 'FAILED'}")
                results.append(f"Test {i}: {'SAVED' if success else 'FAILED TO SAVE'}")
            else:
                existing_title = existing.get("title", "No Title")[:50]
                print(f"Found duplicate: {existing_title}...")
                results.append(f"Test {i}: DUPLICATE DETECTED")

        # Print summary
        print(f"\n{'='*50}")
        print("TEST RESULTS SUMMARY")
        print("=" * 50)

        for result in results:
            print(f"✅ {result}")

        print(f"\n📋 Expected Behavior:")
        print("- Test 1: Should save successfully (first occurrence)")
        print("- Test 2: Should detect as EXACT duplicate (identical content)")
        print("- Test 3: Should save successfully (different title)")
        print("- Test 4: Should save successfully (different content)")

        # Clean up test posts
        cleanup_result = db_manager.collection.delete_many(
            {"title": {"$regex": "Test Job:"}}
        )
        print(f"\n🧹 Cleaned up {cleanup_result.deleted_count} test posts")

    except Exception as e:
        print(f"❌ Error during exact matching test: {e}")


def main():
    """Main function to handle command line arguments"""
    if len(sys.argv) < 2:
        show_help()
        return

    command = sys.argv[1].lower()

    if command == "stats":
        show_stats()

    elif command == "list":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        list_posts(limit=limit)

    elif command == "list-sent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        list_posts(limit=limit, sent_only=True)

    elif command == "list-unsent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        list_posts(limit=limit, unsent_only=True)

    elif command == "mark-unsent":
        mark_all_as_unsent()

    elif command == "clear":
        clear_database()

    elif command == "test-exact":
        test_exact_matching()

    elif command == "help" or command == "-h" or command == "--help":
        show_help()

    else:
        print(f"❌ Unknown command: {command}")
        print("Use 'python db_manager.py help' for usage information.")


if __name__ == "__main__":
    main()
