"""
Notice Formatter Service:

LLM-based formatter for notices using LangGraph and Gemini.
Models (Job, Notice, EligibilityMark) are imported from superset_client to keep types unified.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from bs4.element import Tag
from rapidfuzz import fuzz, process
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from typing import Required, TypedDict
from core import get_settings


# Re-export models for convenience
from .superset_client import Notice, Job, EligibilityMark


class PostState(TypedDict, total=False):
    # inputs
    notice: Required["Notice"]
    jobs: Required[List["Job"]]

    # computed fields through the graph
    id: str
    raw_text: str
    category: str
    matched_job: Optional["Job"]
    matched_job_id: Optional[str]
    job_location: Optional[str]
    extracted: Dict[str, Any]
    formatted_message: str


class NoticeFormatterService:

    def __init__(
        self,
        google_api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash-lite",
        temperature: float = 0,
    ):
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=google_api_key or get_settings().google_api_key,
        )
        self.app = self._build_graph()

    # -------- helpers ---------
    @staticmethod
    def _ensure_str_content(content: Any) -> str:
        """Normalize LLM message content (can be str or list of parts) to a string."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: List[str] = []
            for p in content:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict) and "text" in p:
                    parts.append(str(p["text"]))

            return "\n".join(parts)

        return str(content)

    @staticmethod
    def _format_ms_epoch_to_ist(
        ms: Optional[int],
        fmt: str = "%B %d, %Y at %I:%M %p %Z",
    ) -> str:
        """Convert milliseconds epoch to a formatted string in Asia/Kolkata (IST).

        Returns 'Not specified' if input is falsy.
        """
        if not ms:
            return "Not specified"
        try:
            # timestamps in the codebase are milliseconds
            ts = float(ms) / 1000.0
            # build aware datetime from UTC then convert to Asia/Kolkata
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            ist = dt_utc.astimezone(ZoneInfo("Asia/Kolkata"))
            return ist.strftime(fmt)

        except Exception:
            return "Not specified"

    @staticmethod
    def _prettify_raw_text(raw: str) -> str:
        """Lightly format the raw extracted text for direct sending.

        - Collapse more than one consecutive blank line into a single blank line.
        - Strip trailing spaces on each line.
        - Ensure the overall message is trimmed.
        """
        if not raw:
            return ""

        lines = [ln.rstrip() for ln in raw.splitlines()]
        cleaned: List[str] = []
        blank = False

        for ln in lines:
            if ln.strip() == "":
                if not blank:  # first blank line allowed
                    cleaned.append("")
                blank = True
            else:
                cleaned.append(ln)
                blank = False

        return "\n".join(cleaned).strip()

    @staticmethod
    def _format_package(amount: Any, annum_months: Optional[str] = None) -> str:
        """Format a numeric package amount into a human friendly string.

        - If amount >= 100000, represent as lakhs with one decimal and use
          'LPM' when annum_months starts with 'M' (monthly) else 'LPA'.
        - Otherwise, show rupee with thousand separators.
        """
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

        # show with separators; preserve cents when needed
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

    # -------- graph node handlers ---------
    def extract_text(self, state: PostState) -> PostState:
        """Extract clean text from the notice's HTML content."""
        soup = BeautifulSoup(
            state["notice"].content,
            "html.parser",
        )
        text = soup.get_text(
            separator="\n",
            strip=True,
        )
        state["raw_text"] = (state["notice"].title + "\n" + text).strip()
        state["id"] = state["notice"].id
        print("--- 1. Text Extracted ---")
        return state

    def classify_post(self, state: PostState) -> PostState:
        """Classify the notice into a predefined category."""
        classification_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a strict single-label classifier. Read the notice and output ONLY one lowercase label from this set (no punctuation, no extra words):\n"
                    "update, shortlisting, announcement, hackathon, webinar, job posting\n\n"
                    "Definitions / decision guide:\n"
                    "- update: Minor operational / procedural info, timetable shifts, portal status, brief changes with no list of selected students and not primarily event-focused. especially for ongoing placement / job drives.\n"
                    "- shortlisting: Contains a list (or table) of selected / shortlisted candidate names, rolls, or enrollments for a role, round, or company.\n"
                    "- announcement: General broad notice to all students (holiday, policy, generic info) that is not a job posting, not a shortlist, and not clearly an event (webinar/hackathon).\n"
                    "- hackathon: Describes a hackathon / coding competition (often includes theme, duration, prizes, team size).\n"
                    "- webinar: Describes an online/offline seminar / session with a speaker, topic, time (learning / informational session).\n"
                    "- job posting: Describes an opportunity to apply for a job/internship/placement including company + role (and often CTC, eligibility, deadline).\n\n"
                    "Tie-break rules:\n"
                    "1. If it has a shortlist table/list of names -> shortlisting.\n"
                    "2. If it is clearly a job opportunity with application instructions -> job posting (even if called announcement).\n"
                    "3. If it invites to a hackathon competition -> hackathon.\n"
                    "4. If it invites to a talk/session/seminar -> webinar.\n"
                    "5. If it is a generic info broadcast with broad audience and no action list -> announcement.\n"
                    "6. Minor status/info changes -> update.\n\n"
                    "Respond with ONLY the label (e.g., job posting).",
                ),
                (
                    "human",
                    "{raw_text}",
                ),
            ]
        )

        chain = classification_prompt | self.llm
        result = chain.invoke({"raw_text": state.get("raw_text", "")})

        category = self._ensure_str_content(result.content).strip().lower()
        state["category"] = category

        print(f"--- 2. Classified as: {category} ---")
        return state

    def match_job(self, state: PostState) -> PostState:
        """Extract company names from notice and fuzzy-match with job listings."""
        notice_text = state.get("raw_text", "")
        jobs = state.get("jobs", [])

        company_extraction_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an expert entity extractor. Your task is to identify and extract any company names mentioned in the text. List them separated by commas. If no company is mentioned, return an empty string.",
                ),
                (
                    "human",
                    "Text: {raw_text}",
                ),
            ]
        )

        extraction_chain = company_extraction_prompt | self.llm
        result = extraction_chain.invoke({"raw_text": notice_text})
        extracted_names_str = self._ensure_str_content(result.content).strip()

        if not extracted_names_str:
            print("--- 3. No company names extracted, skipping match ---")
            state["matched_job"] = None
            state["matched_job_id"] = None
            return state

        extracted_names = [
            name.strip() for name in extracted_names_str.split(",") if name.strip()
        ]
        print(f"DEBUG: Extracted potential company names -> {extracted_names}")

        best_overall_match_job = None
        highest_score = 0
        job_company_choices = [job.company for job in jobs]

        for name in extracted_names:
            match_result = process.extractOne(
                name, job_company_choices, scorer=fuzz.token_set_ratio
            )
            if match_result and match_result[1] > highest_score:
                highest_score = match_result[1]
                matched_company_name = match_result[0]
                best_overall_match_job = next(
                    (j for j in jobs if j.company == matched_company_name), None
                )

        print(f"DEBUG: Highest fuzzy match score -> {highest_score}")

        if best_overall_match_job and highest_score > 80:
            state["matched_job"] = best_overall_match_job
            state["matched_job_id"] = best_overall_match_job.id
            state["job_location"] = best_overall_match_job.location
            print(f"--- 3. Matched Job ID: {best_overall_match_job.id} ---")

        else:
            state["matched_job"] = None
            state["matched_job_id"] = None
            state["job_location"] = None
            print("--- 3. No suitable job match found ---")

        return state

    def extract_info(self, state: PostState) -> PostState:
        """Extract structured information based on the notice category."""
        extraction_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an information extractor. Based on the category, extract structured details. Your response MUST be a valid JSON object.\n\n"
                    "- For shortlisting: extract a list of students under the key 'students', each with 'name' and 'enrollment'. Also extract 'company_name' and 'role' if mentioned.\n"
                    "- For job posting: extract 'company_name', 'role', 'package', 'deadline', 'location', 'hiring_flow' (list of strings), and 'eligibility_criteria' (list of strings).\n"
                    "- For webinar: extract 'event_name', 'topic', 'speaker', 'date', 'time', 'venue', 'registration_link', and 'deadline' if present.\n"
                    "- For hackathon: extract 'event_name', 'theme', 'start_date', 'end_date', 'registration_deadline', 'registration_link', 'prize_pool', 'team_size', and 'venue' if present.\n"
                    "- For all others: extract relevant details based on the context (e.g., 'message', 'event_name', etc.).",
                ),
                (
                    "human",
                    "Category: {category}\n\nNotice:\n{raw_text}",
                ),
            ]
        )
        chain = extraction_prompt | self.llm
        result = chain.invoke(
            {
                "category": state.get("category", "announcement"),
                "raw_text": state.get("raw_text", ""),
            }
        )
        raw_content = self._ensure_str_content(result.content)
        cleaned_json_str = (
            raw_content.strip().replace("```json", "").replace("```", "").strip()
        )
        try:
            state["extracted"] = json.loads(cleaned_json_str)
            print("--- 4. Information Extracted Successfully ---")

        except json.JSONDecodeError:
            print("--- 4. FAILED to parse JSON from LLM ---")
            state["extracted"] = {
                "error": "Failed to parse JSON",
                "raw": cleaned_json_str,
            }
        return state

    def format_message(self, state: PostState) -> PostState:
        """Compose the final formatted message from extracted details and matches."""
        data = state.get("extracted", {})
        cat = state.get("category", "announcement")
        job = state.get("matched_job")
        job_location = state.get("job_location") or (job.location if job else None)
        notice: Notice = state["notice"]

        post_date = self._format_ms_epoch_to_ist(notice.updatedAt)
        title = notice.title

        # Add prefix for job postings
        if cat == "job posting":
            company_name = job.company if job else data.get("company_name", "")
            role = job.job_profile if job else data.get("role", "")
            if company_name and role:
                title = f"Open for applications - {company_name}'s Job Profile - {role}"
            elif company_name:
                title = f"Open for applications - {company_name}"

        msg_parts = [f"**{title}**\n"]

        # --- Simple passthrough formatting for 'announcement' ---
        if cat == "announcement":
            raw_text = state.get("raw_text", "")
            prettified = self._prettify_raw_text(raw_text)

            # Append attribution footer
            prettified += f"\n\n*Posted by*: {notice.author} \n*On:* {post_date}"
            state["formatted_message"] = prettified

            print("--- 5. Message Formatted (passthrough) ---")
            return state

        # --- Well-formatted update notices using LLM ---
        if cat == "update":
            company_name = job.company if job else data.get("company_name", "")
            role = job.job_profile if job else data.get("role", "")
            raw_text = state.get("raw_text", "")

            # Build context for LLM
            context_parts = [f"Title: {title}", f"Content:\n{raw_text}"]
            if company_name:
                context_parts.append(f"Company: {company_name}")
            if role:
                context_parts.append(f"Role: {role}")
            if job_location:
                context_parts.append(f"Location: {job_location}")
            if job:
                package_info = self._format_package(job.package, job.annum_months)
                if package_info:
                    context_parts.append(f"Package: {package_info}")

            context = "\n".join(context_parts)

            format_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a message formatter for placement/job update notifications. "
                        "Format the given notice into a clean, concise Telegram message.\n\n"
                        "Rules:\n"
                        "- Use **bold** for key labels only (Company, Role, Date, Location, etc.)\n"
                        "- Use bullet points (-) for listing key information\n"
                        "- Remove redundant/repetitive text\n"
                        "- Fix line breaks - no excessive blank lines\n"
                        "- Keep it concise - only essential info\n"
                        "- Use at most 1 emoji at the start as a header indicator\n"
                        "- Do NOT repeat information already shown\n"
                        "- End with a single line break before footer\n\n"
                        "Output ONLY the formatted message text, nothing else.",
                    ),
                    (
                        "human",
                        "{context}",
                    ),
                ]
            )

            chain = format_prompt | self.llm
            result = chain.invoke({"context": context})
            formatted_content = self._ensure_str_content(result.content).strip()

            # Add footer
            formatted_content += f"\n\n*Posted by:* {notice.author}\n*On:* {post_date}"

            state["formatted_message"] = formatted_content
            print("--- 5. Message Formatted (update via LLM) ---")
            return state

        if cat == "shortlisting":
            students = data.get("students", [])
            student_list = "\n".join(
                [
                    f"- {s.get('name', 'Unknown')} ({s.get('enrollment', 'N/A')})"
                    for s in students
                    if isinstance(s, dict)
                ]
            )
            total_shortlisted = data.get("total_shortlisted", len(students))

            company_name = job.company if job else data.get("company_name", "N/A")
            role = job.job_profile if job else data.get("role", "N/A")
            package_info: Optional[str]
            package_breakdown: str

            if job:
                package_info = self._format_package(job.package, job.annum_months)
                package_breakdown = self.format_html_breakdown(job.package_info)
            else:
                extracted_package = data.get("package")
                package_info = str(extracted_package) if extracted_package else None
                package_breakdown = ""

            msg_parts.append("**🎉 Shortlisting Update**")
            msg_parts.append(f"**Company:** {company_name}")
            msg_parts.append(f"**Role:** {role}")

            if job_location:
                msg_parts.append(f"**Location:** {job_location}")

            msg_parts.append("")
            if total_shortlisted > 0 and student_list:
                msg_parts.append(f"**Total Shortlisted:** {total_shortlisted}")
                msg_parts.append("Congratulations to the following students:")
                msg_parts.append(student_list)
                msg_parts.append("\n")

            if job and job.hiring_flow:
                hiring_flow_list = "\n".join(
                    [f"{i+1}. {step}" for i, step in enumerate(job.hiring_flow)]
                )
                msg_parts.append(f"\n**Hiring Process:**\n{hiring_flow_list}")

            if package_info:
                msg_parts.append(f"\n**CTC:** {package_info} {package_breakdown}")

        elif cat == "webinar":

            def _fmt_dt(val: Any) -> Optional[str]:
                if not val:
                    return None

                try:
                    # numeric epoch (ms or s). Assume ms if big number.
                    num = float(str(val))
                    if num > 10_000_000_000:  # clearly ms
                        return self._format_ms_epoch_to_ist(int(num))

                    # treat as seconds
                    return self._format_ms_epoch_to_ist(int(num * 1000))

                except Exception:
                    # try ISO
                    try:
                        dt = datetime.fromisoformat(str(val))

                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

                        return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
                            "%B %d, %Y at %I:%M %p %Z"
                        )

                    except Exception:
                        return str(val)

            event_name = data.get("event_name") or title
            topic = data.get("topic") or data.get("subject")
            speaker = data.get("speaker") or data.get("speakers")
            date_field = data.get("date")
            time_field = data.get("time")
            venue = data.get("venue") or data.get("location") or data.get("platform")
            reg_link = (
                data.get("registration_link") or data.get("link") or data.get("url")
            )
            deadline_raw = data.get("deadline")
            deadline_fmt = _fmt_dt(deadline_raw) if deadline_raw else None
            date_fmt = _fmt_dt(date_field) if date_field else None

            msg_parts.append("**🎓 Webinar Details**")
            msg_parts.append(f"**Event:** {event_name}")
            if topic:
                msg_parts.append(f"**Topic:** {topic}")
            if speaker:
                msg_parts.append(f"**Speaker:** {speaker}")
            if date_fmt and time_field:
                msg_parts.append(f"**When:** {date_fmt} | {time_field}")
            elif date_fmt:
                msg_parts.append(f"**When:** {date_fmt}")
            elif time_field:
                msg_parts.append(f"**Time:** {time_field}")
            if venue:
                msg_parts.append(f"**Venue / Platform:** {venue}")
            if reg_link:
                msg_parts.append(f"**Registration:** {reg_link}")
            if deadline_fmt:
                msg_parts.append(f"⚠️ **Deadline:** {deadline_fmt}")

        elif cat == "hackathon":

            def _fmt_dt(val: Any) -> Optional[str]:
                if not val:
                    return None
                try:
                    num = float(str(val))

                    if num > 10_000_000_000:
                        return self._format_ms_epoch_to_ist(int(num))

                    return self._format_ms_epoch_to_ist(int(num * 1000))

                except Exception:
                    try:
                        dt = datetime.fromisoformat(str(val))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

                        return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
                            "%B %d, %Y at %I:%M %p %Z"
                        )
                    except Exception:
                        return str(val)

            event_name = data.get("event_name") or title
            theme = data.get("theme") or data.get("topic")

            start_date = _fmt_dt(data.get("start_date"))
            end_date = _fmt_dt(data.get("end_date"))

            reg_deadline = _fmt_dt(data.get("registration_deadline"))
            reg_link = (
                data.get("registration_link") or data.get("link") or data.get("url")
            )

            prize_pool = data.get("prize_pool")
            team_size = data.get("team_size")

            venue = data.get("venue") or data.get("location") or data.get("platform")

            msg_parts.append("**🏁 Hackathon**")

            msg_parts.append(f"**Event:** {event_name}")

            if theme:
                msg_parts.append(f"**Theme:** {theme}")
            if start_date or end_date:
                if start_date and end_date:
                    msg_parts.append(f"**Duration:** {start_date} — {end_date}")
                else:
                    msg_parts.append(f"**Date:** {start_date or end_date}")
            if team_size:
                msg_parts.append(f"**Team Size:** {team_size}")
            if prize_pool:
                msg_parts.append(f"**Prize Pool:** {prize_pool}")
            if venue:
                msg_parts.append(f"**Venue / Platform:** {venue}")
            if reg_link:
                msg_parts.append(f"**Registration:** {reg_link}")
            if reg_deadline:
                msg_parts.append(f"⚠️ **Registration Deadline:** {reg_deadline}")

        elif cat == "job posting":
            if job:
                company_name = job.company
                role = job.job_profile
                job_location = job.location
                package_info = self._format_package(job.package, job.annum_months)
                package_breakdown = self.format_html_breakdown(job.package_info)

                deadline = self._format_ms_epoch_to_ist(
                    job.deadline, fmt="%B %d, %Y, %I:%M %p %Z"
                )

                eligibility_list = [
                    f"- **Courses:** \n{'\n'.join(job.eligibility_courses)}"
                ]
                for mark in job.eligibility_marks:
                    eligibility_list.append(
                        f"- **{mark.level} Marks:** {mark.criteria} CGPA or equivalent"
                    )

                eligibility_str = "**Eligibility Criteria:**\n" + "\n".join(
                    eligibility_list
                )

                hiring_flow_list = "\n".join(
                    [f"{i+1}. {step}" for i, step in enumerate(job.hiring_flow)]
                )
                hiring_flow_str = f"**Hiring Flow:**\n{hiring_flow_list}"

            else:
                company_name = data.get("company_name", "N/A")
                role = data.get("role", "N/A")
                job_location = data.get("location", None)
                package_info = data.get("package", "Not specified")
                package_breakdown = ""

                raw_deadline = data.get("deadline")
                if raw_deadline is None:
                    deadline = "Not specified"

                else:
                    try:
                        num = float(str(raw_deadline))
                        deadline = self._format_ms_epoch_to_ist(
                            int(num), fmt="%B %d, %Y, %I:%M %p %Z"
                        )

                    except Exception:
                        try:
                            dt = datetime.fromisoformat(str(raw_deadline))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                            deadline = dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
                                "%B %d, %Y, %I:%M %p %Z"
                            )
                        except Exception:
                            deadline = str(raw_deadline)

                extracted_eligibility = data.get("eligibility_criteria", [])
                if isinstance(extracted_eligibility, list) and extracted_eligibility:
                    eligibility_str = "**Eligibility Criteria:**\n" + "\n".join(
                        [f"- {item}" for item in extracted_eligibility]
                    )
                else:
                    eligibility_str = ""

                extracted_flow = data.get("hiring_flow", [])
                if isinstance(extracted_flow, list) and extracted_flow:
                    hiring_flow_str = "**Hiring Flow:**\n" + "\n".join(
                        [f"{i+1}. {step}" for i, step in enumerate(extracted_flow)]
                    )
                else:
                    hiring_flow_str = ""

            msg_parts.append("**📢 Job Posting**")
            msg_parts.append(f"**Company:** {company_name}")
            msg_parts.append(f"**Role:** {role}")

            if job_location:
                msg_parts.append(f"**Location:** {job_location}")

            msg_parts.append(f"**CTC:** {package_info} {package_breakdown}\n")

            if eligibility_str:
                msg_parts.append(eligibility_str + "\n")
            if hiring_flow_str:
                msg_parts.append(hiring_flow_str)

            msg_parts.append(f"\n⚠️ **Deadline:** {deadline}")

            job_id_for_link = job.id if job else state.get("matched_job_id")
            if job_id_for_link:
                details_url = (
                    f"http://jiit-placement-updates.tashif.codes/jobs/{job_id_for_link}"
                )
                msg_parts.append(f"\n\n🔗 Detailed JD: {details_url}")

        else:
            message_content = data.get(
                "message", state.get("raw_text", "See notice for details.")
            )
            msg_parts.append(f"**🔔 {cat.capitalize()}**\n")
            msg_parts.append(message_content.replace(title, "").strip())

            if data.get("deadline"):
                raw_d = data.get("deadline")
                try:
                    num = float(str(raw_d))
                    d_str = self._format_ms_epoch_to_ist(
                        int(num), fmt="%B %d, %Y, %I:%M %p %Z"
                    )
                except Exception:
                    d_str = str(raw_d)

                msg_parts.append(f"\n⚠️ **Deadline:** {d_str}")

        msg_parts.append(f"*Posted by*: {notice.author} \n*On:* {post_date}")
        state["formatted_message"] = "\n".join(msg_parts)

        print("--- 5. Message Formatted ---")
        return state

    # -------- graph assembly ---------
    def _build_graph(self):
        workflow = StateGraph(PostState)
        workflow.add_node("extract_text", self.extract_text)
        workflow.add_node("classify_post", self.classify_post)
        workflow.add_node("match_job", self.match_job)
        workflow.add_node("extract_info", self.extract_info)
        workflow.add_node("format_message", self.format_message)
        workflow.set_entry_point("extract_text")
        workflow.add_edge("extract_text", "classify_post")
        workflow.add_edge("classify_post", "match_job")
        workflow.add_edge("match_job", "extract_info")
        workflow.add_edge("extract_info", "format_message")
        workflow.add_edge("format_message", END)
        return workflow.compile()

    # -------- public API ---------
    def format_notice(self, notice: Notice, jobs: Sequence[Job]) -> Dict[str, Any]:
        inputs = {"notice": notice, "jobs": list(jobs)}
        result: PostState = self.app.invoke(inputs)  # type: ignore
        matched_job = result.get("matched_job")
        extracted = result.get("extracted", {}) or {}
        job_company = (
            matched_job.company if matched_job else extracted.get("company_name")
        )
        job_role = matched_job.job_profile if matched_job else extracted.get("role")
        job_location_out = result.get("job_location") or (
            matched_job.location if matched_job else None
        )

        if matched_job:
            pkg_lpa = matched_job.package / 100000
            pkg_str = self._format_package(
                matched_job.package, matched_job.annum_months
            )
            pkg_breakdown = self.format_html_breakdown(matched_job.package_info)

        else:
            pkg_val = extracted.get("package")
            pkg_str = str(pkg_val) if pkg_val is not None else None
            pkg_breakdown = ""

        enriched: Dict[str, Any] = {
            **notice.model_dump(),
            "source": "Superset",
            "category": result.get("category"),
            "matched_job_id": result.get("matched_job_id"),
            "job_company": job_company,
            "job_role": job_role,
            "job_location": job_location_out,
            "package": pkg_str,
            "package_breakdown": pkg_breakdown,
            "formatted_message": result.get("formatted_message"),
        }
        return enriched

    def format_many(
        self,
        notices: Sequence[Notice],
        jobs: Sequence[Job],
    ) -> List[Dict[str, Any]]:
        """
        Format multiple notices.
        """
        final_records: List[Dict[str, Any]] = []

        for notice in notices:
            final_records.append(self.format_notice(notice, jobs))

        return final_records
