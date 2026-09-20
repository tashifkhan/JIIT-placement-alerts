"""
Notice Message Builder

Builds Telegram/WebPush text from structured notice documents stored in MongoDB.
The database contract is structured fields; messages are render output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


class NoticeMessageBuilder:
    """Render structured notice documents into notification messages."""

    @staticmethod
    def _compact_lines(lines: Iterable[Optional[str]]) -> str:
        return "\n".join(line for line in lines if line is not None and str(line).strip())

    @staticmethod
    def _category(notice: Dict[str, Any]) -> str:
        category = notice.get("category") or notice.get("type") or "announcement"
        return str(category).replace("_", " ").strip().lower()

    @staticmethod
    def _format_date(value: Any) -> Optional[str]:
        if value in (None, "", 0):
            return None

        try:
            if isinstance(value, datetime):
                dt = value
            elif isinstance(value, (int, float)):
                timestamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            else:
                raw = str(value).strip()
                if raw.isdigit():
                    timestamp = float(raw) / 1000 if len(raw) > 10 else float(raw)
                    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                else:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
                "%B %d, %Y at %I:%M %p IST"
            )
        except Exception:
            return str(value)

    @staticmethod
    def _student_label(student: Dict[str, Any]) -> str:
        name = student.get("name") or "Unknown"
        enrollment = (
            student.get("enrollment")
            or student.get("enrollment_number")
            or student.get("roll_number")
            or "N/A"
        )
        role = student.get("role")
        package = student.get("package")
        location = student.get("location")
        joining_date = student.get("joining_date")

        suffix_parts = [str(enrollment)]
        if role:
            suffix_parts.append(str(role))
        if package not in (None, ""):
            suffix_parts.append(f"{package} LPA" if isinstance(package, (int, float)) else str(package))
        if location:
            suffix_parts.append(str(location))
        if joining_date:
            suffix_parts.append(str(joining_date))

        return f"- {name} ({' | '.join(suffix_parts)})"

    @staticmethod
    def _students(notice: Dict[str, Any]) -> List[Dict[str, Any]]:
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        candidates = (
            notice.get("shortlisted_students")
            or notice.get("selected_students")
            or notice.get("students")
            or details.get("students")
            or []
        )
        return [student for student in candidates if isinstance(student, dict)]

    @staticmethod
    def _footer(notice: Dict[str, Any]) -> str:
        author = notice.get("author") or "Placement Updates"
        date_value = (
            notice.get("time_sent")
            or notice.get("createdAt")
            or notice.get("created_at")
            or notice.get("updatedAt")
            or notice.get("updated_at")
        )
        posted_on = NoticeMessageBuilder._format_date(date_value)
        footer = f"*Posted by:* {author}"
        if posted_on:
            footer += f"\n*On:* {posted_on}"
        return footer

    @staticmethod
    def _job_url(job_id: Optional[str]) -> Optional[str]:
        if not job_id:
            return None
        return f"http://jiit-placement-updates.tashif.codes/jobs/{job_id}"

    def build(self, notice: Dict[str, Any]) -> str:
        """Build a message from the structured notice document."""
        category = self._category(notice)

        if category == "placement offer" or notice.get("type") == "placement_offer":
            return self._build_placement_offer(notice)
        if category == "job posting":
            return self._build_job_posting(notice)
        if category == "shortlisting":
            return self._build_shortlisting(notice)
        if category == "webinar":
            return self._build_webinar(notice)
        if category == "hackathon":
            return self._build_hackathon(notice)
        if category == "internship noc":
            return self._build_student_list(notice, "**📋 Internship NOC List**")
        if category == "reminder":
            return self._build_generic(notice, "**⏰ Reminder**")
        if category == "update":
            return self._build_update(notice)
        return self._build_generic(notice, f"**🔔 {category.title()}**")

    def _build_job_posting(self, notice: Dict[str, Any]) -> str:
        job_id = notice.get("matched_job_id") or notice.get("related_job_id")
        title = notice.get("title") or "Job Posting"
        company = notice.get("job_company")
        role = notice.get("job_role")
        package = notice.get("package")
        package_breakdown = notice.get("package_breakdown")
        location = notice.get("location") or notice.get("job_location")
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        deadline = self._format_date(notice.get("deadline") or details.get("deadline"))
        eligibility = notice.get("eligibility_criteria") or details.get("eligibility_criteria") or []
        hiring_flow = notice.get("hiring_flow") or details.get("hiring_flow") or []

        lines = [f"**{title}**", "", "**📢 Job Posting**"]
        if company:
            lines.append(f"**Company:** {company}")
        if role:
            lines.append(f"**Role:** {role}")
        if location:
            lines.append(f"**Location:** {location}")
        if package:
            ctc = f"**CTC:** {package}"
            if package_breakdown:
                ctc += f" {package_breakdown}"
            lines.append(ctc)
        if eligibility:
            lines.append("\n**Eligibility Criteria:**")
            lines.extend(f"- {item}" for item in eligibility if item)
        if hiring_flow:
            lines.append("\n**Hiring Flow:**")
            lines.extend(f"{index + 1}. {step}" for index, step in enumerate(hiring_flow) if step)
        if deadline:
            lines.append(f"\n⚠️ **Deadline:** {deadline}")
        url = self._job_url(str(job_id)) if job_id else None
        if url:
            lines.append(f"\n🔗 Detailed JD: {url}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_shortlisting(self, notice: Dict[str, Any]) -> str:
        job_id = notice.get("matched_job_id") or notice.get("related_job_id")
        title = notice.get("title") or "Shortlisting Update"
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        company = notice.get("job_company") or details.get("company_name")
        role = notice.get("job_role") or details.get("role")
        location = notice.get("location") or details.get("venue")
        package = notice.get("package")
        students = self._students(notice)
        total = notice.get("students_count") or details.get("total_shortlisted") or len(students)

        lines = [f"**{title}**", "", "**🎉 Shortlisting Update**"]
        if company:
            lines.append(f"**Company:** {company}")
        if role:
            lines.append(f"**Role:** {role}")
        if location:
            lines.append(f"**Location:** {location}")
        if package:
            lines.append(f"**CTC:** {package}")
        if students:
            lines.append(f"\n**Total Shortlisted:** {total}")
            lines.append("Congratulations to the following students:")
            lines.extend(self._student_label(student) for student in students)
        url = self._job_url(str(job_id)) if job_id else None
        if url:
            lines.append(f"\n🔗 Detailed JD: {url}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_placement_offer(self, notice: Dict[str, Any]) -> str:
        job_id = notice.get("matched_job_id") or notice.get("related_job_id")
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        company = notice.get("job_company") or details.get("company")
        role = notice.get("job_role") or details.get("role")
        package = notice.get("package") or details.get("package")
        package_breakdown = notice.get("package_breakdown")
        location = notice.get("location") or details.get("location")
        joining_date = notice.get("joining_date") or details.get("joining_date")
        students = self._students(notice)
        total = notice.get("number_of_offers") or notice.get("students_count") or len(students)
        title = notice.get("title") or "Placement Offer"

        lines = [f"**{title}**", "", "**💰 Placement Offer**"]
        if company:
            lines.append(f"**Company:** {company}")
        if role:
            lines.append(f"**Role:** {role}")
        if package:
            ctc = f"**CTC:** {package}"
            if package_breakdown:
                ctc += f" {package_breakdown}"
            lines.append(ctc)
        if location:
            lines.append(f"**Location:** {location}")
        if joining_date:
            lines.append(f"**Joining Date:** {joining_date}")
        if total is not None:
            lines.append(f"**Number of Offers:** {total}")
        if students:
            lines.append("\n**Selected Students:**")
            lines.extend(self._student_label(student) for student in students)
        url = self._job_url(str(job_id)) if job_id else None
        if url:
            lines.append(f"\n🔗 Related Job Posting: {url}")
        lines.append("\nCongratulations to all selected!")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_webinar(self, notice: Dict[str, Any]) -> str:
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        event = details.get("event_name") or notice.get("title") or "Webinar"
        date = self._format_date(details.get("date"))
        deadline = self._format_date(notice.get("deadline") or details.get("deadline"))
        lines = [f"**{notice.get('title') or event}**", "", "**🎓 Webinar Details**"]
        lines.append(f"**Event:** {event}")
        for key, label in (("topic", "Topic"), ("speaker", "Speaker"), ("venue", "Venue / Platform")):
            if details.get(key):
                lines.append(f"**{label}:** {details[key]}")
        if date and details.get("time"):
            lines.append(f"**When:** {date} | {details['time']}")
        elif date:
            lines.append(f"**When:** {date}")
        elif details.get("time"):
            lines.append(f"**Time:** {details['time']}")
        if details.get("registration_link"):
            lines.append(f"**Registration:** {details['registration_link']}")
        if deadline:
            lines.append(f"\n⚠️ **Deadline:** {deadline}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_hackathon(self, notice: Dict[str, Any]) -> str:
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        event = details.get("event_name") or notice.get("title") or "Hackathon"
        start = self._format_date(details.get("start_date"))
        end = self._format_date(details.get("end_date"))
        deadline = self._format_date(details.get("registration_deadline") or notice.get("deadline"))
        lines = [f"**{notice.get('title') or event}**", "", "**🏁 Hackathon**"]
        lines.append(f"**Event:** {event}")
        for key, label in (
            ("theme", "Theme"),
            ("team_size", "Team Size"),
            ("prize_pool", "Prize Pool"),
            ("venue", "Venue / Platform"),
        ):
            if details.get(key):
                lines.append(f"**{label}:** {details[key]}")
        if start and end:
            lines.append(f"**Duration:** {start} - {end}")
        elif start or end:
            lines.append(f"**Date:** {start or end}")
        if details.get("registration_link"):
            lines.append(f"**Registration:** {details['registration_link']}")
        if deadline:
            lines.append(f"\n⚠️ **Registration Deadline:** {deadline}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_student_list(self, notice: Dict[str, Any], heading: str) -> str:
        students = self._students(notice)
        lines = [f"**{notice.get('title') or 'Student List'}**", "", heading]
        if students:
            lines.append(f"\n**Total Students:** {len(students)}")
            lines.extend(self._student_label(student) for student in students)
        content = notice.get("content")
        if content:
            lines.append(f"\n{content}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_update(self, notice: Dict[str, Any]) -> str:
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        company = notice.get("job_company") or details.get("company_name")
        role = notice.get("job_role") or details.get("role")
        lines = [f"**{notice.get('title') or 'Update'}**", "", "**🔔 Update**"]
        if company:
            lines.append(f"**Company:** {company}")
        if role:
            lines.append(f"**Role:** {role}")
        if notice.get("location"):
            lines.append(f"**Location:** {notice['location']}")
        body = details.get("message") or notice.get("content")
        if body:
            lines.append(f"\n{body}")
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)

    def _build_generic(self, notice: Dict[str, Any], heading: str) -> str:
        details = notice.get("details") if isinstance(notice.get("details"), dict) else {}
        lines = [f"**{notice.get('title') or 'Notice'}**", "", heading]
        body = details.get("message") or notice.get("content")
        if body:
            lines.append(f"\n{body}")
        deadline = self._format_date(notice.get("deadline") or details.get("deadline"))
        if deadline:
            lines.append(f"\n⚠️ **Deadline:** {deadline}")
        links = notice.get("links") or details.get("links") or []
        if links:
            lines.append("\n**🔗 Links:**")
            lines.extend(f"- {link}" for link in links[:5] if link)
        lines.append(f"\n{self._footer(notice)}")
        return self._compact_lines(lines)
