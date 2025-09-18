import os
import re
from dotenv import load_dotenv
import logging
from pymongo import MongoClient
from datetime import datetime
import hashlib
from config import safe_print


load_dotenv()


class MongoDBManager:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connection_string = os.getenv("MONGO_CONNECTION_STR")

        # declaring the connector
        self.client = None

        # declaring the DB
        self.db = None

        # declaring the tables
        self.notices_collection = None
        self.jobs_collection = None
        self.placement_offers_collection = None
        self.users_collection = None

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
            self.notices_collection = self.db["Notices"]
            self.jobs_collection = self.db["Jobs"]
            self.placement_offers_collection = self.db["PlacementOffers"]
            self.users_collection = self.db["Users"]

            # test the connection
            self.client.admin.command("ping")
            success_msg = "Successfully connected to MongoDB"
            self.logger.info(success_msg)
            safe_print(success_msg)

        except Exception as e:
            error_msg = f"Failed to connect to MongoDB: {e}"
            self.logger.error(error_msg, exc_info=True)
            safe_print(error_msg)
            raise

    def notice_exists(self, notice_id: str) -> bool:
        """Check if a notice with given id exists in the Notices collection."""
        if not notice_id:
            return False
        try:
            return self.notices_collection.find_one({"id": notice_id}) is not None

        except Exception as e:
            safe_print(f"Error checking notice existence: {e}")
            return False

    def save_notice(self, notice: dict) -> tuple[bool, str]:
        """Insert a notice dict into Notices collection if id not present.

        Returns (True, inserted_id) on insert, (False, reason) otherwise.
        """
        try:
            nid = notice.get("id") if isinstance(notice, dict) else None
            if not nid:
                return False, "Missing notice id"

            if self.notice_exists(nid):
                return False, "Notice already exists"

            doc = {
                **notice,
                "saved_at": datetime.utcnow(),
                "sent_to_telegram": False,
            }
            res = self.notices_collection.insert_one(doc)
            safe_print(f"Saved notice {nid} -> {res.inserted_id}")
            return True, str(res.inserted_id)

        except Exception as e:
            safe_print(f"Error saving notice: {e}")
            return False, str(e)

    def get_notice_by_id(self, notice_id: str) -> dict | None:
        try:
            return self.notices_collection.find_one({"id": notice_id})

        except Exception as e:
            safe_print(f"Error fetching notice {notice_id}: {e}")
            return None

    def structured_job_exists(self, structured_id: str) -> bool:
        if not structured_id:
            return False

        try:
            return self.jobs_collection.find_one({"id": structured_id}) is not None

        except Exception as e:
            safe_print(f"Error checking structured job existence: {e}")
            return False

    def upsert_structured_job(self, structured_job: dict) -> tuple[bool, str]:
        try:
            sid = structured_job.get("id") if isinstance(structured_job, dict) else None
            if not sid:
                return False, "Missing structured job id"

            existing = self.jobs_collection.find_one({"id": sid})
            if existing:
                updated = {
                    **existing,
                    **structured_job,
                    "updated_at": datetime.utcnow(),
                }
                self.jobs_collection.replace_one({"_id": existing["_id"]}, updated)
                safe_print(f"Updated structured job {sid}")
                return True, "updated"

            doc = {**structured_job, "saved_at": datetime.utcnow()}
            res = self.jobs_collection.insert_one(doc)
            safe_print(f"Inserted structured job {sid} -> {res.inserted_id}")
            return True, str(res.inserted_id)

        except Exception as e:
            safe_print(f"Error upserting structured job: {e}")
            return False, str(e)

    def save_placement_offers(self, offers: list[dict]) -> dict:
        """Save a list of placement offers (deduplicated by subject+sender) into PlacementOffers collection.

        Returns stats: {'inserted': n, 'skipped': m}
        """
        inserted = 0
        skipped = 0
        try:
            # Defensive checks for initialized collections
            if getattr(self, "placement_offers_collection", None) is None:
                safe_print("Placement offers collection not initialized")
                return {"error": "Placement offers collection not initialized"}
            if getattr(self, "notices_collection", None) is None:
                safe_print("Notices collection not initialized; will save offers only")

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                key = f"{offer.get('email_subject','')}__{offer.get('email_sender','')}"
                exists = self.placement_offers_collection.find_one(
                    {
                        "email_subject": offer.get("email_subject"),
                        "email_sender": offer.get("email_sender"),
                    }
                )
                if exists:
                    skipped += 1
                    continue
                # Save placement offer
                doc = {**offer, "saved_at": datetime.utcnow()}
                offer_res = self.placement_offers_collection.insert_one(doc)
                inserted += 1

                # Also create a corresponding placement notice for Telegram
                try:
                    if getattr(self, "notices_collection", None) is None:
                        # Skip creating notices if collection isn't available
                        continue
                    # Generate a unique notice id
                    ts = datetime.utcnow().timestamp()
                    company = (offer.get("company") or "").strip()
                    safe_company = company.replace(" ", "_") or "unknown_company"
                    notice_id = f"placement_{safe_company}_{int(ts)}"

                    # Build a detailed summary
                    roles_data = offer.get("roles") or []
                    role_names = [r.get("role") for r in roles_data if r.get("role")]
                    students = offer.get("students_selected") or []

                    # Build role -> package map (light formatting)
                    role_pkg: dict[str, str | None] = {}
                    for r in roles_data:
                        rname = r.get("role")
                        if not rname:
                            continue
                        pkg = r.get("package")
                        pkg_str: str | None
                        try:
                            if pkg is None:
                                pkg_str = None
                            else:
                                p = float(pkg)
                                # Assume >= 100000 means INR amount; convert to LPA
                                if p >= 100000:
                                    pkg_str = f"{p/100000:.1f} LPA"
                                else:
                                    # already looks like LPA figure
                                    pkg_str = f"{p:g} LPA"
                        except Exception:
                            pkg_str = str(pkg) if pkg is not None else None
                        role_pkg[rname] = pkg_str

                    # Count students per role; if students lack role and only one role exists, assign that bucket
                    role_counts: dict[str, int] = {}
                    default_role = role_names[0] if len(role_names) == 1 else None
                    for s in students:
                        rname = s.get("role") or default_role or "Unspecified"
                        role_counts[rname] = role_counts.get(rname, 0) + 1

                    total_count = len(students)

                    # Breakdown lines
                    lines: list[str] = []
                    listed = set()
                    for rname in role_names:
                        cnt = role_counts.get(rname, 0)
                        if cnt <= 0:
                            continue
                        pkg_str = role_pkg.get(rname)
                        suffix = f" — {pkg_str}" if pkg_str else ""
                        lines.append(
                            f"- {rname}: {cnt} offer{'s' if cnt!=1 else ''}{suffix}"
                        )
                        listed.add(rname)
                    for rname, cnt in role_counts.items():
                        if rname in listed:
                            continue
                        lines.append(f"- {rname}: {cnt} offer{'s' if cnt!=1 else ''}")

                    breakdown = "\n".join(lines)

                    summary = f"{total_count} student{'s' if total_count!=1 else ''} have been placed at {company or 'the company'}."
                    if breakdown:
                        summary += f"\n\nPositions:\n{breakdown}"
                    summary += "\n\nCongratulations to all selected!"

                    notice_doc = {
                        "id": notice_id,
                        "title": f"Placement Update: {company}",
                        "content": summary,
                        "author": "PlacementBot",
                        "type": "placement_update",
                        "source": "PlacementOffers",
                        "placement_offer_ref": str(offer_res.inserted_id),
                        # Provide a ready-to-send formatted message to bypass LLM formatting
                        "formatted_message": summary,
                        # timestamps in ms
                        "createdAt": int(ts * 1000),
                        "updatedAt": int(ts * 1000),
                        "sent_to_telegram": False,
                    }
                    self.notices_collection.insert_one(notice_doc)
                    safe_print(f"Inserted placement notice {notice_id}")
                except Exception as e:
                    safe_print(f"Error inserting placement notice: {e}")

            safe_print(
                f"Saved {inserted} new placement offers, skipped {skipped} duplicates"
            )
            return {"inserted": inserted, "skipped": skipped}

        except Exception as e:
            safe_print(f"Error saving placement offers: {e}")
            return {"error": str(e)}

    def get_unsent_notices(self):
        """Get all notices not yet sent to Telegram, sorted by oldest first (chronological order)."""
        try:
            if getattr(self, "notices_collection", None) is None:
                safe_print("Notices collection not initialized")
                return []
            query = {"sent_to_telegram": {"$ne": True}}

            # Sort by createdAt ascending (1) to send oldest messages first
            cursor = self.notices_collection.find(query).sort("createdAt", 1)
            posts = list(cursor)

            unsent_posts = []
            for post in posts:
                sent_status = post.get("sent_to_telegram")
                if sent_status is not True:  # Explicit check for not True
                    unsent_posts.append(post)
                else:
                    safe_print(
                        f"⚠️  Filtering out post marked as sent: {post.get('title', 'No Title')[:30]}..."
                    )

            safe_print(
                f"Found {len(unsent_posts)} unsent posts out of {len(posts)} queried posts"
            )
            return unsent_posts

        except Exception as e:
            safe_print(f"Error getting unsent posts: {e}")
            return []

    def mark_as_sent(self, post_id):
        """Mark a post as sent to Telegram"""
        try:
            result = self.notices_collection.update_one(
                {"_id": post_id},
                {
                    "$set": {
                        "sent_to_telegram": True,
                        "sent_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0

        except Exception as e:
            safe_print(f"Error marking post as sent: {e}")
            return False

    def is_post_sent(self, post_id):
        """Check if a specific post has already been sent to Telegram"""
        try:
            post = self.notices_collection.find_one({"_id": post_id})
            if post:
                return post.get("sent_to_telegram", False)
            return False

        except Exception as e:
            safe_print(f"Error checking if post was sent: {e}")
            return False

    def get_all_notices(self, limit=50):
        """Get all notices with optional limit"""
        try:
            cursor = self.notices_collection.find().sort("created_at", -1).limit(limit)
            return list(cursor)

        except Exception as e:
            safe_print(f"Error getting all notices: {e}")
            return []

    def get_all_jobs(self, limit=300):
        """Get all jobs with optional limit"""
        try:
            cursor = self.jobs_collection.find().sort("created_at", -1).limit(limit)
            return list(cursor)

        except Exception as e:
            safe_print(f"Error getting all jobs: {e}")
            return []

    def get_all_offers(self, limit=100):
        """Get all offers with optional limit"""
        try:
            coll = getattr(self, "placement_offers_collection", None) or getattr(
                self, "offers_collection", None
            )
            # Avoid truth-value testing of pymongo Collection objects
            if coll is None:
                safe_print("Offers collection not initialized")
                return []

            cursor = coll.find().sort("created_at", -1).limit(limit)
            return list(cursor)

        except Exception as e:
            safe_print(f"Error getting all offers: {e}")
            return []

    def clean_duplicate_notices(self, dry_run=True):
        """Find and optionally remove duplicate notices based on the 'id' field (keep earliest by createdAt)"""
        try:
            safe_print("🔍 Scanning for duplicate notices by 'id' field...")

            pipeline = [
                {
                    "$group": {
                        "_id": "$id",
                        "posts": {
                            "$push": {
                                "_id": "$_id",
                                "title": "$title",
                                "createdAt": "$createdAt",
                                "created_at": "$created_at",
                            }
                        },
                        "count": {"$sum": 1},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
            ]

            duplicates = list(self.notices_collection.aggregate(pipeline))

            if not duplicates:
                safe_print("✅ No duplicate notices found!")
                return {"duplicates_found": 0, "removed": 0}

            safe_print(f"Found {len(duplicates)} sets of duplicate notices:")

            total_duplicates = 0
            posts_to_remove = []

            for dup_group in duplicates:
                posts = dup_group["posts"]
                count = dup_group["count"]
                total_duplicates += count - 1

                # Sort by createdAt or created_at, fallback to 0 so earliest (smallest) comes first
                posts.sort(
                    key=lambda x: (
                        x.get("createdAt")
                        if x.get("createdAt") is not None
                        else x.get("created_at", 0)
                    )
                )
                post_to_keep = posts[0]
                posts_to_delete = posts[1:]

                safe_print(f"  📝 Duplicate id: {dup_group['_id']} ({count} documents)")
                safe_print(
                    f"     Keeping: {post_to_keep.get('title','No Title')[:50]}..."
                )

                for post in posts_to_delete:
                    safe_print(
                        f"     {'Would remove' if dry_run else 'Removing'}: {post.get('title','No Title')[:50]}..."
                    )
                    posts_to_remove.append(post["_id"])

            removed_count = 0
            if not dry_run and posts_to_remove:
                result = self.notices_collection.delete_many(
                    {"_id": {"$in": posts_to_remove}}
                )
                removed_count = result.deleted_count
                safe_print(f"✅ Removed {removed_count} duplicate notices")

            elif dry_run:
                safe_print(
                    f"🔍 DRY RUN: Would remove {len(posts_to_remove)} duplicate notices"
                )
                safe_print(
                    "   Use clean_duplicate_notices(dry_run=False) to actually remove them"
                )

            return {
                "duplicates_found": total_duplicates,
                "removed": removed_count,
                "dry_run": dry_run,
            }

        except Exception as e:
            safe_print(f"❌ Error cleaning duplicate notices: {e}")
            return {"error": str(e)}

            safe_print(f"Found {len(duplicates)} sets of duplicate posts:")

            total_duplicates = 0
            posts_to_remove = []

            for dup_group in duplicates:
                posts = dup_group["posts"]
                count = dup_group["count"]
                total_duplicates += count - 1

                posts.sort(key=lambda x: x["created_at"])
                posts_to_keep = posts[0]
                posts_to_delete = posts[1:]

                safe_print(
                    f"  📝 Hash: {dup_group['_id'][:16]}... ({count} duplicates)"
                )
                safe_print(f"     Keeping: {posts_to_keep['title'][:50]}...")

                for post in posts_to_delete:
                    safe_print(
                        f"     {'Would remove' if dry_run else 'Removing'}: {post['title'][:50]}..."
                    )
                    posts_to_remove.append(post["id"])

            removed_count = 0
            if not dry_run and posts_to_remove:
                result = self.collection.delete_many({"_id": {"$in": posts_to_remove}})
                removed_count = result.deleted_count
                safe_print(f"✅ Removed {removed_count} duplicate posts")

            elif dry_run:
                safe_print(
                    f"🔍 DRY RUN: Would remove {len(posts_to_remove)} duplicate posts"
                )
                safe_print(
                    "   Use clean_duplicate_posts(dry_run=False) to actually remove them"
                )

            return {
                "duplicates_found": total_duplicates,
                "removed": removed_count,
                "dry_run": dry_run,
            }

        except Exception as e:
            safe_print(f"❌ Error cleaning duplicate posts: {e}")
            return {"error": str(e)}

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
                        safe_print(f"Reactivated user: {user_id} (@{username})")
                        return True, "User reactivated"

                # User already exists and is active
                safe_print(f"User {user_id} already exists and is active")
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
            safe_print(f"Added new user: {user_id} (@{username})")
            return True, str(result.inserted_id)

        except Exception as e:
            safe_print(f"Error adding user: {e}")
            return False, str(e)

    def get_all_users(self):
        """Get all active users"""
        try:
            users = list(self.users_collection.find({"is_active": True}))
            return users

        except Exception as e:
            safe_print(f"Error getting users: {e}")
            return []

    def get_user_by_id(self, user_id):
        """Get a specific user by ID"""
        try:
            user = self.users_collection.find_one({"user_id": user_id})
            return user
        except Exception as e:
            safe_print(f"Error getting user by ID: {e}")
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
            safe_print(f"Error deactivating user: {e}")
            return False

    def get_notice_stats(self):
        """Return basic statistics about the Notices collection.

        Keys returned:
         - total_posts: total documents in Notices
         - sent_to_telegram: documents with sent_to_telegram == True
         - pending_to_send: documents where sent_to_telegram != True
         - post_types: list of dicts [{'_id': <type>, 'count': <n>}, ...] grouped by 'type' field

        Function is defensive: returns empty dict on error or if collection not initialized.
        """
        try:
            if getattr(self, "notices_collection", None) is None:
                safe_print("Notices collection not initialized")
                return {}

            total_posts = self.notices_collection.count_documents({})
            sent_to_telegram = self.notices_collection.count_documents(
                {"sent_to_telegram": True}
            )
            pending_to_send = self.notices_collection.count_documents(
                {"sent_to_telegram": {"$ne": True}}
            )

            # Aggregate post types grouped by 'type' field (fallbacks handled by pipeline)
            try:
                pipeline = [
                    {
                        "$group": {
                            "_id": {"$ifNull": ["$type", "unknown"]},
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1}},
                ]
                post_types = list(self.notices_collection.aggregate(pipeline))
            except Exception:
                post_types = []

            return {
                "total_posts": int(total_posts),
                "sent_to_telegram": int(sent_to_telegram),
                "pending_to_send": int(pending_to_send),
                "post_types": post_types,
            }

        except Exception as e:
            safe_print(f"Error getting notice stats: {e}")
            return {"error": str(e)}

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
            safe_print(f"Error getting user stats: {e}")
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
            safe_print(f"Error reactivating user: {e}")
            return False

    def fix_user_activation_status(self):
        """Fix any users that might have incorrect activation status"""
        try:
            # Find users that might be incorrectly inactive
            inactive_users = list(
                self.users_collection.find({"is_active": {"$ne": True}})
            )

            safe_print(f"Found {len(inactive_users)} users with non-active status")

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
                    safe_print(
                        f"Fixed activation status for user {user_id} (@{username})"
                    )

            safe_print(f"Fixed activation status for {fixed_count} users")
            return fixed_count

        except Exception as e:
            safe_print(f"Error fixing user activation status: {e}")
            return 0

    # placement stats
    def get_placement_stats(self):
        """Compute placement statistics from PlacementOffers collection.

        Returns a dict with overall stats and per-company stats.
        """
        try:
            docs = list(self.placement_offers_collection.find())

            # Helper to coerce package values to float when possible
            def to_float(val):
                try:
                    if val is None:
                        return None
                    return float(val)

                except Exception:
                    return None

            def get_student_package(student, placement):
                # student.package if present
                spkg = to_float(student.get("package"))
                if spkg is not None:
                    return spkg

                # exact role match in placement.roles
                roles = placement.get("roles") or []
                exact = next(
                    (r for r in roles if r.get("role") == student.get("role")), None
                )
                if exact:
                    rpkg = to_float(exact.get("package"))
                    if rpkg is not None:
                        return rpkg

                # viable roles (non-null package)
                viable = [to_float(r.get("package")) for r in roles]
                viable = [v for v in viable if v is not None]
                if len(viable) == 1:
                    return viable[0]

                if len(viable) > 1:
                    return max(viable)

                return None

            placements = docs

            total_students_placed = 0
            all_packages = []
            company_stats = {}

            for p in placements:
                students = p.get("students_selected") or []
                total_students_placed += len(students)

                company = p.get("company") or "Unknown"
                if company not in company_stats:
                    company_stats[company] = {
                        "count": 0,
                        "profiles": set(),
                        "avgPackage": 0.0,
                        "packages": [],
                        "studentsCount": 0,
                    }
                company_stats[company]["count"] += 1
                company_stats[company]["studentsCount"] += len(students)

                # collect profiles from roles
                for role in p.get("roles") or []:
                    role_name = role.get("role")
                    if role_name:
                        company_stats[company]["profiles"].add(role_name)

                # collect package values from students
                for student in students:
                    pkg = get_student_package(student, p)
                    if pkg is not None and pkg > 0:
                        all_packages.append(pkg)
                        company_stats[company]["packages"].append(pkg)

            # overall stats
            average_package = (
                sum(all_packages) / len(all_packages) if len(all_packages) > 0 else 0.0
            )

            sorted_packages = sorted(all_packages)
            if len(sorted_packages) == 0:
                median_package = 0.0
            elif len(sorted_packages) % 2 == 0:
                mid = len(sorted_packages) // 2
                median_package = (sorted_packages[mid - 1] + sorted_packages[mid]) / 2.0
            else:
                median_package = sorted_packages[len(sorted_packages) // 2]

            highest_package = max(all_packages) if all_packages else 0.0
            unique_companies = len(
                {(p.get("company") or "Unknown") for p in placements}
            )

            # finalize company stats (compute avg and convert profiles to list)
            for comp, stats in company_stats.items():
                pkgs = stats["packages"]
                stats["avgPackage"] = sum(pkgs) / len(pkgs) if pkgs else 0.0
                stats["profiles"] = sorted(list(stats["profiles"]))

            result = {
                "placements_count": len(placements),
                "total_students_placed": total_students_placed,
                "average_package": average_package,
                "median_package": median_package,
                "highest_package": highest_package,
                "unique_companies": unique_companies,
                "company_stats": company_stats,
                "placements_raw": placements,
            }

            return result

        except Exception as e:
            safe_print(f"Error computing placement stats: {e}")
            return {"error": str(e)}

    # close connection
    def close_connection(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            safe_print("MongoDB connection closed")
