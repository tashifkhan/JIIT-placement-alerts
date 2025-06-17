import os
import dotenv
from pymongo import MongoClient
from datetime import datetime
import hashlib

dotenv.load_dotenv()


class MongoDBManager:
    def __init__(self):
        self.connection_string = os.getenv("MONGO_CONNECTION_STR")
        self.client = None
        self.db = None
        self.collection = None
        self.connect()

    def connect(self):
        """Connect to MongoDB"""
        try:
            if not self.connection_string:
                raise ValueError(
                    "MONGO_CONNECTION_STR not found in environment variables"
                )

            self.client = MongoClient(self.connection_string)
            self.db = self.client["SupersetPlacement"]
            self.collection = self.db["Posts"]

            # Test the connection
            self.client.admin.command("ping")
            print("Successfully connected to MongoDB")

        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise

    def create_post_hash(self, content):
        """Create a unique hash for post content to detect duplicates"""
        # Clean the content and create hash
        cleaned_content = content.strip().lower()
        # Remove common variations that don't affect content meaning
        cleaned_content = (
            cleaned_content.replace(" ", "").replace("\n", "").replace("\t", "")
        )
        return hashlib.md5(cleaned_content.encode()).hexdigest()

    def post_exists(self, content_hash):
        """Check if a post with this hash already exists"""
        try:
            existing_post = self.collection.find_one({"content_hash": content_hash})
            return existing_post is not None
        except Exception as e:
            print(f"Error checking if post exists: {e}")
            return False

    def save_post(self, title, content, raw_content="", author="", posted_time=""):
        """Save a new post to MongoDB"""
        try:
            content_hash = self.create_post_hash(content)

            # Check if post already exists
            if self.post_exists(content_hash):
                print(f"Post already exists with hash: {content_hash}")
                return False, "Post already exists"

            # Extract key information from content
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

            # Extract additional metadata
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

        # Check for deadline
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

        # Check for eligibility criteria
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

        # Check for links
        if "http" in content_lower or "www." in content_lower:
            metadata["has_link"] = True

        # Determine post type
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
        """Get all posts that haven't been sent to Telegram yet"""
        try:
            cursor = self.collection.find(
                {"sent_to_telegram": False},
                sort=[("created_at", -1)],  # Most recent first
            )
            return list(cursor)
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

            # Get post types distribution
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

    def close_connection(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("MongoDB connection closed")

    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close_connection()
