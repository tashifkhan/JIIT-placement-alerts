"""PlacementOffers collection repository methods."""

import logging
from datetime import UTC, datetime
from typing import Any

from core.config import safe_print
from model.placement_offers import PlacementOfferDocument
from services.database.base import RepositoryMixin

logger = logging.getLogger(__name__)


class PlacementOfferRepository(RepositoryMixin):
    """Persistence and stats operations for placement offer records."""

    STUDENT_OFFER_TIMESTAMP_FIELDS = frozenset({"offer_received_at", "offerReceivedAt"})
    ON_CAMPUS_DETAIL_FIELDS = (
        "on_campus_reason",
        "on_campus_signals",
        "on_campus_job_id",
        "on_campus_ppo",
        "on_campus_model",
    )

    @staticmethod
    def _student_identity(student: dict[str, Any]) -> str | None:
        """Build a case-insensitive identity for student merge operations."""
        enrollment = student.get("enrollment_number") or student.get("enrollment")
        if enrollment:
            return f"enrollment:{str(enrollment).strip().casefold()}"
        name = " ".join(str(student.get("name") or "").split()).casefold()
        return f"name:{name}" if name else None

    @staticmethod
    def _parse_source_datetime(value: Any) -> datetime | None:
        """Parse source-created timestamps from email/SuperSet data."""
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            )

        try:
            if isinstance(value, (int, float)):
                timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
                return datetime.fromtimestamp(timestamp, tz=UTC)

            raw = str(value).strip()
            if raw.isdigit():
                timestamp = float(raw) / 1000 if len(raw) > 10 else float(raw)
                return datetime.fromtimestamp(timestamp, tz=UTC)

            from dateutil import parser as date_parser

            parsed = date_parser.parse(
                raw.replace(" IST", " +05:30"),
                fuzzy=True,
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            logger.exception("Error parsing source datetime: %s", value)
            return None

    @classmethod
    def _source_timestamps(cls, doc: dict[str, Any]) -> tuple[datetime | None, int | None]:
        """Resolve source datetime and epoch-ms from a placement offer document."""
        source_dt = cls._parse_source_datetime(
            doc.get("created_at") or doc.get("time_sent") or doc.get("saved_at")
        )

        created_at_ms = doc.get("createdAt")
        if isinstance(created_at_ms, (int, float)):
            source_ms = int(created_at_ms)
            return source_dt or cls._parse_source_datetime(source_ms), source_ms

        if source_dt:
            return source_dt, int(source_dt.timestamp() * 1000)

        return None, None

    @classmethod
    def _stamp_student_offer_date(
        cls,
        student: dict[str, Any],
        fallback_dt: datetime,
        fallback_ms: int,
    ) -> None:
        """Set a student's first offer date without replacing an existing one."""
        existing_dt = cls._parse_source_datetime(student.get("offer_received_at"))
        existing_ms = student.get("offerReceivedAt")
        if isinstance(existing_ms, (int, float)):
            existing_ms = int(existing_ms)
            existing_dt = existing_dt or cls._parse_source_datetime(existing_ms)
        else:
            existing_ms = None

        offer_dt = existing_dt or fallback_dt
        if existing_ms is not None:
            offer_ms = existing_ms
        elif existing_dt is not None:
            offer_ms = int(existing_dt.timestamp() * 1000)
        else:
            offer_ms = fallback_ms
        student["offer_received_at"] = offer_dt
        student["offerReceivedAt"] = offer_ms

    def save_placement_offers(self, offers: list[dict[str, Any]]) -> dict[str, Any]:
        """Save placement offers with merge logic and emit notice events."""
        inserted = 0
        updated = 0
        skipped = 0
        events: list[dict[str, Any]] = []

        try:
            if self.placement_offers_collection is None:
                safe_print("Placement offers collection not initialized")
                return {"error": "Placement offers collection not initialized"}

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                offer = dict(offer)
                company_name, company_key = self.normalize_company_identity(
                    offer.get("company")
                )
                if not company_key:
                    skipped += 1
                    continue
                offer["company"] = company_name
                offer["company_key"] = company_key

                source_dt, source_ms = self._source_timestamps(offer)
                now = datetime.now(UTC)
                offer_dt = source_dt or now
                offer_ms = source_ms or int(offer_dt.timestamp() * 1000)
                for student in offer.get("students_selected", []):
                    if isinstance(student, dict):
                        self._stamp_student_offer_date(student, offer_dt, offer_ms)
                matched_job = self._match_job_by_company(company_name)
                if matched_job:
                    offer["matched_job_id"] = matched_job.get("id")
                    offer["related_job_id"] = matched_job.get("id")
                    offer["matched_job"] = matched_job
                else:
                    offer["matched_job_id"] = None
                    offer["related_job_id"] = None
                    offer["matched_job"] = None

                cursor = self.placement_offers_collection.find(
                    {"company_key": company_key}
                ).sort("updated_at", -1)
                existing_companies = list(cursor)
                if not existing_companies:
                    legacy_cursor = self.placement_offers_collection.find(
                        {
                            "$or": [
                                {"company_key": {"$exists": False}},
                                {"company_key": None},
                            ]
                        }
                    ).sort("updated_at", -1)
                    for legacy_company in legacy_cursor:
                        _, legacy_key = self.normalize_company_identity(
                            legacy_company.get("company")
                        )
                        if legacy_key != company_key:
                            continue
                        self.placement_offers_collection.update_one(
                            {"_id": legacy_company["_id"]},
                            {"$set": {"company_key": company_key}},
                        )
                        legacy_company["company_key"] = company_key
                        existing_companies = [legacy_company]
                        break
                existing_company = existing_companies[0] if existing_companies else None

                if existing_company:
                    stored_company, _ = self.normalize_company_identity(
                        existing_company.get("company")
                    )
                    if stored_company:
                        company_name = stored_company
                        offer["company"] = stored_company
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
                            for field, value in new_role.items():
                                if self._has_value(value):
                                    role_map[r_name][field] = value
                        else:
                            existing_roles.append(new_role)
                            role_map[r_name] = new_role

                    existing_students = existing_company.get("students_selected", [])
                    new_students = offer.get("students_selected", [])
                    newly_added_students = []

                    existing_dt, existing_ms = self._source_timestamps(existing_company)
                    existing_dt = existing_dt or now
                    existing_ms = existing_ms or int(existing_dt.timestamp() * 1000)
                    for student in existing_students:
                        if isinstance(student, dict):
                            self._stamp_student_offer_date(
                                student,
                                existing_dt,
                                existing_ms,
                            )

                    student_map = {}
                    for student in existing_students:
                        key = self._student_identity(student)
                        if key:
                            student_map[key] = student

                    for new_student in new_students:
                        key = self._student_identity(new_student)
                        if not key:
                            continue
                        if key in student_map:
                            existing_student = student_map[key]
                            for field, value in new_student.items():
                                if (
                                    field in self.STUDENT_OFFER_TIMESTAMP_FIELDS
                                    and self._has_value(existing_student.get(field))
                                ):
                                    continue
                                if self._has_value(value):
                                    existing_student[field] = value
                        else:
                            existing_students.append(new_student)
                            student_map[key] = new_student
                            newly_added_students.append(new_student)

                    total_students = len(existing_students)
                    set_doc = {
                        "company": company_name,
                        "company_key": company_key,
                        "roles": existing_roles,
                        "students_selected": existing_students,
                        "number_of_offers": total_students,
                        "updated_at": now,
                    }

                    overwrite_fields = [
                        "job_location",
                        "joining_date",
                        "additional_info",
                        "email_subject",
                        "email_sender",
                        "time_sent",
                        "matched_job_id",
                        "related_job_id",
                        "matched_job",
                    ]
                    for field in overwrite_fields:
                        value = offer.get(field)
                        if self._has_value(value):
                            set_doc[field] = value

                    # A company's document collects several emails. Keep the most
                    # confident campus assessment instead of letting a later email
                    # that failed or scored lower clear a tag an earlier one earned.
                    if "likely_on_campus" in offer:
                        new_conf = offer.get("on_campus_confidence")
                        old_conf = existing_company.get("on_campus_confidence")
                        if (
                            "likely_on_campus" not in existing_company
                            or (offer.get("likely_on_campus") and not existing_company.get("likely_on_campus"))
                            or (
                                offer.get("likely_on_campus") == existing_company.get("likely_on_campus")
                                and new_conf is not None
                                and (old_conf is None or new_conf > old_conf)
                            )
                        ):
                            set_doc["likely_on_campus"] = bool(offer.get("likely_on_campus"))
                            set_doc["on_campus_confidence"] = new_conf
                            # The reason travels with the verdict it explains.
                            for field in self.ON_CAMPUS_DETAIL_FIELDS:
                                if field in offer:
                                    set_doc[field] = offer[field]

                    if source_dt:
                        set_doc["created_at"] = source_dt
                        set_doc["saved_at"] = source_dt
                    if source_ms:
                        set_doc["createdAt"] = source_ms

                    merged_doc = {**existing_company, **set_doc}
                    update_doc: dict[str, Any] = {"$set": {}}
                    if not matched_job:
                        for field in (
                            "matched_job_id",
                            "related_job_id",
                            "matched_job",
                        ):
                            merged_doc.pop(field, None)
                        update_doc["$unset"] = {
                            "matched_job_id": "",
                            "related_job_id": "",
                            "matched_job": "",
                        }

                    validated_set = self._validated_doc(
                        PlacementOfferDocument(**merged_doc)
                    )
                    validated_set.pop("_id", None)
                    update_doc["$set"] = validated_set
                    self.placement_offers_collection.update_one(
                        {"company_key": company_key},
                        update_doc,
                    )
                    updated += 1
                    safe_print(f"Updated placement data for {company_name}")

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
                    doc = self._validated_doc(PlacementOfferDocument(**offer))
                    doc.update(
                        {
                            "saved_at": source_dt or now,
                            "created_at": source_dt or now,
                            "createdAt": source_ms or int(now.timestamp() * 1000),
                            "updated_at": now,
                        }
                    )
                    offer_res = self.placement_offers_collection.insert_one(doc)
                    inserted += 1
                    safe_print(f"Inserted new placement data for {company_name}")

                    events.append(
                        {
                            "type": "new_offer",
                            "company": company_name,
                            "offer_id": offer_res.inserted_id,
                            "offer_data": doc,
                            "roles": doc.get("roles", []),
                            "total_students": len(doc.get("students_selected", [])),
                            "email_sender": doc.get("email_sender"),
                            "time_sent": doc.get("time_sent"),
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
            logger.exception("Error saving placement offers")
            return {"error": str(e)}

    def get_all_offers(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get all placement offers."""
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
            logger.exception("Error getting all offers")
            return []

    def get_placement_stats(self) -> dict[str, Any]:
        """Compute placement statistics."""
        try:
            if self.placement_offers_collection is None:
                return {}
            docs = list(self.placement_offers_collection.find())

            def to_float(val):
                try:
                    if val is None:
                        return None
                    value = float(val)
                    if value >= 100_000:
                        return value / 100_000
                    if value > 1_000:
                        return None
                    return value
                except Exception:
                    logger.exception("Error converting package value: %s", val)
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

            for placement in docs:
                students = placement.get("students_selected") or []
                total_students_placed += len(students)

                company = placement.get("company") or "Unknown"
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

                for role in placement.get("roles") or []:
                    role_name = role.get("role")
                    if role_name:
                        company_stats[company]["profiles"].add(role_name)

                for student in students:
                    pkg = get_student_package(student, placement)
                    if pkg is not None and pkg > 0:
                        all_packages.append(pkg)
                        company_stats[company]["packages"].append(pkg)

            average_package = sum(all_packages) / len(all_packages) if all_packages else 0.0
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
                {
                    p.get("company_key")
                    or self.normalize_company_identity(p.get("company"))[1]
                    or "unknown"
                    for p in docs
                }
            )

            for stats in company_stats.values():
                pkgs = stats["packages"]
                stats["avgPackage"] = sum(pkgs) / len(pkgs) if pkgs else 0.0
                stats["profiles"] = sorted(stats["profiles"])

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
            logger.exception("Error computing placement stats")
            return {"error": str(e)}

    def _serialize_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Convert MongoDB document to JSON-serializable format."""
        if not doc:
            return doc
        new_doc = doc.copy()
        if "_id" in new_doc:
            new_doc["_id"] = str(new_doc["_id"])
        return new_doc
