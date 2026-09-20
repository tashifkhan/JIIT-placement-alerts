"""
Migrate legacy notice/placement records to structured JSON fields.

Usage:
    python -m scripts.migrate_structured_notices --year 202526
    python -m scripts.migrate_structured_notices --all-years
    python -m scripts.migrate_structured_notices --year 202526 --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rapidfuzz import fuzz, process

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients.db_client import DBClient
from core.config import get_settings, safe_print
from core.year_context import (
    DEFAULT_PLACEMENT_YEAR,
    database_name_for_year,
    get_configured_placement_years,
    normalize_year,
)


LABEL_PATTERNS = {
    "company": re.compile(r"(?:\*\*)?Company(?:\*\*)?\s*:\s*(.+)", re.I),
    "role": re.compile(r"(?:\*\*)?Role(?:\*\*)?\s*:\s*(.+)", re.I),
    "ctc": re.compile(r"(?:\*\*)?(?:CTC|Package)(?:\*\*)?\s*:\s*(.+)", re.I),
    "location": re.compile(r"(?:\*\*)?(?:Location|Venue|Venue / Platform)(?:\*\*)?\s*:\s*(.+)", re.I),
    "deadline": re.compile(r"(?:Deadline|Registration Deadline)\s*:\s*(.+)", re.I),
    "posted_by": re.compile(r"(?:\*\*)?Posted by(?:\*\*)?\s*:\s*(.+)", re.I),
    "posted_on": re.compile(r"(?:\*\*)?(?:On|Date|Sent)(?:\*\*)?\s*:\s*(.+)", re.I),
    "offers": re.compile(r"Number of Offers\s*:\s*(\d+)", re.I),
}
JOB_URL_RE = re.compile(r"/jobs/([A-Za-z0-9_-]+)")
STUDENT_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*(?P<name>[^()\n]+?)\s*\((?P<enrollment>[^()\n]+)\)")


def parse_dt(value: Any) -> Optional[datetime]:
    """Parse date-ish values used by existing Mongo records."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    try:
        if isinstance(value, (int, float)):
            timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        raw = str(value).strip()
        if raw.isdigit():
            timestamp = float(raw) / 1000 if len(raw) > 10 else float(raw)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)

        from dateutil import parser as date_parser

        parsed = date_parser.parse(raw.replace(" IST", " +05:30"), fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    return int(dt.timestamp() * 1000) if dt else None


def clean_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = re.sub(r"</?[^>]+>", "", value)
    value = value.replace("**", "").strip()
    value = re.sub(r"\s+", " ", value)
    return value or None


def parse_labels(message: str) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for key, pattern in LABEL_PATTERNS.items():
        match = pattern.search(message or "")
        if match:
            parsed[key] = clean_value(match.group(1))

    job_match = JOB_URL_RE.search(message or "")
    if job_match:
        parsed["job_id"] = job_match.group(1)

    students: List[Dict[str, Any]] = []
    for line in (message or "").splitlines():
        match = STUDENT_LINE_RE.search(line)
        if not match:
            continue
        name = clean_value(match.group("name"))
        enrollment = clean_value(match.group("enrollment"))
        if name or enrollment:
            students.append(
                {
                    "name": name or "Unknown",
                    "enrollment": enrollment,
                    "enrollment_number": enrollment,
                }
            )
    if students:
        parsed["students"] = students

    return parsed


def normalize_category(doc: Dict[str, Any], parsed: Dict[str, Any]) -> str:
    raw = doc.get("category") or doc.get("type") or "announcement"
    category = str(raw).replace("_", " ").strip().lower()
    title_message = f"{doc.get('title', '')}\n{doc.get('content', '')}\n{doc.get('formatted_message', '')}".lower()

    if category in {"placement update", "placement offer"} or "placement offer" in title_message:
        return "placement offer"
    if "shortlist" in category or re.search(r"\bshortlist", title_message):
        return "shortlisting"
    if category == "job posting" or parsed.get("company") and parsed.get("role") and "open for applications" in title_message:
        return "job posting"
    if category == "internship noc":
        return "internship noc"
    return category or "announcement"


def build_job_lookup(jobs: Iterable[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[int, str], List[Dict[str, Any]]]:
    job_list = [job for job in jobs if isinstance(job, dict)]
    by_id = {str(job.get("id") or job.get("_id")): job for job in job_list if job.get("id") or job.get("_id")}
    choices = {index: str(job.get("company", "")) for index, job in enumerate(job_list) if job.get("company")}
    return by_id, choices, job_list


def job_summary(job: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not job:
        return None
    return {
        "id": str(job.get("id") or job.get("_id") or ""),
        "company": job.get("company"),
        "job_profile": job.get("job_profile"),
        "location": job.get("location"),
        "package": job.get("package"),
        "package_breakdown": job.get("package_breakdown") or job.get("package_info"),
    }


def match_job(company: Optional[str], parsed_job_id: Optional[str], job_by_id: Dict[str, Dict[str, Any]], job_choices: Dict[int, str], jobs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if parsed_job_id and parsed_job_id in job_by_id:
        return job_by_id[parsed_job_id]
    if not company or not job_choices:
        return None
    match = process.extractOne(company, job_choices, scorer=fuzz.token_set_ratio)
    if not match:
        return None
    _, score, index = match
    return jobs[index] if score > 80 else None


def normalize_student_rows(
    students: List[Dict[str, Any]],
    roles: List[Dict[str, Any]],
    location: Optional[str],
    joining_date: Optional[str],
    offer_received_at: Optional[datetime] = None,
    student_offer_dates: Optional[Dict[str, datetime]] = None,
) -> List[Dict[str, Any]]:
    default_role = roles[0].get("role") if len(roles) == 1 and roles[0].get("role") else None
    role_packages = {role.get("role"): role.get("package") for role in roles if role.get("role")}
    default_package = roles[0].get("package") if len(roles) == 1 else None
    rows: List[Dict[str, Any]] = []
    student_offer_dates = student_offer_dates or {}

    for student in students:
        row = dict(student)
        role = row.get("role") or default_role
        package = row.get("package") or (role_packages.get(role) if role else None) or default_package
        if role:
            row["role"] = role
        if package not in (None, ""):
            row["package"] = package
        if location and not row.get("location"):
            row["location"] = location
        if joining_date and not row.get("joining_date"):
            row["joining_date"] = joining_date
        enrollment = row.get("enrollment") or row.get("enrollment_number")
        if enrollment:
            row["enrollment"] = enrollment
            row["enrollment_number"] = enrollment
        identity = student_identity(row)
        student_date = student_offer_dates.get(identity) or offer_received_at
        if student_date and not row.get("offer_received_at"):
            row["offer_received_at"] = student_date
        if student_date and not row.get("offerReceivedAt"):
            row["offerReceivedAt"] = epoch_ms(student_date)
        rows.append({key: value for key, value in row.items() if value not in (None, "", [], {})})
    return rows


def student_identity(student: Dict[str, Any]) -> str:
    """Build the same stable student identity used by placement persistence."""
    enrollment = student.get("enrollment_number") or student.get("enrollment")
    if enrollment:
        return f"enrollment:{str(enrollment).strip().casefold()}"
    name = " ".join(str(student.get("name") or "").split()).casefold()
    return f"name:{name}" if name else ""


def get_student_offer_dates(db, offer: Dict[str, Any]) -> Dict[str, datetime]:
    """Recover earliest student offer dates from related placement notices."""
    offer_id = str(offer.get("_id") or "")
    company = offer.get("company")
    clauses: List[Dict[str, Any]] = []
    if offer_id:
        clauses.append({"placement_offer_ref": offer_id})
    if company:
        clauses.append(
            {
                "category": "placement offer",
                "job_company": {"$regex": f"^{re.escape(str(company))}$", "$options": "i"},
            }
        )
    if not clauses:
        return {}

    dates: Dict[str, datetime] = {}
    notices = db["Notices"].find({"$or": clauses}).sort("createdAt", 1)
    for notice in notices:
        notice_date = parse_dt(
            notice.get("time_sent")
            or notice.get("createdAt")
            or notice.get("saved_at")
        )
        if not notice_date:
            continue
        students = (
            notice.get("selected_students")
            or notice.get("shortlisted_students")
            or notice.get("students")
            or []
        )
        for student in students:
            if not isinstance(student, dict):
                continue
            identity = student_identity(student)
            if identity and identity not in dates:
                dates[identity] = notice_date
    return dates


def migrate_notices(db, year: str, dry_run: bool) -> int:
    notices = db["Notices"]
    jobs = list(db["Jobs"].find({}))
    job_by_id, job_choices, job_list = build_job_lookup(jobs)
    changed = 0

    for doc in notices.find({}):
        message = doc.get("formatted_message") or ""
        parsed = parse_labels(message)
        category = normalize_category(doc, parsed)
        matched_job = match_job(
            doc.get("job_company") or parsed.get("company"),
            str(doc.get("matched_job_id") or parsed.get("job_id") or "") or None,
            job_by_id,
            job_choices,
            job_list,
        )
        matched = job_summary(matched_job)
        matched_job_id = matched.get("id") if matched else parsed.get("job_id") or doc.get("matched_job_id")

        students = doc.get("shortlisted_students") or doc.get("selected_students") or doc.get("students") or parsed.get("students")
        if not isinstance(students, list):
            students = []

        source_dt = parse_dt(doc.get("time_sent") or doc.get("saved_at") or parsed.get("posted_on"))
        set_doc: Dict[str, Any] = {
            "category": category,
            "type": category.replace(" ", "_"),
            "year": doc.get("year") or year,
            "details": {
                **(doc.get("details") if isinstance(doc.get("details"), dict) else {}),
                **{key: value for key, value in parsed.items() if key not in {"students", "job_id"} and value},
            },
            "job_company": doc.get("job_company") or (matched or {}).get("company") or parsed.get("company"),
            "job_role": doc.get("job_role") or (matched or {}).get("job_profile") or parsed.get("role"),
            "package": doc.get("package") or parsed.get("ctc"),
            "location": doc.get("location") or (matched or {}).get("location") or parsed.get("location"),
            "deadline": doc.get("deadline") or parsed.get("deadline"),
            "matched_job_id": matched_job_id,
            "related_job_id": matched_job_id,
            "matched_job": matched,
        }

        if students:
            if category == "placement offer":
                set_doc["selected_students"] = students
            set_doc["shortlisted_students"] = students
            set_doc["students_count"] = len(students)

        if source_dt:
            ms = epoch_ms(source_dt)
            set_doc["createdAt"] = ms
            set_doc["updatedAt"] = ms

        set_doc = {key: value for key, value in set_doc.items() if value not in (None, "", [], {})}
        update = {"$set": set_doc, "$unset": {"formatted_message": ""}}
        changed += 1
        if not dry_run:
            notices.update_one({"_id": doc["_id"]}, update)

    return changed


def migrate_placement_offers(db, dry_run: bool) -> int:
    offers = db["PlacementOffers"]
    jobs = list(db["Jobs"].find({}))
    job_by_id, job_choices, job_list = build_job_lookup(jobs)
    changed = 0

    for doc in offers.find({}):
        roles = doc.get("roles") if isinstance(doc.get("roles"), list) else []
        locations = doc.get("job_location") if isinstance(doc.get("job_location"), list) else []
        location = ", ".join(str(item) for item in locations if item) or None
        joining_date = doc.get("joining_date")
        students = doc.get("students_selected") if isinstance(doc.get("students_selected"), list) else []
        source_dt = parse_dt(doc.get("time_sent") or doc.get("saved_at") or doc.get("created_at"))
        student_offer_dates = get_student_offer_dates(db, doc)
        normalized_students = normalize_student_rows(
            students,
            roles,
            location,
            joining_date,
            source_dt,
            student_offer_dates,
        )
        matched_job = match_job(doc.get("company"), str(doc.get("matched_job_id") or "") or None, job_by_id, job_choices, job_list)
        matched = job_summary(matched_job)
        matched_job_id = matched.get("id") if matched else doc.get("matched_job_id")

        set_doc: Dict[str, Any] = {
            "students_selected": normalized_students,
            "number_of_offers": len(normalized_students),
            "matched_job_id": matched_job_id,
            "related_job_id": matched_job_id,
            "matched_job": matched,
        }
        if source_dt:
            set_doc["created_at"] = source_dt
            set_doc["saved_at"] = source_dt
            set_doc["createdAt"] = epoch_ms(source_dt)

        set_doc = {key: value for key, value in set_doc.items() if value not in (None, "", [], {})}
        changed += 1
        if not dry_run:
            offers.update_one({"_id": doc["_id"]}, {"$set": set_doc})

    return changed


def migrate_year(year: str, dry_run: bool) -> Dict[str, int]:
    db_client = DBClient(database_name=database_name_for_year(year))
    db_client.connect()
    try:
        db = db_client.db
        notices = migrate_notices(db, year, dry_run)
        offers = migrate_placement_offers(db, dry_run)
        return {"notices": notices, "placement_offers": offers}
    finally:
        db_client.close_connection()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate notices to structured JSON fields")
    parser.add_argument("--year", help="Placement year, e.g. 202526")
    parser.add_argument("--all-years", action="store_true", help="Run for every configured placement year")
    parser.add_argument("--dry-run", action="store_true", help="Count changes without writing")
    args = parser.parse_args()

    settings = get_settings()
    if args.all_years:
        years = get_configured_placement_years(settings)
    else:
        years = [normalize_year(args.year or getattr(settings, "active_placement_year", None) or DEFAULT_PLACEMENT_YEAR)]

    totals: Dict[str, Dict[str, int]] = {}
    for year in years:
        safe_print(f"Migrating {year} ({'dry run' if args.dry_run else 'write'})...")
        totals[year] = migrate_year(year, args.dry_run)

    safe_print(f"Migration complete: {totals}")


if __name__ == "__main__":
    main()
