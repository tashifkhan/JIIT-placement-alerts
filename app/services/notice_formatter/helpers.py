"""Helper methods for SuperSet notice formatting."""

from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from bs4.element import Tag

from services.notice_formatter.state import Job


class NoticeFormatterHelperMixin:
    """Pure helper methods used by formatter graph nodes and output mapping."""

    @staticmethod
    def _ensure_str_content(content: Any) -> str:
        """Normalize LLM message content to a string."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
            return "\n".join(parts)

        return str(content)

    @staticmethod
    def _format_package(amount: Any, annum_months: Optional[str] = None) -> str:
        """Format a numeric package amount into a human friendly string."""
        if amount is None:
            return "Not specified"

        try:
            amt = float(amount)
        except Exception:
            return str(amount)

        is_monthly = False
        if isinstance(annum_months, str) and annum_months.strip():
            is_monthly = annum_months.strip().lower().startswith("m")

        if amt >= 100000:
            suffix = "LPM" if is_monthly else "LPA"
            return f"₹{(amt / 100000):.1f} {suffix}"

        if amt.is_integer():
            return f"₹{int(amt):,}"

        return f"₹{amt:,.2f}"

    @staticmethod
    def format_html_breakdown(html_content: Optional[str]) -> str:
        """Parse HTML content into a multi-line readable string."""
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, "html.parser")
        lines: List[str] = []

        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue

            for row in table.find_all("tr"):
                if not isinstance(row, Tag):
                    continue
                cells = [
                    cell.get_text(separator=" ", strip=True)
                    for cell in row.find_all(["td", "th"])
                    if isinstance(cell, Tag) and cell.get_text(strip=True)
                ]
                if cells:
                    lines.append(" | ".join(cells))

        for element in soup.find_all(["p", "li"]):
            text = element.get_text(separator=" ", strip=True)
            if text:
                lines.append(text)

        if not lines:
            fallback_text = soup.get_text(separator="\n", strip=True)
            if fallback_text:
                lines.append(fallback_text)

        if not lines:
            return ""

        result = "\n".join(lines).replace("\xa0", " ").strip()
        return f"(\n{result}\n)" if result else ""

    @staticmethod
    def _compact_list(value: Any) -> Optional[List[str]]:
        """Normalize a scalar/list field to a compact string list."""
        if not value:
            return None
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned or None
        text = str(value).strip()
        return [text] if text else None

    @staticmethod
    def _normalize_students(students: Any) -> Optional[List[Dict[str, Any]]]:
        """Normalize extracted student dictionaries for Mongo/UI consumption."""
        if not isinstance(students, list):
            return None

        normalized: List[Dict[str, Any]] = []
        for student in students:
            if not isinstance(student, dict):
                continue
            name = student.get("name")
            enrollment = (
                student.get("enrollment")
                or student.get("enrollment_number")
                or student.get("roll_number")
            )
            if not name and not enrollment:
                continue
            row: Dict[str, Any] = {
                "name": name or "Unknown",
                "enrollment": enrollment,
                "enrollment_number": enrollment,
            }
            for key in ("company", "role", "package", "location", "joining_date"):
                if student.get(key) not in (None, ""):
                    row[key] = student.get(key)
            normalized.append(row)

        return normalized or None

    @staticmethod
    def _job_eligibility(job: Optional[Job]) -> Optional[List[str]]:
        """Build compact eligibility lines from a structured job."""
        if not job:
            return None

        eligibility: List[str] = []
        if job.eligibility_courses:
            eligibility.append("Courses: " + ", ".join(job.eligibility_courses))
        for mark in job.eligibility_marks:
            eligibility.append(f"{mark.level}: {mark.criteria} CGPA or equivalent")
        return eligibility or None

    def _matched_job_summary(self, job: Optional[Job]) -> Optional[Dict[str, Any]]:
        """Build the embedded related-job summary for Mongo."""
        if not job:
            return None

        package = self._format_package(job.package, job.annum_months)
        package_breakdown = self.format_html_breakdown(job.package_info) or None
        return {
            "id": job.id,
            "company": job.company,
            "job_profile": job.job_profile,
            "location": job.location,
            "package": package,
            "package_breakdown": package_breakdown,
        }

    @staticmethod
    def _build_details(extracted: Dict[str, Any]) -> Dict[str, Any]:
        """Drop parser control fields and empty values from extracted details."""
        return {
            key: value
            for key, value in extracted.items()
            if value not in (None, "", []) and key not in {"error", "raw"}
        }
