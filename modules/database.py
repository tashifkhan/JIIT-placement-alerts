import os
import re
import dotenv
import logging
from pymongo import MongoClient
from datetime import datetime
import hashlib

dotenv.load_dotenv()


class MongoDBManager:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connection_string = os.getenv("MONGO_CONNECTION_STR")
        self.client = None
        self.db = None
        self.collection = None
        self.users_collection = None  # Add users collection
        self.logger.info("Initializing MongoDBManager")
        self.connect()

    def connect(self):
        """Connect to MongoDB"""
        self.logger.info("Attempting to connect to MongoDB")
        try:
            if not self.connection_string:
                error_msg = "MONGO_CONNECTION_STR not found in environment variables"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            self.client = MongoClient(self.connection_string)
            self.db = self.client["SupersetPlacement"]
            self.collection = self.db["Posts"]
            self.users_collection = self.db["Users"]  # Initialize users collection

            # Test the connection
            self.client.admin.command("ping")
            success_msg = "Successfully connected to MongoDB"
            self.logger.info(success_msg)
            print(success_msg)

        except Exception as e:
            error_msg = f"Failed to connect to MongoDB: {e}"
            self.logger.error(error_msg, exc_info=True)
            print(error_msg)
            raise

    def create_post_hash(self, content):
        """Create a unique hash for exact content matching (no fuzzy matching)"""
        # Use the content exactly as-is for precise duplicate detection
        # Only strip leading/trailing whitespace to avoid formatting issues
        exact_content = content.strip()
        content_hash = hashlib.sha256(exact_content.encode("utf-8")).hexdigest()
        self.logger.debug(f"Created hash for content: {content_hash[:16]}...")
        return content_hash

    def post_exists(self, content_hash, content=None):
        """Check if a post with this exact hash already exists (no fuzzy matching)"""
        self.logger.debug(f"Checking if post exists with hash: {content_hash[:16]}...")
        try:
            existing_post = self.collection.find_one({"content_hash": content_hash})
            exists = existing_post is not None
            self.logger.debug(f"Post exists check result: {exists}")
            return exists
        except Exception as e:
            self.logger.error(f"Error checking if post exists: {e}", exc_info=True)
            return False
        try:
            # Only check for exact hash matches - no similarity checking
            existing_post = self.collection.find_one({"content_hash": content_hash})
            if existing_post:
                print(f"Found exact duplicate with hash: {content_hash[:16]}...")
                return existing_post

            return None

        except Exception as e:
            print(f"Error checking if post exists: {e}")
            return None

    # Removed fuzzy matching method - now using exact content matching only

    def save_post(self, title, content, raw_content="", author="", posted_time=""):
        """Save a new post to MongoDB with exact duplicate prevention"""
        try:
            # Create hash of exact content for precise duplicate detection
            content_hash = self.create_post_hash(content)

            # Check for exact duplicates only
            existing_post = self.post_exists(content_hash)
            if existing_post:
                print(f"Exact duplicate found with hash: {content_hash[:16]}...")
                print(
                    f"🔄 Exact duplicate exists: {existing_post.get('title', 'No Title')[:50]}..."
                )
                return False, "Exact duplicate post already exists"

            post_data = {
                "title": title.strip() if title else "No Title",
                "content": content,
                "raw_content": raw_content,
                "content_hash": content_hash,
                "author": author.strip() if author else "Unknown",
                "posted_time": posted_time.strip() if posted_time else "",
                "scraped_at": datetime.utcnow(),
                "sent_to_telegram": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }

            post_data.update(self._extract_post_metadata(content))

            result = self.collection.insert_one(post_data)
            print(f"Saved new post with ID: {result.inserted_id}")
            return True, str(result.inserted_id)

        except Exception as e:
            print(f"Error saving post: {e}")
            return False, str(e)

    def _extract_post_metadata(self, content):
        """Extract metadata from post content"""
        metadata = {
            "has_deadline": False,
            "has_eligibility": False,
            "has_link": False,
            "post_type": "general",
        }

        content_lower = content.lower()

        if "deadline" in content_lower or any(
            month in content_lower
            for month in [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ]
        ):
            metadata["has_deadline"] = True

        if any(
            term in content_lower
            for term in [
                "eligibility",
                "cgpa",
                "percentage",
                "b.tech",
                "m.tech",
                "undergraduate",
            ]
        ):
            metadata["has_eligibility"] = True

        if "http" in content_lower or "www." in content_lower:
            metadata["has_link"] = True

        if any(
            term in content_lower
            for term in ["open for applications", "hiring", "placement", "job"]
        ):
            metadata["post_type"] = "job_posting"

        elif any(
            term in content_lower for term in ["hackathon", "competition", "contest"]
        ):
            metadata["post_type"] = "competition"

        elif any(term in content_lower for term in ["webinar", "session", "workshop"]):
            metadata["post_type"] = "event"

        return metadata

    def get_unsent_posts(self):
        """Get all posts that haven't been sent to Telegram yet, sorted by oldest first (chronological order)"""
        try:
            query = {"sent_to_telegram": {"$ne": True}}

            # Sort by created_at in ascending order (1) to send oldest messages first (chronological order)
            cursor = self.collection.find(query).sort("created_at", -1)
            posts = list(cursor)

            unsent_posts = []
            for post in posts:
                sent_status = post.get("sent_to_telegram")
                if sent_status is not True:  # Explicit check for not True
                    unsent_posts.append(post)
                else:
                    print(
                        f"⚠️  Filtering out post marked as sent: {post.get('title', 'No Title')[:30]}..."
                    )

            print(
                f"Found {len(unsent_posts)} unsent posts out of {len(posts)} queried posts"
            )
            return unsent_posts

        except Exception as e:
            print(f"Error getting unsent posts: {e}")
            return []

    def mark_as_sent(self, post_id):
        """Mark a post as sent to Telegram"""
        try:
            result = self.collection.update_one(
                {"_id": post_id},
                {
                    "$set": {
                        "sent_to_telegram": True,
                        "sent_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0

        except Exception as e:
            print(f"Error marking post as sent: {e}")
            return False

    def is_post_sent(self, post_id):
        """Check if a specific post has already been sent to Telegram"""
        try:
            post = self.collection.find_one({"_id": post_id})
            if post:
                return post.get("sent_to_telegram", False)
            return False

        except Exception as e:
            print(f"Error checking if post was sent: {e}")
            return False

    def reset_send_status(self, post_id):
        """Reset the send status of a post (for debugging/testing purposes)"""
        try:
            result = self.collection.update_one(
                {"_id": post_id},
                {
                    "$set": {
                        "sent_to_telegram": False,
                        "updated_at": datetime.utcnow(),
                    },
                    "$unset": {"sent_at": ""},
                },
            )
            return result.modified_count > 0

        except Exception as e:
            print(f"Error resetting send status: {e}")
            return False

    def get_all_posts(self, limit=50):
        """Get all posts with optional limit"""
        try:
            cursor = self.collection.find().sort("created_at", -1).limit(limit)
            return list(cursor)

        except Exception as e:
            print(f"Error getting all posts: {e}")
            return []

    def get_posts_stats(self):
        """Get statistics about posts"""
        try:
            total_posts = self.collection.count_documents({})
            sent_posts = self.collection.count_documents({"sent_to_telegram": True})
            unsent_posts = self.collection.count_documents({"sent_to_telegram": False})

            pipeline = [
                {"$group": {"_id": "$post_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            post_types = list(self.collection.aggregate(pipeline))

            return {
                "total_posts": total_posts,
                "sent_to_telegram": sent_posts,
                "pending_to_send": unsent_posts,
                "post_types": post_types,
            }

        except Exception as e:
            print(f"Error getting posts stats: {e}")
            return {}

    def clean_duplicate_posts(self, dry_run=True):
        """Find and optionally remove duplicate posts based on content hash"""
        try:
            print("🔍 Scanning for duplicate posts...")

            pipeline = [
                {
                    "$group": {
                        "_id": "$content_hash",
                        "posts": {
                            "$push": {
                                "id": "$_id",
                                "title": "$title",
                                "created_at": "$created_at",
                            }
                        },
                        "count": {"$sum": 1},
                    }
                },
                {
                    "$match": {
                        "count": {
                            "$gt": 1,
                        },
                    },
                },
            ]

            duplicates = list(self.collection.aggregate(pipeline))

            if not duplicates:
                print("✅ No duplicate posts found!")
                return {"duplicates_found": 0, "removed": 0}

            print(f"Found {len(duplicates)} sets of duplicate posts:")

            total_duplicates = 0
            posts_to_remove = []

            for dup_group in duplicates:
                posts = dup_group["posts"]
                count = dup_group["count"]
                total_duplicates += count - 1

                posts.sort(key=lambda x: x["created_at"])
                posts_to_keep = posts[0]
                posts_to_delete = posts[1:]

                print(f"  📝 Hash: {dup_group['_id'][:16]}... ({count} duplicates)")
                print(f"     Keeping: {posts_to_keep['title'][:50]}...")

                for post in posts_to_delete:
                    print(
                        f"     {'Would remove' if dry_run else 'Removing'}: {post['title'][:50]}..."
                    )
                    posts_to_remove.append(post["id"])

            removed_count = 0
            if not dry_run and posts_to_remove:
                result = self.collection.delete_many({"_id": {"$in": posts_to_remove}})
                removed_count = result.deleted_count
                print(f"✅ Removed {removed_count} duplicate posts")

            elif dry_run:
                print(
                    f"🔍 DRY RUN: Would remove {len(posts_to_remove)} duplicate posts"
                )
                print(
                    "   Use clean_duplicate_posts(dry_run=False) to actually remove them"
                )

            return {
                "duplicates_found": total_duplicates,
                "removed": removed_count,
                "dry_run": dry_run,
            }

        except Exception as e:
            print(f"❌ Error cleaning duplicate posts: {e}")
            return {"error": str(e)}

    def close_connection(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("MongoDB connection closed")

    # User Management Methods
    def add_user(self, user_id, username=None, first_name=None, last_name=None):
        """Add a new user to the database or reactivate existing user"""
        try:
            # Check if user already exists
            existing_user = self.users_collection.find_one({"user_id": user_id})
            if existing_user:
                # If user exists but is inactive, reactivate them
                if not existing_user.get("is_active", False):
                    result = self.users_collection.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "is_active": True,
                                "username": username,
                                "first_name": first_name,
                                "last_name": last_name,
                                "updated_at": datetime.utcnow(),
                            }
                        },
                    )
                    if result.modified_count > 0:
                        print(f"Reactivated user: {user_id} (@{username})")
                        return True, "User reactivated"

                # User already exists and is active
                print(f"User {user_id} already exists and is active")
                return False, "User already exists and is active"

            # Create new user
            user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }

            result = self.users_collection.insert_one(user_data)
            print(f"Added new user: {user_id} (@{username})")
            return True, str(result.inserted_id)

        except Exception as e:
            print(f"Error adding user: {e}")
            return False, str(e)

    def get_all_users(self):
        """Get all active users"""
        try:
            users = list(self.users_collection.find({"is_active": True}))
            return users
        except Exception as e:
            print(f"Error getting users: {e}")
            return []

    def get_user_by_id(self, user_id):
        """Get a specific user by ID"""
        try:
            user = self.users_collection.find_one({"user_id": user_id})
            return user
        except Exception as e:
            print(f"Error getting user by ID: {e}")
            return None

    def deactivate_user(self, user_id):
        """Deactivate a user (soft delete)"""
        try:
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error deactivating user: {e}")
            return False

    def get_users_stats(self):
        """Get user statistics"""
        try:
            total_users = self.users_collection.count_documents({})
            active_users = self.users_collection.count_documents({"is_active": True})
            inactive_users = total_users - active_users

            return {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": inactive_users,
            }
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {}

    def reactivate_user(self, user_id):
        """Reactivate a user (opposite of deactivate)"""
        try:
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "is_active": True,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error reactivating user: {e}")
            return False

    def fix_user_activation_status(self):
        """Fix any users that might have incorrect activation status"""
        try:
            # Find users that might be incorrectly inactive
            inactive_users = list(
                self.users_collection.find({"is_active": {"$ne": True}})
            )

            print(f"Found {len(inactive_users)} users with non-active status")

            fixed_count = 0
            for user in inactive_users:
                user_id = user.get("user_id")
                username = user.get("username", "Unknown")

                # Reactivate the user
                result = self.users_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "is_active": True,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )

                if result.modified_count > 0:
                    fixed_count += 1
                    print(f"Fixed activation status for user {user_id} (@{username})")

            print(f"Fixed activation status for {fixed_count} users")
            return fixed_count

        except Exception as e:
            print(f"Error fixing user activation status: {e}")
            return 0

    # ...existing code...
