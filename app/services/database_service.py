"""
Database Service

Implements IDatabaseService protocol for MongoDB operations.
Wraps the existing MongoDBManager functionality with dependency injection support.
"""

import os
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pymongo import MongoClient

from core.config import safe_print


class DatabaseService:
    """
    Database service implementing IDatabaseService protocol.

    This service handles all MongoDB operations including:
    - Notices (job postings, announcements)
    - Jobs (structured job listings)
    - Placement offers
    - User management
    - Official placement data
    """

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize database service.

        Args:
            connection_string: MongoDB connection string. If None, reads from env.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.connection_string = connection_string or os.getenv("MONGO_CONNECTION_STR")

        # Connection and collections
        self.client: Optional[MongoClient] = None
        self.db = None
        self.notices_collection = None
        self.jobs_collection = None
        self.placement_offers_collection = None
        self.users_collection = None

        self.logger.info("Initializing DatabaseService")
        self.connect()

    # Connection Management
    def connect(self) -> None:
        """Establish database connection"""
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

            # Test connection
            self.client.admin.command("ping")
            success_msg = "Successfully connected to MongoDB"
            self.logger.info(success_msg)
            safe_print(success_msg)

        except Exception as e:
            error_msg = f"Failed to connect to MongoDB: {e}"
            self.logger.error(error_msg, exc_info=True)
            safe_print(error_msg)
            raise

    def close_connection(self) -> None:
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            self.logger.info("MongoDB connection closed")
            safe_print("MongoDB connection closed")

    # =========================================================================
    # Notice Operations
    # =========================================================================

    def notice_exists(self, notice_id: str) -> bool:
        """Check if a notice with given id exists"""
        if not notice_id:
            return False
        try:
            return (
                self.notices_collection is not None
                and self.notices_collection.find_one({"id": notice_id}) is not None
            )
        except Exception as e:
            safe_print(f"Error checking notice existence: {e}")
            return False

    def get_all_notice_ids(self) -> set:
        """Get all notice IDs as a set for efficient lookup"""
        try:
            if self.notices_collection is None:
                return set()
            cursor = self.notices_collection.find({}, {"id": 1})
            return {doc.get("id") for doc in cursor if doc.get("id")}
        except Exception as e:
            safe_print(f"Error getting notice IDs: {e}")
            return set()

    def save_notice(self, notice: Dict[str, Any]) -> Tuple[bool, str]:
        """Insert a notice if id not present"""
        try:
            nid = notice.get("id") if isinstance(notice, dict) else None
            if not nid:
                return False, "Missing notice id"

            if self.notice_exists(nid):
                return False, "Notice already exists"

            if self.notices_collection is None:
                return False, "Notices collection not initialized"

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

    def get_notice_by_id(self, notice_id: str) -> Optional[Dict[str, Any]]:
        """Get a notice by its ID"""
        try:
            if self.notices_collection is None:
                return None
            return self.notices_collection.find_one({"id": notice_id})
        except Exception as e:
            safe_print(f"Error fetching notice {notice_id}: {e}")
            return None

    def get_unsent_notices(self) -> List[Dict[str, Any]]:
        """Get notices not yet sent to Telegram, sorted chronologically"""
        try:
            if self.notices_collection is None:
                safe_print("Notices collection not initialized")
                return []

            query = {"sent_to_telegram": {"$ne": True}}
            cursor = self.notices_collection.find(query).sort("createdAt", 1)
            posts = list(cursor)

            unsent_posts = [p for p in posts if p.get("sent_to_telegram") is not True]
            safe_print(f"Found {len(unsent_posts)} unsent posts")
            return unsent_posts

        except Exception as e:
            safe_print(f"Error getting unsent posts: {e}")
            return []

    def mark_as_sent(self, post_id: Any) -> bool:
        """Mark a notice as sent to Telegram"""
        try:
            if self.notices_collection is None:
                return False
            result = self.notices_collection.update_one(
                {"_id": post_id},
                {"$set": {"sent_to_telegram": True, "sent_at": datetime.utcnow()}},
            )
            return result.modified_count > 0
        except Exception as e:
            safe_print(f"Error marking post as sent: {e}")
            return False

    def get_all_notices(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all notices with optional limit"""
        try:
            if self.notices_collection is None:
                return []
            cursor = self.notices_collection.find().sort("created_at", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            safe_print(f"Error getting all notices: {e}")
            return []

    def get_notice_stats(self) -> Dict[str, Any]:
        """Return statistics about the Notices collection"""
        try:
            if self.notices_collection is None:
                return {}

            total_posts = self.notices_collection.count_documents({})
            sent_to_telegram = self.notices_collection.count_documents(
                {"sent_to_telegram": True}
            )
            pending_to_send = self.notices_collection.count_documents(
                {"sent_to_telegram": {"$ne": True}}
            )

            try:
                pipeline = [
                    {
                        "$group": {
                            "_id": {"$ifNull": ["$type", "unknown"]},
                            "count": {"$sum": 1},
                        }
                    },
                    {
                        "$sort": {"count": -1},
                    },
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

    # =========================================================================
    # Job Operations
    # =========================================================================

    def structured_job_exists(self, structured_id: str) -> bool:
        """Check if a structured job exists"""
        if not structured_id:
            return False
        try:
            return (
                self.jobs_collection is not None
                and self.jobs_collection.find_one({"id": structured_id}) is not None
            )
        except Exception as e:
            safe_print(f"Error checking structured job existence: {e}")
            return False

    def get_all_job_ids(self) -> set:
        """Get all job IDs as a set for efficient lookup"""
        try:
            if self.jobs_collection is None:
                return set()
            cursor = self.jobs_collection.find({}, {"id": 1})
            return {doc.get("id") for doc in cursor if doc.get("id")}
        except Exception as e:
            safe_print(f"Error getting job IDs: {e}")
            return set()

    def upsert_structured_job(self, structured_job: Dict[str, Any]) -> Tuple[bool, str]:
        """Insert or update a structured job"""
        try:
            sid = structured_job.get("id") if isinstance(structured_job, dict) else None
            if not sid:
                return False, "Missing structured job id"

            if self.jobs_collection is None:
                return False, "Jobs collection not initialized"

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

    def get_all_jobs(self, limit: int = 300) -> List[Dict[str, Any]]:
        """Get all jobs with optional limit"""
        try:
            if self.jobs_collection is None:
                return []
            cursor = self.jobs_collection.find().sort("created_at", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            safe_print(f"Error getting all jobs: {e}")
            return []

    # =========================================================================
    # Placement Offers Operations
    # =========================================================================

    def save_placement_offers(self, offers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Save placement offers with merge logic.

        Returns a dict with:
        - inserted: count of new offers
        - updated: count of updated offers
        - skipped: count of offers without company name
        - events: list of change events for notification handling

        Each event in 'events' is:
        {
            "type": "new_offer" | "update_offer",
            "company": str,
            "offer_id": ObjectId,
            "offer_data": dict,  # Full offer for new, or update info
            "newly_added_students": list,  # Only for updates
            "roles": list,
            "total_students": int,
        }
        """
        inserted = 0
        updated = 0
        skipped = 0
        events: List[Dict[str, Any]] = []

        try:
            if self.placement_offers_collection is None:
                safe_print("Placement offers collection not initialized")
                return {"error": "Placement offers collection not initialized"}

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                company_name = offer.get("company")
                if not company_name:
                    skipped += 1
                    continue

                cursor = self.placement_offers_collection.find(
                    {"company": company_name}
                ).sort("updated_at", -1)
                existing_companies = list(cursor)

                existing_company = existing_companies[0] if existing_companies else None

                if existing_company:
                    # Merge logic
                    existing_roles = existing_company.get("roles", [])
                    new_roles = offer.get("roles", [])
                    role_map = {
                        r.get("role"): r for r in existing_roles if r.get("role")
                    }

                    for new_role in new_roles:
                        r_name = new_role.get("role")
                        if not r_name:
                            continue
                        if r_name in role_map:
                            old_pkg = role_map[r_name].get("package")
                            new_pkg = new_role.get("package")
                            if new_pkg is not None:
                                if old_pkg is None or float(new_pkg) > float(old_pkg):
                                    role_map[r_name]["package"] = new_pkg
                                    if new_role.get("package_details"):
                                        role_map[r_name]["package_details"] = (
                                            new_role.get("package_details")
                                        )
                        else:
                            existing_roles.append(new_role)
                            role_map[r_name] = new_role

                    existing_students = existing_company.get("students_selected", [])
                    new_students = offer.get("students_selected", [])
                    newly_added_students = []

                    student_map = {}
                    for s in existing_students:
                        key = s.get("enrollment_number") or s.get("name")
                        if key:
                            student_map[key] = s

                    for new_student in new_students:
                        key = new_student.get("enrollment_number") or new_student.get(
                            "name"
                        )
                        if not key:
                            continue
                        if key in student_map:
                            existing_s = student_map[key]
                            old_pkg = existing_s.get("package")
                            new_pkg = new_student.get("package")
                            if new_pkg is not None:
                                if old_pkg is None or float(new_pkg) > float(old_pkg):
                                    existing_s["package"] = new_pkg
                                    if new_student.get("role"):
                                        existing_s["role"] = new_student.get("role")
                        else:
                            existing_students.append(new_student)
                            student_map[key] = new_student
                            newly_added_students.append(new_student)

                    total_students = len(existing_students)

                    update_doc = {
                        "$set": {
                            "roles": existing_roles,
                            "students_selected": existing_students,
                            "number_of_offers": total_students,
                            "updated_at": datetime.utcnow(),
                        }
                    }

                    self.placement_offers_collection.update_one(
                        {"_id": existing_company["_id"]},
                        update_doc,
                    )
                    updated += 1
                    safe_print(f"Updated placement data for {company_name}")

                    # Emit update event if new students were added
                    if newly_added_students:
                        events.append(
                            {
                                "type": "update_offer",
                                "company": company_name,
                                "offer_id": existing_company["_id"],
                                "newly_added_students": newly_added_students,
                                "roles": existing_roles,
                                "total_students": total_students,
                                "email_sender": offer.get("email_sender"),
                                "time_sent": offer.get("time_sent"),
                            }
                        )
                else:
                    doc = {**offer, "saved_at": datetime.utcnow()}
                    offer_res = self.placement_offers_collection.insert_one(doc)
                    inserted += 1
                    safe_print(f"Inserted new placement data for {company_name}")

                    # Emit new offer event
                    events.append(
                        {
                            "type": "new_offer",
                            "company": company_name,
                            "offer_id": offer_res.inserted_id,
                            "offer_data": offer,
                            "roles": offer.get("roles", []),
                            "total_students": len(offer.get("students_selected", [])),
                            "email_sender": offer.get("email_sender"),
                            "time_sent": offer.get("time_sent"),
                        }
                    )

            safe_print(
                f"Processed offers: {inserted} inserted, {updated} updated, {skipped} skipped"
            )
            return {
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "events": events,
            }

        except Exception as e:
            safe_print(f"Error saving placement offers: {e}")
            return {"error": str(e)}

    def save_official_placement_data(self, data: Dict[str, Any]) -> None:
        """Save official placement data from JIIT website"""
        try:
            import json
            import hashlib

            if self.db is None:
                safe_print("Database not initialized")
                return

            collection = self.db["OfficialPlacementData"]

            data_for_hash = {
                k: v
                for k, v in data.items()
                if k not in ("scrape_timestamp", "_id", "content_hash")
            }
            content_hash = hashlib.sha256(
                json.dumps(data_for_hash, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest()

            latest_doc = collection.find_one(sort=[("scrape_timestamp", -1)])

            if latest_doc and latest_doc.get("content_hash") == content_hash:
                collection.update_one(
                    {"_id": latest_doc["_id"]},
                    {"$set": {"scrape_timestamp": data.get("scrape_timestamp")}},
                )
                safe_print(
                    f"Official placement data unchanged (hash: {content_hash[:12]}...). Updated timestamp."
                )
            else:
                data["content_hash"] = content_hash
                result = collection.insert_one(data)
                safe_print(
                    f"New official placement data inserted (hash: {content_hash[:12]}...). ID: {result.inserted_id}"
                )
        except Exception as e:
            safe_print(f"Error saving official placement data: {e}")

    def get_all_offers(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all placement offers"""
        try:
            if self.placement_offers_collection is None:
                safe_print("Offers collection not initialized")
                return []
            cursor = (
                self.placement_offers_collection.find()
                .sort("created_at", -1)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            safe_print(f"Error getting all offers: {e}")
            return []

    def get_placement_stats(self) -> Dict[str, Any]:
        """Compute placement statistics"""
        try:
            if self.placement_offers_collection is None:
                return {}
            docs = list(self.placement_offers_collection.find())

            def to_float(val):
                try:
                    return float(val) if val is not None else None
                except Exception:
                    return None

            def get_student_package(student, placement):
                spkg = to_float(student.get("package"))
                if spkg is not None:
                    return spkg

                roles = placement.get("roles") or []
                exact = next(
                    (r for r in roles if r.get("role") == student.get("role")), None
                )
                if exact:
                    rpkg = to_float(exact.get("package"))
                    if rpkg is not None:
                        return rpkg

                viable = [to_float(r.get("package")) for r in roles]
                viable = [v for v in viable if v is not None]
                if len(viable) == 1:
                    return viable[0]
                if len(viable) > 1:
                    return max(viable)
                return None

            total_students_placed = 0
            all_packages = []
            company_stats = {}

            for p in docs:
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

                for role in p.get("roles") or []:
                    role_name = role.get("role")
                    if role_name:
                        company_stats[company]["profiles"].add(role_name)

                for student in students:
                    pkg = get_student_package(student, p)
                    if pkg is not None and pkg > 0:
                        all_packages.append(pkg)
                        company_stats[company]["packages"].append(pkg)

            average_package = (
                sum(all_packages) / len(all_packages) if all_packages else 0.0
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
            unique_companies = len({p.get("company") or "Unknown" for p in docs})

            for comp, stats in company_stats.items():
                pkgs = stats["packages"]
                stats["avgPackage"] = sum(pkgs) / len(pkgs) if pkgs else 0.0
                stats["profiles"] = sorted(list(stats["profiles"]))

            return {
                "placements_count": len(docs),
                "total_students_placed": total_students_placed,
                "average_package": average_package,
                "median_package": median_package,
                "highest_package": highest_package,
                "unique_companies": unique_companies,
                "company_stats": company_stats,
                "placements_raw": [self._serialize_doc(d) for d in docs],
            }
        except Exception as e:
            safe_print(f"Error computing placement stats: {e}")
            return {"error": str(e)}

    def _serialize_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB document to JSON-serializable format"""
        if not doc:
            return doc
        new_doc = doc.copy()
        if "_id" in new_doc:
            new_doc["_id"] = str(new_doc["_id"])
        # Handle other potential ObjectId fields if necessary
        return new_doc

    # =========================================================================
    # User Management
    # =========================================================================

    def add_user(
        self,
        user_id: int,
        chat_id: Optional[int] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Add or reactivate a user"""
        try:
            if self.users_collection is None:
                return False, "Users collection not initialized"

            existing_user = self.users_collection.find_one({"user_id": user_id})
            if existing_user:
                if not existing_user.get("is_active", False):
                    result = self.users_collection.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "is_active": True,
                                "chat_id": chat_id,
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

                safe_print(f"User {user_id} already exists and is active")
                return False, "User already exists and is active"

            user_data = {
                "user_id": user_id,
                "chat_id": chat_id,
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

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate a user (soft delete)"""
        try:
            if self.users_collection is None:
                return False
            result = self.users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
            )
            return result.modified_count > 0
        except Exception as e:
            safe_print(f"Error deactivating user: {e}")
            return False

    def get_active_users(self) -> List[Dict[str, Any]]:
        """Get all active users"""
        try:
            if self.users_collection is None:
                return []
            return list(self.users_collection.find({"is_active": True}))
        except Exception as e:
            safe_print(f"Error getting users: {e}")
            return []

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users (for admin)"""
        try:
            if self.users_collection is None:
                return []
            return list(self.users_collection.find({"is_active": True}))
        except Exception as e:
            safe_print(f"Error getting users: {e}")
            return []

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user by their ID"""
        try:
            if self.users_collection is None:
                return None
            return self.users_collection.find_one({"user_id": user_id})
        except Exception as e:
            safe_print(f"Error getting user by ID: {e}")
            return None

    def get_users_stats(self) -> Dict[str, Any]:
        """Get user statistics"""
        try:
            if self.users_collection is None:
                return {}
            total_users = self.users_collection.count_documents({})
            active_users = self.users_collection.count_documents({"is_active": True})
            return {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": total_users - active_users,
            }
        except Exception as e:
            safe_print(f"Error getting user stats: {e}")
            return {}
