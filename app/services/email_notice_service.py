"""
Email Notice Service

LangGraph pipeline for processing non-placement email notices from Google Groups.
Classifies emails, extracts structured notice data, and saves to database.
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, TypedDict

from pydantic import BaseModel, Field, ValidationError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from core import safe_print, get_settings
from services.google_groups_client import GoogleGroupsClient
from services.notice_formatter_service import NoticeFormatterService


# ============================================================================
# Pydantic Models
# ============================================================================


class ExtractedNotice(BaseModel):
    """Extracted notice data from email"""

    is_notice: bool = Field(..., description="Whether this is a valid notice")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection")
    title: Optional[str] = Field(None, description="Notice title")
    content: Optional[str] = Field(None, description="Notice content")
    type: Optional[str] = Field(
        None,
        description="Notice type: announcement, hackathon, job_posting, shortlisting, update, webinar, reminder, internship_noc",
    )
    source: Optional[str] = Field(None, description="Source organization")
    deadline: Optional[str] = Field(None, description="Deadline if applicable")
    links: Optional[List[str]] = Field(None, description="Relevant URLs")
    additional_info: Optional[str] = Field(None, description="Other details")

    # Shortlisting / Internship NOC fields
    students: Optional[List[Dict[str, str]]] = Field(
        None,
        description="List of students with name, enrollment, and optionally company",
    )
    company_name: Optional[str] = Field(
        None, description="Company name for shortlisting/job posting"
    )
    role: Optional[str] = Field(None, description="Job role/profile")
    total_shortlisted: Optional[int] = Field(
        None, description="Total number of shortlisted students"
    )
    round: Optional[str] = Field(None, description="Interview round name")
    interview_date: Optional[str] = Field(None, description="Interview date")
    venue: Optional[str] = Field(None, description="Interview/event venue")

    # Job posting fields
    package: Optional[str] = Field(None, description="CTC/stipend")
    location: Optional[str] = Field(None, description="Job location")
    eligibility_criteria: Optional[List[str]] = Field(
        None, description="Eligibility requirements"
    )
    hiring_flow: Optional[List[str]] = Field(
        None, description="Selection process steps"
    )
    job_type: Optional[str] = Field(None, description="Full-time or Internship")

    # Webinar / Hackathon fields
    event_name: Optional[str] = Field(None, description="Event name")
    topic: Optional[str] = Field(None, description="Topic/theme")
    theme: Optional[str] = Field(None, description="Hackathon theme")
    speaker: Optional[str] = Field(None, description="Speaker name(s)")
    date: Optional[str] = Field(None, description="Event date")
    time: Optional[str] = Field(None, description="Event time")
    registration_link: Optional[str] = Field(None, description="Registration URL")

    # Hackathon specific
    start_date: Optional[str] = Field(None, description="Start date")
    end_date: Optional[str] = Field(None, description="End date")
    registration_deadline: Optional[str] = Field(
        None, description="Registration deadline"
    )
    prize_pool: Optional[str] = Field(None, description="Prize details")
    team_size: Optional[str] = Field(None, description="Team size requirements")
    organizer: Optional[str] = Field(None, description="Organizing body")


class NoticeDocument(BaseModel):
    """Notice document ready for database storage"""

    id: str = Field(..., alias="_id", description="Unique notice ID for MongoDB")
    title: str = Field(..., description="Notice title")
    content: str = Field(..., description="Notice content")
    author: str = Field("EmailNoticeBot", description="Author name")
    type: str = Field(..., description="Notice type")
    source: str = Field(..., description="Source")
    formatted_message: str = Field(..., description="Formatted message for sending")
    createdAt: int = Field(..., description="Creation timestamp (ms)")
    updatedAt: int = Field(..., description="Update timestamp (ms)")
    sent_to_telegram: bool = Field(False, description="Whether sent to Telegram")
    time_sent: Optional[str] = Field(None, description="Original email time in IST")
    deadline: Optional[str] = Field(None, description="Deadline if applicable")
    links: Optional[List[str]] = Field(None, description="Relevant URLs")
    students: Optional[List[Dict[str, str]]] = Field(
        None, description="List of students for internship_noc"
    )
    students_count: Optional[int] = Field(None, description="Number of students")


# ============================================================================
# Graph State
# ============================================================================


class NoticeGraphState(TypedDict):
    """LangGraph state for email notice processing"""

    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
    rejection_reason: Optional[str]
    extracted_notice: Optional[ExtractedNotice]
    validation_errors: Optional[List[str]]
    retry_count: Optional[int]


# NOTE: Classification is now fully LLM-based - no keyword filtering

# ============================================================================
# LLM Prompt
# ============================================================================

NOTICE_EXTRACTION_PROMPT = ChatPromptTemplate.from_template(
    """
You are an assistant that extracts structured notice data from emails sent to college/university groups.

**PHASE 1: CLASSIFICATION**

Determine if this email contains a relevant notice. A relevant notice is:
- An announcement, event, hackathon, job posting, shortlist, update, webinar, reminder, or internship NOC
- Relevant to students or academic community
- NOT a placement offer (those are handled separately - placement offers announce final selections with CTC/package for placed students)
- NOT spam or promotional content

If this is a PLACEMENT OFFER (announcing final selected candidates with their packages/CTC), return:
```json
{{
    "is_notice": false,
    "rejection_reason": "This is a placement offer, not a general notice"
}}
```

If this is SPAM or irrelevant, return:
```json
{{
    "is_notice": false,
    "rejection_reason": "Explain why it's spam/irrelevant"
}}
```

**PHASE 2: EXTRACTION (only if valid notice)**

Extract the notice information based on the type. All responses must include these base fields:
- is_notice: true
- title: Concise, descriptive title (max 100 chars)
- content: Main notice content - summarize key information clearly
- type: One of the types below
- source: Organization, company, or sender name
- deadline: ISO format (YYYY-MM-DDTHH:MM:SS) if mentioned, null otherwise
- links: Array of relevant URLs found in the email
- additional_info: Any other important details not captured elsewhere

**TYPE-SPECIFIC FIELDS:**

**1. shortlisting** - Interview shortlists, next round selections
Required fields:
- students: Array of {{"name": "Full Name", "enrollment": "Enrollment/Roll Number"}}
- company_name: Company name conducting the selection
- role: Job profile/position name
- total_shortlisted: Number of students shortlisted (integer)
Optional: round (e.g., "Technical Round 1", "HR Round"), venue, interview_date

**2. job_posting** - Job opportunities, internships open for applications
Required fields:
- company_name: Company name
- role: Job profile/position title
Optional fields:
- package: CTC/stipend (e.g., "6 LPA", "₹25000/month")
- location: Job location(s)
- eligibility_criteria: Array of eligibility requirements (e.g., ["B.Tech CSE/IT", "CGPA > 7.0", "No active backlogs"])
- hiring_flow: Array of selection process steps (e.g., ["Online Test", "Technical Interview", "HR Interview"])
- job_type: "Full-time" or "Internship"

**3. webinar** - Online/offline seminars, workshops, sessions
Required fields:
- event_name: Name of the webinar/session
Optional fields:
- topic: Subject/topic being covered
- speaker: Speaker name(s) and designation
- date: Event date (ISO format)
- time: Event time (e.g., "2:00 PM IST")
- venue: Location or platform (e.g., "Zoom", "Auditorium")
- registration_link: URL to register

**4. hackathon** - Coding competitions, hackathons, tech contests
Required fields:
- event_name: Name of the hackathon/competition
Optional fields:
- theme: Hackathon theme or problem statement
- start_date: Start date (ISO format)
- end_date: End date (ISO format)
- registration_deadline: Last date to register (ISO format)
- registration_link: URL to register
- prize_pool: Prize details (e.g., "₹1,00,000", "Goodies + Certificates")
- team_size: Team size requirements (e.g., "2-4 members", "Individual")
- venue: Location or "Online"
- organizer: Organizing body/club

**5. internship_noc** - List of students joining internships, NOC lists
Required fields:
- students: Array of {{"name": "Full Name", "enrollment": "Enrollment Number", "company": "Company Name"}}
Optional: noc_type (e.g., "Summer Internship", "6-month Internship")

**6. update** - Updates on ongoing processes, status changes, minor operational info
Just use base fields. Content should summarize the update clearly.

**7. announcement** - General announcements, news, policy updates
Just use base fields. Content should capture the full announcement.

**8. reminder** - Deadline reminders, follow-ups
Required fields:
- deadline: The deadline being reminded about (ISO format)
Optional: original_notice (what this is a reminder for)

**EXAMPLE RESPONSES:**

Shortlisting example:
```json
{{
    "is_notice": true,
    "title": "Microsoft - SDE Intern Shortlist for Technical Round",
    "content": "Students shortlisted for Microsoft SDE Intern Technical Round scheduled for Jan 20, 2026.",
    "type": "shortlisting",
    "source": "Training & Placement Cell",
    "company_name": "Microsoft",
    "role": "SDE Intern",
    "round": "Technical Round 1",
    "interview_date": "2026-01-20",
    "total_shortlisted": 25,
    "students": [
        {{"name": "Rahul Sharma", "enrollment": "21103001"}},
        {{"name": "Priya Singh", "enrollment": "21103045"}}
    ],
    "deadline": null,
    "links": [],
    "additional_info": "Carry your college ID and resume"
}}
```

Job Posting example:
```json
{{
    "is_notice": true,
    "title": "Google - Software Engineer Opening",
    "content": "Google is hiring Software Engineers. Apply before the deadline.",
    "type": "job_posting",
    "source": "Google",
    "company_name": "Google",
    "role": "Software Engineer",
    "package": "25 LPA",
    "location": "Bangalore, Hyderabad",
    "eligibility_criteria": ["B.Tech/M.Tech CSE/IT/ECE", "CGPA >= 7.5", "No active backlogs"],
    "hiring_flow": ["Online Assessment", "Technical Interview (2 rounds)", "HR Interview"],
    "job_type": "Full-time",
    "deadline": "2026-01-25T23:59:00",
    "links": ["https://careers.google.com/apply"],
    "additional_info": null
}}
```

**PRIVACY RULES:**
- Do NOT include forwarding headers or sender email addresses in content
- Focus on the actual notice content, not email metadata
- For student lists, only include name and enrollment number (no emails/phone numbers)

Return ONLY the raw JSON object, no explanations or markdown code fences.

Email Subject: {subject}
Email Body: {body}
"""
)


# ============================================================================
# Email Notice Service
# ============================================================================


class EmailNoticeService:
    """
    Email notice service using LangGraph pipeline.

    Handles:
    - Fetching emails via GoogleGroupsClient
    - Classifying non-placement notices
    - LLM-based notice extraction
    - Saving to database
    """

    def __init__(
        self,
        email_client: Optional[GoogleGroupsClient] = None,
        google_api_key: Optional[str] = None,
        db_service: Optional[Any] = None,
        model: str = "gemini-2.5-pro",
    ):
        """
        Initialize email notice service.

        Args:
            email_client: GoogleGroupsClient instance for fetching emails
            google_api_key: API key for LLM
            db_service: Database service for saving notices
            model: LLM model to use
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        self.email_client = email_client or GoogleGroupsClient()
        api_key = google_api_key or get_settings().google_api_key
        self.db_service = db_service

        # Initialize formatter service for notice formatting
        self.formatter_service = NoticeFormatterService(google_api_key=api_key)

        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=0,
            google_api_key=api_key,
        )

        # Build LangGraph pipeline
        self.app = self._build_graph()

        self.logger.info("EmailNoticeService initialized")

    # =========================================================================
    # LangGraph Pipeline
    # =========================================================================

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow"""
        workflow = StateGraph(NoticeGraphState)

        # Add nodes
        workflow.add_node("classify", self._classify_email)
        workflow.add_node("extract_notice", self._extract_notice)
        workflow.add_node("validate", self._validate_notice)
        workflow.add_node("display_results", self._display_results)

        # Set entry point
        workflow.set_entry_point("classify")

        # Add edges
        workflow.add_conditional_edges("classify", self._decide_to_extract)
        workflow.add_conditional_edges("extract_notice", self._should_retry)
        workflow.add_edge("validate", "display_results")
        workflow.add_edge("display_results", END)

        return workflow.compile()

    def _classify_email(self, state: NoticeGraphState) -> NoticeGraphState:
        """Pass email to LLM for classification - no keyword filtering"""
        safe_print("--- Notice Classification ---")

        # Always mark as relevant and let the LLM decide during extraction
        # The LLM prompt handles classification and will return is_notice: false for irrelevant emails
        safe_print("Passing to LLM for classification...")

        return {
            **state,
            "is_relevant": True,  # Let LLM decide
            "confidence_score": 1.0,
            "classification_reason": "LLM-based classification",
            "retry_count": 0,
        }

    def _extract_notice(self, state: NoticeGraphState) -> NoticeGraphState:
        """LLM-based notice extraction"""
        safe_print("--- Notice Extraction ---")
        email_data = state["email"]
        retry_count = state.get("retry_count", 0) or 0

        chain = NOTICE_EXTRACTION_PROMPT | self.llm

        try:
            response = chain.invoke(
                {
                    "subject": email_data.get("subject", ""),
                    "body": email_data.get("body", ""),
                }
            )

            # Extract JSON from response
            json_content = self._extract_json(str(response.content))
            data = json.loads(json_content)

            if not data.get("is_notice", False):
                rejection_reason = data.get(
                    "rejection_reason", "LLM determined this is not a valid notice"
                )
                safe_print(f"Rejected: {rejection_reason}")
                return {
                    **state,
                    "extracted_notice": None,
                    "rejection_reason": rejection_reason,
                }

            notice = ExtractedNotice(**data)
            safe_print(f"Extracted notice: {notice.title}")

            return {
                **state,
                "extracted_notice": notice,
                "validation_errors": None,
                "rejection_reason": None,
            }

        except (ValidationError, json.JSONDecodeError) as e:
            error_msg = str(e)
            safe_print(f"Extraction error: {error_msg}")

            if retry_count < 2:
                return {
                    **state,
                    "validation_errors": [error_msg],
                    "retry_count": retry_count + 1,
                }
            else:
                return {
                    **state,
                    "extracted_notice": None,
                    "validation_errors": [error_msg],
                }

    def _validate_notice(self, state: NoticeGraphState) -> NoticeGraphState:
        """Validate extracted notice"""
        notice = state.get("extracted_notice")

        if not notice:
            return state

        issues = []
        if not notice.title or len(notice.title) < 3:
            issues.append("Title too short")
        if not notice.content or len(notice.content) < 10:
            issues.append("Content too short")
        if not notice.type:
            issues.append("Missing notice type")

        if issues:
            safe_print(f"Validation issues: {issues}")
            return {**state, "validation_errors": issues}

        safe_print("Notice validated successfully")
        return {**state, "validation_errors": None}

    def _display_results(self, state: NoticeGraphState) -> NoticeGraphState:
        """Display extraction results"""
        notice = state.get("extracted_notice")
        rejection = state.get("rejection_reason")

        safe_print("=" * 50)
        if rejection:
            safe_print(f"Rejected: {rejection}")
        elif notice:
            safe_print(f"Notice: {notice.title}")
            safe_print(f"Type: {notice.type}")
        else:
            safe_print("No valid notice extracted")
        safe_print("=" * 50)

        return state

    def _decide_to_extract(self, state: NoticeGraphState) -> str:
        """Decide whether to proceed with extraction"""
        if state.get("is_relevant", False):
            return "extract_notice"
        return "display_results"

    def _should_retry(self, state: NoticeGraphState) -> str:
        """Determine if extraction should be retried"""
        errors = state.get("validation_errors")
        retry_count = state.get("retry_count", 0) or 0
        notice = state.get("extracted_notice")

        if not errors or notice is not None or retry_count >= 2:
            return "validate"
        return "extract_notice"

    @staticmethod
    def _extract_json(response_content: str) -> str:
        """Extract JSON from LLM response"""
        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        match = re.search(json_pattern, response_content)
        return match.group(1).strip() if match else response_content.strip()

    # =========================================================================
    # Public API
    # =========================================================================

    def process_emails(self, mark_as_read: bool = True) -> List[NoticeDocument]:
        """
        Fetch and process unread emails for notices sequentially.

        Process:
        1. Get all unread message IDs
        2. For each ID:
           a. Fetch email content (w/o marking read)
           b. Process and extract notice
           c. Save to database
           d. Mark as read (if successful or if rejected/irrelevant)

        Args:
            mark_as_read: Whether to mark emails as read after processing

        Returns:
            List of NoticeDocument objects for valid notices
        """
        safe_print("Fetching unread email IDs...")
        try:
            email_ids = self.email_client.get_unread_message_ids()
        except Exception as e:
            self.logger.error(f"Failed to fetch email IDs: {e}")
            safe_print(f"Error fetching email IDs: {e}")
            return []

        safe_print(f"Found {len(email_ids)} unread emails")

        notices: List[NoticeDocument] = []

        for e_id in email_ids:
            try:
                # 1. Fetch email content (without marking read yet)
                email_data = self.email_client.fetch_email(e_id, mark_as_read=False)

                if not email_data:
                    safe_print(f"Failed to fetch content for email {e_id}, skipping")
                    continue

                # 2. Process email
                result = self.process_single_email(email_data)

                # 3. Save if valid notice
                if result:
                    notices.append(result)
                    if self.db_service:
                        success, _ = self.db_service.save_notice(result.model_dump())
                        if success:
                            safe_print(f"Saved notice: {result.title}")

                # 4. Mark as read if configured
                # We mark as read even if it wasn't a relevant notice to avoid reprocessing
                if mark_as_read:
                    self.email_client.mark_as_read(e_id)

            except Exception as e:
                self.logger.error(f"Error processing email {e_id}: {e}")
                safe_print(f"Error processing email {e_id}: {e}")
                # We do NOT mark as read here so it can be retried

        safe_print(f"Processed {len(notices)} notices")
        return notices

    def process_single_email(
        self, email_data: Dict[str, str]
    ) -> Optional[NoticeDocument]:
        """
        Process a single email through the pipeline.

        Args:
            email_data: Dict with subject, sender, body keys

        Returns:
            NoticeDocument if valid notice, None otherwise
        """
        initial_state: NoticeGraphState = {
            "email": email_data,
            "is_relevant": None,
            "confidence_score": None,
            "classification_reason": None,
            "rejection_reason": None,
            "extracted_notice": None,
            "validation_errors": None,
            "retry_count": 0,
        }

        result = self.app.invoke(initial_state)

        notice = result.get("extracted_notice")
        if not notice or not result.get("is_relevant"):
            return None

        return self._create_notice_document(notice, email_data)

    @staticmethod
    def _format_date_ist(date_str: Optional[str]) -> str:
        """Format a date string to IST format, matching NoticeFormatterService style."""
        if not date_str:
            return "Not specified"
        try:
            from zoneinfo import ZoneInfo

            # Try parsing ISO format
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime(
                "%B %d, %Y at %I:%M %p %Z"
            )
        except Exception:
            # Return as-is if parsing fails
            return date_str

    @staticmethod
    def _prettify_raw_text(raw: str) -> str:
        """Lightly format raw text for direct sending.

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
                if not blank:
                    cleaned.append("")
                blank = True
            else:
                cleaned.append(ln)
                blank = False

        return "\n".join(cleaned).strip()

    def _create_notice_document(
        self,
        notice: ExtractedNotice,
        email_data: Dict[str, str],
    ) -> NoticeDocument:
        """Create a NoticeDocument from extracted data with formatting matching Superset notices."""
        ts = datetime.utcnow().timestamp()
        safe_title = (notice.title or "notice").replace(" ", "_")[:30]
        notice_id = f"notice_{safe_title}_{int(ts)}"

        # Extract author from email sender (prioritize forwarded sender)
        body = email_data.get("body", "")
        forwarded_sender = GoogleGroupsClient.extract_forwarded_sender(body)
        author = forwarded_sender or email_data.get("sender") or "EmailNoticeBot"

        time_sent = email_data.get("time_sent")
        post_date = (
            time_sent
            if time_sent
            else datetime.utcnow().strftime("%B %d, %Y at %I:%M %p IST")
        )

        # Build formatted message matching NoticeFormatterService style
        msg_parts: List[str] = [f"**{notice.title}**\n"]
        notice_type = notice.type or "announcement"

        # --- Passthrough formatting for 'update' or 'announcement' ---
        if notice_type in {"update", "announcement"}:
            prettified = self._prettify_raw_text(notice.content or "")
            prettified += f"\n\n*Posted by*: {author} \n*On:* {post_date}"
            formatted = prettified

        # --- Shortlisting format ---
        elif notice_type == "shortlisting":
            msg_parts.append("**🎉 Shortlisting Update**")

            company = notice.company_name or notice.source
            if company:
                msg_parts.append(f"**Company:** {company}")

            if notice.role:
                msg_parts.append(f"**Role:** {notice.role}")

            if notice.round:
                msg_parts.append(f"**Round:** {notice.round}")

            if notice.location or notice.venue:
                msg_parts.append(f"**Venue:** {notice.venue or notice.location}")

            if notice.interview_date:
                interview_dt = self._format_date_ist(notice.interview_date)
                msg_parts.append(f"**Interview Date:** {interview_dt}")

            msg_parts.append("")

            if notice.students:
                total = notice.total_shortlisted or len(notice.students)
                student_list = "\n".join(
                    [
                        f"- {s.get('name', 'Unknown')} ({s.get('enrollment', 'N/A')})"
                        for s in notice.students
                        if isinstance(s, dict)
                    ]
                )
                msg_parts.append(f"**Total Shortlisted:** {total}")
                msg_parts.append("Congratulations to the following students:")
                msg_parts.append(student_list)
                msg_parts.append("\n")

            if notice.content:
                msg_parts.append(notice.content)

            if notice.hiring_flow:
                hiring_flow_list = "\n".join(
                    [f"{i+1}. {step}" for i, step in enumerate(notice.hiring_flow)]
                )
                msg_parts.append(f"\n**Hiring Process:**\n{hiring_flow_list}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Webinar format ---
        elif notice_type == "webinar":
            msg_parts.append("**🎓 Webinar Details**")

            event = notice.event_name or notice.title
            msg_parts.append(f"**Event:** {event}")

            if notice.topic:
                msg_parts.append(f"**Topic:** {notice.topic}")

            if notice.speaker:
                msg_parts.append(f"**Speaker:** {notice.speaker}")

            # Handle date and time
            if notice.date and notice.time:
                date_fmt = self._format_date_ist(notice.date)
                msg_parts.append(f"**When:** {date_fmt} | {notice.time}")
            elif notice.date:
                date_fmt = self._format_date_ist(notice.date)
                msg_parts.append(f"**When:** {date_fmt}")
            elif notice.time:
                msg_parts.append(f"**Time:** {notice.time}")

            venue = notice.venue or notice.location
            if venue:
                msg_parts.append(f"**Venue / Platform:** {venue}")

            if notice.source:
                msg_parts.append(f"**Organized by:** {notice.source}")

            if notice.content:
                msg_parts.append(f"\n{notice.content}")

            reg_link = notice.registration_link
            if reg_link:
                msg_parts.append(f"\n**Registration:** {reg_link}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    if link != reg_link:  # Avoid duplicate
                        msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Hackathon format ---
        elif notice_type == "hackathon":
            msg_parts.append("**🏁 Hackathon**")

            event = notice.event_name or notice.title
            msg_parts.append(f"**Event:** {event}")

            theme = notice.theme or notice.topic
            if theme:
                msg_parts.append(f"**Theme:** {theme}")

            # Handle duration
            if notice.start_date or notice.end_date:
                start_fmt = (
                    self._format_date_ist(notice.start_date)
                    if notice.start_date
                    else None
                )
                end_fmt = (
                    self._format_date_ist(notice.end_date) if notice.end_date else None
                )
                if start_fmt and end_fmt:
                    msg_parts.append(f"**Duration:** {start_fmt} — {end_fmt}")
                else:
                    msg_parts.append(f"**Date:** {start_fmt or end_fmt}")

            if notice.team_size:
                msg_parts.append(f"**Team Size:** {notice.team_size}")

            if notice.prize_pool:
                msg_parts.append(f"**Prize Pool:** {notice.prize_pool}")

            venue = notice.venue or notice.location
            if venue:
                msg_parts.append(f"**Venue / Platform:** {venue}")

            organizer = notice.organizer or notice.source
            if organizer:
                msg_parts.append(f"**Organized by:** {organizer}")

            if notice.content:
                msg_parts.append(f"\n{notice.content}")

            reg_link = notice.registration_link
            if reg_link:
                msg_parts.append(f"\n**Registration:** {reg_link}")

            reg_deadline = notice.registration_deadline or notice.deadline
            if reg_deadline:
                deadline_fmt = self._format_date_ist(reg_deadline)
                msg_parts.append(f"\n⚠️ **Registration Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    if link != reg_link:  # Avoid duplicate
                        msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Job Posting format ---
        elif notice_type == "job_posting":
            company = notice.company_name or notice.source
            role = notice.role

            # Update title for job postings
            if company and role:
                msg_parts[0] = (
                    f"**Open for applications - {company}'s Job Profile - {role}**\n"
                )
            elif company:
                msg_parts[0] = f"**Open for applications - {company}**\n"

            msg_parts.append("**📢 Job Posting**")

            if company:
                msg_parts.append(f"**Company:** {company}")

            if role:
                msg_parts.append(f"**Role:** {role}")

            if notice.location:
                msg_parts.append(f"**Location:** {notice.location}")

            if notice.package:
                msg_parts.append(f"**CTC:** {notice.package}")

            if notice.job_type:
                msg_parts.append(f"**Type:** {notice.job_type}")

            if notice.content:
                msg_parts.append(f"\n{notice.content}")

            if notice.eligibility_criteria:
                eligibility_str = "\n".join(
                    [f"- {item}" for item in notice.eligibility_criteria]
                )
                msg_parts.append(f"\n**Eligibility Criteria:**\n{eligibility_str}")

            if notice.hiring_flow:
                hiring_flow_str = "\n".join(
                    [f"{i+1}. {step}" for i, step in enumerate(notice.hiring_flow)]
                )
                msg_parts.append(f"\n**Hiring Flow:**\n{hiring_flow_str}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Apply / Links:**")
                for link in notice.links[:5]:
                    msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Internship NOC format ---
        elif notice_type == "internship_noc" and notice.students:
            students = notice.students
            msg_parts.append("**📋 Internship NOC List**")
            msg_parts.append(f"\n**Total Students:** {len(students)}\n")

            # Group by company if available
            companies: Dict[str, List[Dict[str, str]]] = {}
            for student in students:
                company = student.get("company", "General")
                if company not in companies:
                    companies[company] = []
                companies[company].append(student)

            # Format by company
            if len(companies) > 1 or "General" not in companies:
                for company, company_students in companies.items():
                    msg_parts.append(
                        f"**{company}** ({len(company_students)} students)"
                    )
                    for s in company_students:
                        name = s.get("name", "Unknown")
                        enrollment = s.get("enrollment", "N/A")
                        msg_parts.append(f"- {name} ({enrollment})")
                    msg_parts.append("")
            else:
                # No company grouping, just list students
                for s in students:
                    name = s.get("name", "Unknown")
                    enrollment = s.get("enrollment", "N/A")
                    msg_parts.append(f"- {name} ({enrollment})")

            if notice.content:
                msg_parts.append(f"\n{notice.content}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Reminder format ---
        elif notice_type == "reminder":
            msg_parts.append("**⏰ Reminder**")

            if notice.content:
                msg_parts.append(f"\n{notice.content}")

            if notice.additional_info:
                msg_parts.append(f"\n{notice.additional_info}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        # --- Default / fallback format ---
        else:
            msg_parts.append(f"**🔔 {notice_type.replace('_', ' ').capitalize()}**\n")

            if notice.content:
                msg_parts.append(notice.content)

            if notice.additional_info:
                msg_parts.append(f"\n{notice.additional_info}")

            if notice.deadline:
                deadline_fmt = self._format_date_ist(notice.deadline)
                msg_parts.append(f"\n⚠️ **Deadline:** {deadline_fmt}")

            if notice.links:
                msg_parts.append("\n**🔗 Links:**")
                for link in notice.links[:5]:
                    msg_parts.append(f"- {link}")

            msg_parts.append(f"\n*Posted by*: {author} \n*On:* {post_date}")
            formatted = "\n".join(msg_parts)

        students_list = notice.students if notice.type == "internship_noc" else None
        students_count = len(notice.students) if notice.students else None

        return NoticeDocument(
            _id=notice_id,
            title=notice.title or "Notice",
            content=notice.content or "",
            author=author,
            type=notice.type or "announcement",
            source="Email Notice Service",
            formatted_message=formatted.strip(),
            createdAt=int(ts * 1000),
            updatedAt=int(ts * 1000),
            sent_to_telegram=False,
            time_sent=time_sent,
            deadline=notice.deadline,
            links=notice.links,
            students=students_list,
            students_count=students_count,
        )
