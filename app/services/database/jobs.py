"""Job collection repository methods."""

import logging
from datetime import UTC, datetime
from typing import Any

from rapidfuzz import fuzz, process

from core.config import safe_print
from model.jobs import JobDocument
from services.database.base import RepositoryMixin

logger = logging.getLogger(__name__)


class JobRepository(RepositoryMixin):
    """CRUD and matching operations for the Jobs collection."""

    def structured_job_exists(self, structured_id: str) -> bool:
        """Check if a structured job exists."""
        if not structured_id:
            return False
        try:
            return (
                self.jobs_collection is not None
                and self.jobs_collection.find_one({"id": structured_id}) is not None
            )
        except Exception as e:
            safe_print(f"Error checking structured job existence: {e}")
            logger.exception("Error checking structured job existence")
            return False

    def get_all_job_ids(self) -> set:
        """Get all job IDs as a set for efficient lookup."""
        try:
            if self.jobs_collection is None:
                return set()
            cursor = self.jobs_collection.find({}, {"id": 1})
            return {doc.get("id") for doc in cursor if doc.get("id")}
        except Exception as e:
            safe_print(f"Error getting job IDs: {e}")
            logger.exception("Error getting job IDs")
            return set()

    def upsert_structured_job(self, structured_job: dict[str, Any]) -> tuple[bool, str]:
        """Insert or update a structured job."""
        try:
            sid = structured_job.get("id") if isinstance(structured_job, dict) else None
            if not sid:
                return False, "Missing structured job id"

            if self.jobs_collection is None:
                return False, "Jobs collection not initialized"

            validated_job = self._validated_doc(JobDocument(**structured_job))
            existing = self.jobs_collection.find_one({"id": sid})
            if existing:
                updated = {
                    **existing,
                    **validated_job,
                    "updated_at": datetime.now(UTC),
                }
                self.jobs_collection.replace_one({"_id": existing["_id"]}, updated)
                safe_print(f"Updated structured job {sid}")
                return True, "updated"

            doc = {**validated_job, "saved_at": datetime.now(UTC)}
            res = self.jobs_collection.insert_one(doc)
            safe_print(f"Inserted structured job {sid} -> {res.inserted_id}")
            return True, str(res.inserted_id)

        except Exception as e:
            safe_print(f"Error upserting structured job: {e}")
            logger.exception("Error upserting structured job")
            return False, str(e)

    def get_all_jobs(self, limit: int = 300) -> list[dict[str, Any]]:
        """Get all jobs with optional limit."""
        try:
            if self.jobs_collection is None:
                return []
            cursor = self.jobs_collection.find().sort("createdAt", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            safe_print(f"Error getting all jobs: {e}")
            logger.exception("Error getting all jobs")
            return []

    @staticmethod
    def _format_package(package: Any) -> str | None:
        """Format package values from Jobs for embedded summaries."""
        if package is None:
            return None
        try:
            value = float(package)
            return f"{value / 100000:.1f} LPA" if value >= 100000 else f"{value:g} LPA"
        except Exception:
            logger.exception("Error formatting package value: %s", package)
            return str(package)

    def _match_job_by_company(self, company_name: str) -> dict[str, Any] | None:
        """Fuzzy-match a company to a structured job in the same year DB."""
        if not company_name or self.jobs_collection is None:
            return None
        try:
            jobs = list(self.jobs_collection.find({}))
        except Exception as e:
            safe_print(f"Error loading jobs for placement match: {e}")
            logger.exception("Error loading jobs for placement match")
            return None

        choices = {
            index: str(job.get("company", ""))
            for index, job in enumerate(jobs)
            if job.get("company")
        }
        if not choices:
            return None

        match = process.extractOne(company_name, choices, scorer=fuzz.token_set_ratio)
        if not match:
            return None
        _, score, index = match
        if score <= 80:
            return None

        job = jobs[index]
        return {
            "id": str(job.get("id") or job.get("_id") or ""),
            "company": job.get("company"),
            "job_profile": job.get("job_profile"),
            "location": job.get("location"),
            "package": self._format_package(job.get("package")),
            "package_breakdown": job.get("package_breakdown") or job.get("package_info"),
        }
