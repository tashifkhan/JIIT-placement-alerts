"""
Placement Service

Wraps the placement_stats.py email processing logic with DI support.
Implements IPlacementService protocol.

Full LangGraph pipeline for extracting placement offers from emails:
1. Classification - keyword-based relevance scoring
2. Extraction - LLM-based structured data extraction with retry
3. Validation - data validation and enhancement
4. Privacy sanitization - remove sender/forward info
"""

import os
import re
import json
import imaplib
import email
import logging
from email.header import decode_header
from datetime import datetime
from typing import List, Optional, Dict, Any, TypedDict

from pydantic import BaseModel, Field, ValidationError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from core.config import safe_print


# ============================================================================
# Pydantic Models
# ============================================================================


class Student(BaseModel):
    """Student model for placement offers"""

    name: str
    enrollment_number: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    package: Optional[float] = None


class RolePackage(BaseModel):
    """Role and package model"""

    role: str
    package: Optional[float] = None
    package_details: Optional[str] = None


class PlacementOffer(BaseModel):
    """Placement offer data model"""

    company: str
    roles: List[RolePackage]
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
    students_selected: List[Student]
    number_of_offers: int
    additional_info: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    time_sent: Optional[str] = None


# ============================================================================
# Graph State
# ============================================================================


class GraphState(TypedDict):
    """LangGraph state for email processing"""

    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
    rejection_reason: Optional[str]
    extracted_offer: Optional[PlacementOffer]
    validation_errors: Optional[List[str]]
    retry_count: Optional[int]


# ============================================================================
# Classification Keywords
# ============================================================================


PLACEMENT_KEYWORDS = [
    "tnp",
    "placement",
    "offer",
    "congratulations",
    "selected",
    "hired",
    "job offer",
    "employment",
    "position",
    "role",
    "package",
    "salary",
    "joining",
    "campus recruitment",
    "pre-placement",
    "final placement",
    "internship",
    "stipend",
    "ctc",
    "compensation",
    "ppo",
]

COMPANY_INDICATORS = [
    "company",
    "organization",
    "firm",
    "corporation",
    "ltd",
    "inc",
    "pvt",
    "technologies",
    "solutions",
    "services",
    "consulting",
    "systems",
]

NEGATIVE_KEYWORDS = [
    "spam",
    "advertisement",
    "promotional",
    "newsletter",
    "unsubscribe",
    "marketing",
    "sale",
    "discount",
    "free",
    "click here",
]


# ============================================================================
# LLM Prompt
# ============================================================================


EXTRACTION_PROMPT = ChatPromptTemplate.from_template(
    """
You are an expert assistant specializing in extracting structured data from placement offer emails.

Your task involves a two-phase process:

**PHASE 1: CLASSIFICATION AND VALIDATION OF FINAL PLACEMENT OFFER**

1.  **Objective:** Determine if the provided email content unequivocally represents a *final, confirmed placement offer*. This initial phase is crucial for filtering out non-offer-related communications, such as interim shortlists, interview invitations, or general company updates.

2.  **Strict Criteria for a Valid Final Placement Offer:**
    *   **Existence of Package:** The email MUST explicitly mention a quantifiable compensation package (e.g., CTC, stipend, base salary, annual salary, or an equivalent remuneration figure) for at least one role. If NO package details (not even a stipend for an internship) are discernible anywhere in the email content, it is NOT considered a final placement offer. This is a non-negotiable requirement.
    *   **Finality of Offer:** The communication must unequivocally signify a *final selection or offer*. It should NOT be an interim shortlist, a call for interviews, a notification for the next selection round, or a generic informational email. Look for definite offer language such as "final offer," "selected candidates," "placement offer," "congratulations on your selection," "offer letter attached," or terms indicating successful completion of the entire selection process leading to placement.
    *   **Placement Status:** The candidates mentioned (if any) should be explicitly considered *placed* or *offered* a position, not merely shortlisted for further evaluation or pending additional steps.
    *   **Training/Internship with FTE Conversion:** Explicitly INCLUDE offers that are for a "training program," "internship," or "probationary period" IF AND ONLY IF they clearly state that this leads to a Full-Time Employment (FTE) or final placement offer with a specified package. Treat "shortlisted for training leading to FTE" as a valid placement offer if the final package is known.

3.  **Action Based on Classification:**
    *   **If the email DOES NOT meet ALL of the above "Strict Criteria for a Valid Final Placement Offer":** You MUST immediately return a JSON object with the following structure. Provide a precise `rejection_reason` explaining which criterion was not met. Do NOT proceed to Phase 2 for detailed data extraction.
        ```json
        {{
            "is_final_placement_offer": false,
            "rejection_reason": "Provide a specific reason (e.g., 'No package mentioned', 'Appears to be an interview invitation', 'Not a final offer; seems to be an interim shortlist')."
        }}
        ```
    *   **If the email MEETS ALL "Strict Criteria for a Valid Final Placement Offer":** Set `"is_final_placement_offer": true` and proceed directly to Phase 2 for detailed data extraction, using the schema provided below.

**PHASE 2: DETAILED DATA EXTRACTION (ONLY IF VALIDATED IN PHASE 1)**

Analyze the email content and extract the information into a JSON format that strictly matches the schema below.

PRIVACY RULES (STRICT):
- Do NOT include email headers or sender information in any extracted field (e.g., do not copy lines like "From:", "Sender:", "Forwarded message", "Fwd:").
- Ignore any forwarding/quoted email headers and do NOT mention that the email was forwarded.
- Only extract offer-related content. If headers appear in the body, exclude them from "additional_info" as well.

Schema:
{{
    "is_final_placement_offer": "boolean - this should always be true if you reach Phase 2",
    "company": "string",
    "roles": [
        {{
            "role": "string",
            "package": "numeric CTC value as float (in LPA) - null if not applicable or not explicitly mentioned for this *specific role*, even if a general package exists in the email.",
            "package_details": "string containing detailed breakdown including base salary, stipend, bonuses, benefits, etc. (optional)"
        }}
    ],
    "job_location": ["list of strings"] (optional),
    "joining_date": "string in YYYY-MM-DD format (optional)",
    "students_selected": [
        {{
            "name": "string",
            "enrollment_number": "string (optional)",
            "email": "string (optional)",
            "role": "string - assign role from available roles, if only one role exists use that",
            "package": "numeric CTC value as float (in LPA) - specific to this student if mentioned and quantifiable"
        }}
    ],
    "number_of_offers": "integer (count of students_selected)",
    "additional_info": "string containing any other relevant details (optional)"
}}

IMPORTANT PACKAGE AND STIPEND EXTRACTION RULES:
    
1.  PACKAGE ASSIGNMENT:
    - Associate each student with their specific role if mentioned.
    - If only one role exists in the email, assign that role to all students.
    - Extract CTC as a single float value (not an array).
    - Convert all amounts to LPA (Lakhs Per Annum).
    - If the backage has a breakdown include the total not the breakdown in the `package` field.
    - **Crucial:** While a package must exist in the email for Phase 1 validation, if a package is expected for a *specific role or student* but cannot be found or accurately quantified, leave the respective `package` field as `null`.

2.  STIPEND HANDLING:
    - For INTERNSHIP-ONLY offers: Include the stipend in the `package` field (multiply monthly stipend by 12 to convert to LPA).
    - For FULL-TIME offers (including conditional/PPO): Show only the final CTC in the `package` field. Put any detailed stipend information (e.g., during training) in the `package_details` field.
    - For CONDITIONAL full-time offers: Show only the guaranteed final CTC amount in the `package` field. Ignore any temporary stipends that are not part of the final CTC.
    - For PPO (Pre-Placement Offers): Show only the final CTC in the `package` field.

3.  PACKAGE RANGE HANDLING:
    - If a package is mentioned as a range (e.g., "8-12 LPA", "10-15 lakhs"), use the **LOWEST** quantifiable value for the `package` field (e.g., "8-12 LPA" → 8.0, "10-15 lakhs" → 10.0).
    - If multiple packages are mentioned for the same role, use the lowest quantifiable value.

4.  CONVERSION EXAMPLES:
    - "10 LPA CTC + 50k monthly stipend" (full-time) → package: 10.0, package_details: "10 LPA CTC + 50k monthly stipend during training"
    - "25k monthly stipend" (internship only) → package: 3.0, package_details: "25k monthly stipend (internship)"
    - "8-12 LPA based on performance" → package: 8.0, package_details: "8-12 LPA based on performance"
    - "Conditional offer: 15 LPA after completion" → package: 15.0
    - "12 lakhs per annum" → package: 12.0
    - "The package is INR 8.65 Lakhs {{5.5 LPA (fixed) + 1.65 lakhs (performance-based pay) + 1.5 lakhs (night shift allowance)}}based on performance during the internship and, if converted, to a full-time role and the then prevailing market conditions." → package: 8.65, package_details: "5.5 LPA (fixed) + 1.65 lakhs (performance-based pay) + 1.5 lakhs (night shift allowance)"

Return only the raw JSON object, without any surrounding text, explanations, or markdown.

Email Content to analyze:
Subject: {subject}
Body: {body}
"""
)


# ============================================================================
# Helper Functions
# ============================================================================


def strip_headers_and_forwarded_markers(text: str) -> str:
    """
    Remove lines that look like email headers or forwarded markers.

    PRIVACY RULE: Never disclose sender or forwarding info in user-facing content.
    """
    if not text:
        return text

    header_patterns = [
        r"^\s*(From|Sender|Sent|To|Cc|Subject)\s*:.*$",
        r"^\s*(Fwd|FW)\s*:.*$",
        r"^\s*(Begin forwarded message|Forwarded message).*$",
        r"^\s*On .+ wrote:\s*$",
    ]

    lines = text.splitlines()
    cleaned_lines: List[str] = []
    for ln in lines:
        if any(re.search(pat, ln, flags=re.IGNORECASE) for pat in header_patterns):
            continue
        cleaned_lines.append(ln)

    cleaned = "\n".join(cleaned_lines)

    # Remove inline "via" sender mentions
    cleaned = re.sub(r"\bvia\s+[^\s\n]+", "", cleaned, flags=re.IGNORECASE)

    # Redact explicit phrases stating it's forwarded
    cleaned = re.sub(r"\bforward(ed)?(\s+message)?\b", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


def extract_forwarded_date(text: str) -> Optional[str]:
    """
    Extract the date from forwarded message headers and convert to ISO format.

    Looks for patterns like:
    - "Date: Thu, 21 Aug, 2025, 4:51 pm"
    - "Date: Wed, 20 Aug 2025 at 13:20"

    Returns:
        ISO datetime string (e.g., "2025-08-21T16:51:00+05:30") or None if not found
    """
    if not text:
        return None

    # Try multiple patterns for date extraction
    date_patterns = [
        r"Date:\s*([^\n\r]+?)(?:\s*\n|\s*\r|\s*Subject:|$)",  # Standard newline
        r"Date:\s*(.+?)(?:<br>|Subject:|To:|$)",  # HTML br or Subject/To
        r"Date:\s*([A-Za-z]{3},?\s+\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}(?:,?\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?)",  # Explicit date format
    ]

    date_str = None
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip().rstrip(",")
            break

    if not date_str:
        return None

    # Clean up the date string - remove extra commas
    date_str = re.sub(r",\s*,", ",", date_str)
    # Remove any HTML tags
    date_str = re.sub(r"<[^>]+>", "", date_str).strip()
    # Remove trailing Subject: or To: that might have been captured
    date_str = re.sub(
        r"\s*(Subject|To)\s*:.*$", "", date_str, flags=re.IGNORECASE
    ).strip()

    if not date_str:
        return None

    try:
        from dateutil import parser as date_parser
        from datetime import timezone, timedelta
        import unicodedata

        # Normalize Unicode whitespace (including \u202f narrow no-break space)
        date_str = "".join(
            " " if unicodedata.category(c) in ("Zs", "Cc") else c for c in date_str
        )
        date_str = " ".join(date_str.split())  # Collapse multiple spaces

        # Parse the date string
        parsed_date = date_parser.parse(date_str, fuzzy=True)

        # Define IST timezone (UTC+5:30)
        ist = timezone(timedelta(hours=5, minutes=30))

        # If the parsed date has no timezone, assume it's already IST
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=ist)
        else:
            # Convert to IST
            parsed_date = parsed_date.astimezone(ist)

        # Return ISO format datetime string
        return parsed_date.isoformat()
    except Exception:
        # If parsing fails, return None
        return None


def extract_forwarded_sender(text: str) -> Optional[str]:
    """
    Extract the original sender from forwarded message headers.

    Looks for patterns like:
    - "From: Vinod Kumar <vinod.jptnp@gmail.com>"
    - "From: vinod.jptnp@gmail.com"

    This is used to get the actual sender when an email is forwarded.

    Returns:
        The original sender email/name or None if not a forwarded message
    """
    if not text:
        return None

    # Check if this is a forwarded message
    forwarded_patterns = [
        r"-+\s*Forwarded message\s*-+",
        r"Begin forwarded message",
        r"Fwd:",
        r"FW:",
    ]

    is_forwarded = any(
        re.search(pat, text, re.IGNORECASE) for pat in forwarded_patterns
    )

    if not is_forwarded:
        return None

    # Pattern to match "From: Name <email>" or "From: email" in forwarded headers
    # This captures the content after "From:" until newline
    from_pattern = r"From:\s*(.+?)(?:\n|$)"
    match = re.search(from_pattern, text, re.IGNORECASE)

    if match:
        sender_str = match.group(1).strip()
        # Clean up any trailing characters
        sender_str = sender_str.rstrip(",")
        return sender_str

    return None


def extract_json_from_response(response_content: str) -> str:
    """Extract JSON from LLM response, handling markdown code blocks"""
    json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, response_content)
    return match.group(1).strip() if match else response_content.strip()


# ============================================================================
# Placement Service
# ============================================================================


class PlacementService:
    """
    Placement service implementing IPlacementService protocol.

    Handles:
    - Fetching placement emails via IMAP
    - LangGraph pipeline for classification, extraction, validation
    - Privacy sanitization
    - Saving to database
    """

    def __init__(
        self,
        email_address: Optional[str] = None,
        app_password: Optional[str] = None,
        google_api_key: Optional[str] = None,
        db_service: Optional[Any] = None,
        notification_formatter: Optional[Any] = None,
        email_client: Optional[Any] = None,
        model: str = "gemini-2.5-pro",
        output_file: Optional[str] = None,
    ):
        """
        Initialize placement service.

        Args:
            email_address: Email to fetch from (deprecated, use email_client)
            app_password: App password for email (deprecated, use email_client)
            google_api_key: API key for LLM
            db_service: Database service for saving offers
            notification_formatter: Formatter for creating placement notices (injected)
            email_client: GoogleGroupsClient instance for fetching emails
            model: LLM model to use
            output_file: JSON output file path (fallback)
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        # Email client (preferred) or legacy credentials
        self.email_client = email_client
        self.email_address = email_address or os.getenv("PLCAMENT_EMAIL")
        self.app_password = app_password or os.getenv("PLCAMENT_APP_PASSWORD")
        api_key = google_api_key or os.getenv("GOOGLE_API_KEY")

        self.db_service = db_service
        self.notification_formatter = notification_formatter
        self.output_file = output_file or os.path.join(
            os.getcwd(), "data", "placement_offers.json"
        )

        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=0,
            google_api_key=api_key,
        )

        # Build LangGraph pipeline
        self.app = self._build_graph()

        self.logger.info("PlacementService initialized")

    # =========================================================================
    # LangGraph Pipeline
    # =========================================================================

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow"""
        workflow = StateGraph(GraphState)

        # Add nodes
        workflow.add_node("classify", self._classify_email)
        workflow.add_node("extract_info", self._extract_info)
        workflow.add_node("validate_and_enhance", self._validate_and_enhance)
        workflow.add_node("sanitize_privacy", self._sanitize_privacy)
        workflow.add_node("display_results", self._display_results)

        # Set entry point
        workflow.set_entry_point("classify")

        # Add conditional edges
        workflow.add_conditional_edges("classify", self._decide_to_extract)
        workflow.add_conditional_edges("extract_info", self._should_retry_extraction)
        workflow.add_edge("validate_and_enhance", "sanitize_privacy")
        workflow.add_edge("sanitize_privacy", "display_results")
        workflow.add_edge("display_results", END)

        return workflow.compile()

    def _classify_email(self, state: GraphState) -> GraphState:
        """Intelligent email classification based on keywords"""
        safe_print("--- Step 1: Intelligent Email Classification ---")
        email_data = state["email"]

        sanitized_body = strip_headers_and_forwarded_markers(email_data.get("body", ""))
        full_text = (
            email_data.get("sender", "").lower()
            + " "
            + email_data.get("subject", "").lower()
            + " "
            + sanitized_body.lower()
        )

        # Calculate keyword scores
        placement_score = sum(
            1 for keyword in PLACEMENT_KEYWORDS if keyword in full_text
        )
        company_score = sum(1 for keyword in COMPANY_INDICATORS if keyword in full_text)
        negative_score = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in full_text)

        # Check for patterns
        has_student_names = bool(
            re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", email_data.get("body", ""))
        )
        has_numbers = bool(re.search(r"\d+", email_data.get("body", "")))
        has_email_format = bool(
            re.search(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                email_data.get("body", ""),
            )
        )

        # Security indicators
        security_indicators = [
            "security alert",
            "suspicious activity",
            "login attempt",
            "password",
            "verify",
            "account",
        ]
        has_security_indicators = any(
            indicator in full_text for indicator in security_indicators
        )

        # Calculate confidence score
        confidence = 0.0
        reasons = []

        if placement_score > 0:
            confidence += min(placement_score * 0.3, 0.6)
            reasons.append(f"Contains {placement_score} placement-related keywords")

        if company_score > 0:
            confidence += min(company_score * 0.1, 0.2)
            reasons.append(f"Contains {company_score} company indicators")

        if has_student_names:
            confidence += 0.2
            reasons.append("Contains potential student names")

        if has_numbers:
            confidence += 0.1
            reasons.append("Contains numerical data")

        if has_email_format:
            confidence += 0.1
            reasons.append("Contains email addresses")

        if negative_score > 0:
            confidence -= negative_score * 0.2
            reasons.append(f"Contains {negative_score} spam indicators")

        if has_security_indicators:
            confidence -= 0.4
            reasons.append("Contains security/alert indicators")

        is_relevant = confidence >= 0.6
        classification_reason = (
            "; ".join(reasons) if reasons else "No clear indicators found"
        )

        safe_print(f"Confidence Score: {confidence:.2f}")
        safe_print(f"Classification: {'RELEVANT' if is_relevant else 'NOT RELEVANT'}")

        return {
            **state,
            "is_relevant": is_relevant,
            "confidence_score": confidence,
            "classification_reason": classification_reason,
            "retry_count": 0,
        }

    def _extract_info(self, state: GraphState) -> GraphState:
        """LLM-based information extraction with retry logic"""
        safe_print("\n--- Step 2: Robust Information Extraction ---")
        email_data = state["email"]
        retry_count = state.get("retry_count", 0) or 0
        max_retries = 3

        chain = EXTRACTION_PROMPT | self.llm

        try:
            response = chain.invoke(
                {
                    "subject": email_data["subject"],
                    "body": strip_headers_and_forwarded_markers(email_data["body"]),
                }
            )

            json_content = extract_json_from_response(str(response.content))
            data = json.loads(json_content)

            if not data or len(data) == 0:
                safe_print(
                    "LLM returned an empty response; treating as non-placement offer."
                )
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": None,
                    "rejection_reason": "LLM returned empty response",
                }

            if data.get("is_final_placement_offer") is False:
                rejection_reason = data.get(
                    "rejection_reason",
                    "LLM indicated this is not a final placement offer.",
                )
                safe_print("LLM determined this email is not a final placement offer.")
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": None,
                    "rejection_reason": rejection_reason,
                }

            offer = PlacementOffer(**data)
            offer.email_subject = email_data["subject"]
            # For forwarded emails, extract the original sender from the body
            forwarded_sender = extract_forwarded_sender(email_data.get("body", ""))
            offer.email_sender = forwarded_sender or email_data.get("sender")
            # Use time_sent from email_data (extracted by GoogleGroupsClient) or re-extract
            offer.time_sent = email_data.get("time_sent") or extract_forwarded_date(
                email_data.get("body", "")
            )

            safe_print("Information extracted and validated successfully.")
            return {
                **state,
                "extracted_offer": offer,
                "validation_errors": None,
                "rejection_reason": None,
            }

        except ValidationError as e:
            error_messages = [str(err) for err in e.errors()]
            safe_print(f"Validation Error: {error_messages}")

            if retry_count < max_retries:
                safe_print(
                    f"Retrying extraction (attempt {retry_count + 1}/{max_retries})"
                )
                return {
                    **state,
                    "validation_errors": error_messages,
                    "retry_count": retry_count + 1,
                }
            else:
                safe_print("Max retries reached. Extraction failed.")
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": error_messages,
                }

        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing failed: {str(e)}"
            safe_print(error_msg)

            if retry_count < max_retries:
                safe_print(
                    f"Retrying extraction (attempt {retry_count + 1}/{max_retries})"
                )
                return {
                    **state,
                    "validation_errors": [error_msg],
                    "retry_count": retry_count + 1,
                    "rejection_reason": state.get("rejection_reason"),
                }
            else:
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": [error_msg],
                    "rejection_reason": state.get("rejection_reason"),
                }

    def _validate_and_enhance(self, state: GraphState) -> GraphState:
        """Validate and enhance extracted offer"""
        safe_print("\n--- Step 3: Validation and Enhancement ---")
        offer = state.get("extracted_offer")

        if not offer:
            safe_print("No offer to validate - skipping validation step.")
            return {**state, "validation_errors": None}

        validation_issues = []

        if not offer.company or len(offer.company.strip()) < 2:
            validation_issues.append("Company name is too short or missing")

        if not offer.students_selected or len(offer.students_selected) == 0:
            validation_issues.append("No students listed in the offer")

        if offer.number_of_offers != len(offer.students_selected):
            safe_print(
                f"Adjusting number_of_offers from {offer.number_of_offers} to {len(offer.students_selected)}"
            )
            offer.number_of_offers = len(offer.students_selected)

        if not offer.roles or len(offer.roles) == 0:
            validation_issues.append("No role information found")
        else:
            if len(offer.roles) == 1:
                default_role = offer.roles[0].role
                default_package = offer.roles[0].package

                for student in offer.students_selected:
                    if not student.role:
                        student.role = default_role
                        safe_print(
                            f"Assigned role '{default_role}' to student {student.name}"
                        )

                    if not student.package and default_package:
                        student.package = default_package
                        safe_print(
                            f"Assigned package {default_package} LPA to student {student.name}"
                        )

        if validation_issues:
            safe_print(f"Validation issues found: {validation_issues}")
            return {**state, "validation_errors": validation_issues}

        safe_print("Validation passed successfully.")
        return {**state, "validation_errors": None}

    def _sanitize_privacy(self, state: GraphState) -> GraphState:
        """Sanitize extracted offer for privacy"""
        offer = state.get("extracted_offer")
        if not offer:
            return state

        changed = False

        if offer.additional_info:
            cleaned = strip_headers_and_forwarded_markers(offer.additional_info)
            if cleaned != offer.additional_info:
                offer.additional_info = cleaned
                changed = True

        if offer.roles:
            for rp in offer.roles:
                if rp.package_details:
                    cleaned = strip_headers_and_forwarded_markers(rp.package_details)
                    if cleaned != rp.package_details:
                        rp.package_details = cleaned
                        changed = True

        if offer.job_location:
            new_loc = []
            for loc in offer.job_location:
                cleaned = strip_headers_and_forwarded_markers(loc)
                new_loc.append(cleaned)
                if cleaned != loc:
                    changed = True
            offer.job_location = new_loc

        if changed:
            safe_print("Privacy sanitization applied to extracted offer.")
        return {**state, "extracted_offer": offer}

    def _display_results(self, state: GraphState) -> GraphState:
        """Display extraction results"""
        safe_print("\n--- Step 4: Enhanced Results Display ---")
        offer = state.get("extracted_offer")
        confidence = state.get("confidence_score", 0.0) or 0.0
        rejection_reason = state.get("rejection_reason")

        safe_print("=" * 60)
        safe_print("    PLACEMENT EXTRACTION RESULTS")
        safe_print("=" * 60)
        safe_print(f"Classification Confidence: {confidence:.2f}")

        if rejection_reason:
            safe_print(f"Rejection Reason: {rejection_reason}")

        if not offer:
            safe_print("No valid placement information could be extracted.")
        else:
            safe_print(f"Successfully extracted: {offer.company}")
            safe_print(f"Students: {offer.number_of_offers}")
            safe_print(f"Roles: {len(offer.roles)}")

        safe_print("=" * 60 + "\n")
        return state

    def _decide_to_extract(self, state: GraphState) -> str:
        """Conditional edge: decide whether to proceed with extraction"""
        is_relevant = state.get("is_relevant", False)
        confidence = state.get("confidence_score", 0.0) or 0.0

        if is_relevant and confidence >= 0.6:
            return "extract_info"
        else:
            safe_print(
                f"Skipping extraction - Relevant: {is_relevant}, Confidence: {confidence:.2f}"
            )
            return "display_results"

    def _should_retry_extraction(self, state: GraphState) -> str:
        """Conditional edge: determine if extraction should be retried"""
        validation_errors = state.get("validation_errors", [])
        retry_count = state.get("retry_count", 0) or 0
        max_retries = 3
        extracted_offer = state.get("extracted_offer")

        if (
            not validation_errors
            or extracted_offer is not None
            or retry_count >= max_retries
            or validation_errors is None
        ):
            return "validate_and_enhance"

        return "extract_info"

    # =========================================================================
    # Email Fetching
    # =========================================================================

    def fetch_unread_emails(self) -> List[Dict[str, str]]:
        """
        Fetch unread emails from IMAP.

        Uses GoogleGroupsClient if available, otherwise falls back to legacy implementation.
        """
        # Use injected client if available
        if self.email_client:
            emails = self.email_client.fetch_unread_emails()
            # Convert to expected format (remove extra fields)
            return [
                {
                    "subject": e.get("subject", ""),
                    "sender": e.get("sender", ""),
                    "body": e.get("body", ""),
                }
                for e in emails
            ]

        # Legacy implementation (deprecated)
        if not self.email_address or not self.app_password:
            raise ValueError(
                "Email credentials not properly configured. Please check your environment variables."
            )

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.email_address, self.app_password)
            mail.select("inbox")

            status, messages = mail.search(None, "UNSEEN")
            email_ids = messages[0].split()

            emails = []
            for e_id in email_ids:
                res, msg_data = mail.fetch(e_id, "(RFC822)")
                if msg_data and msg_data[0] and len(msg_data[0]) > 1:
                    raw_msg = msg_data[0][1]
                    if isinstance(raw_msg, bytes):
                        msg = email.message_from_bytes(raw_msg)

                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8")

                        sender = msg.get("From")

                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() in [
                                    "text/plain",
                                    "text/html",
                                ]:
                                    try:
                                        payload = part.get_payload(decode=True)
                                        if isinstance(payload, bytes):
                                            body = payload.decode(
                                                "utf-8", errors="ignore"
                                            )
                                    except:
                                        continue
                        else:
                            payload = msg.get_payload(decode=True)
                            if isinstance(payload, bytes):
                                body = payload.decode("utf-8", errors="ignore")

                        emails.append(
                            {
                                "subject": subject,
                                "sender": sender,
                                "body": body,
                            }
                        )

                        # Mark email as read
                        mail.store(e_id, "+FLAGS", "\\Seen")

            mail.logout()
            return emails

        except imaplib.IMAP4.error as e:
            raise ConnectionError(f"IMAP connection failed: {e}")
        except Exception as e:
            raise Exception(f"Failed to fetch emails: {e}")

    # =========================================================================
    # JSON File Operations
    # =========================================================================

    def save_to_json(self, data: List[Dict], filename: Optional[str] = None) -> None:
        """Append placement offers to JSON file with deduplication"""
        if filename is None:
            filename = self.output_file

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        existing = []
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = []
            except (json.JSONDecodeError, IOError) as e:
                safe_print(f"Warning: Could not read existing file {filename}: {e}")
                backup_file = (
                    f"{filename}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                try:
                    os.rename(filename, backup_file)
                    safe_print(f"Corrupted file backed up to: {backup_file}")
                except:
                    pass
                existing = []

        existing_keys = set()
        for item in existing:
            if isinstance(item, dict):
                key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
                existing_keys.add(key)

        new_items_added = 0
        for item in data:
            if isinstance(item, dict):
                key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
                if key not in existing_keys:
                    existing.append(item)
                    existing_keys.add(key)
                    new_items_added += 1
                else:
                    safe_print(
                        f"Skipping duplicate offer: {item.get('email_subject', 'Unknown')}"
                    )

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            safe_print(f"Successfully saved {new_items_added} new offers to {filename}")
            safe_print(f"Total offers in file: {len(existing)}")
        except IOError as e:
            safe_print(f"Error saving to file {filename}: {e}")
            raise

    # =========================================================================
    # Main Processing
    # =========================================================================

    def process_email(self, email_data: Dict[str, str]) -> Optional[PlacementOffer]:
        """Process a single email through the LangGraph pipeline"""
        state: GraphState = {
            "email": email_data,
            "is_relevant": None,
            "confidence_score": None,
            "classification_reason": None,
            "rejection_reason": None,
            "extracted_offer": None,
            "validation_errors": None,
            "retry_count": None,
        }

        result = self.app.invoke(state)
        return result.get("extracted_offer")

    def update_placement_records(self) -> Dict[str, Any]:
        """
        Main method: Fetch emails, process, and save to database.
        Creates placement notices for new and updated offers.

        Refactored to process emails one by one to ensure data safety.
        """
        emails_fetched = 0
        offers_extracted = 0
        notices_created = 0

        # 1. Use new GoogleGroupsClient path (Sequential Processing)
        if self.email_client:
            safe_print("Fetching unread email IDs...")
            try:
                email_ids = self.email_client.get_unread_message_ids()
            except Exception as e:
                safe_print(f"Error fetching email IDs: {e}")
                return {}

            safe_print(
                f"Found {len(email_ids)} unread emails. Processing sequentially..."
            )

            for e_id in email_ids:
                try:
                    # a. Fetch email (without marking read)
                    email_data = self.email_client.fetch_email(e_id, mark_as_read=False)
                    if not email_data:
                        safe_print(f"Failed to content for email {e_id}")
                        continue

                    emails_fetched += 1
                    safe_print(
                        f"\nProcessing email: {email_data.get('subject', 'Unknown')}"
                    )

                    # b. Process email
                    offer = self.process_email(email_data)

                    # c. Save if valid
                    if offer:
                        offers_extracted += 1
                        offer_data = offer.model_dump()

                        save_success = False
                        events = []

                        # Save to DB
                        if self.db_service:
                            try:
                                # Save single offer (passed as list)
                                result = self.db_service.save_placement_offers(
                                    [offer_data]
                                )
                                safe_print(f"Database save result: {result}")
                                events = result.get("events", [])
                                save_success = True
                            except Exception as e:
                                safe_print(f"Error saving to DB: {e}")
                                # Try backup to JSON
                                self.save_to_json([offer_data])
                        else:
                            # JSON only mode
                            self.save_to_json([offer_data])
                            save_success = True

                        # Create Notices
                        if save_success and events and self.notification_formatter:
                            safe_print(f"Creating notices for {len(events)} events...")
                            new_notices = self.notification_formatter.process_events(
                                events, save_to_db=True
                            )
                            notices_created += len(new_notices)

                        # d. Mark as read (only if processing & saving succeeded)
                        if save_success:
                            self.email_client.mark_as_read(e_id)
                    else:
                        # No offer found (irrelevant/spam) - Mark as read so we don't re-process
                        safe_print("No valid offer extracted. Marking as read.")
                        self.email_client.mark_as_read(e_id)

                except Exception as e:
                    safe_print(f"Error processing email {e_id}: {e}")
                    # Do NOT mark as read, so it retries next time

        # 2. Legacy Path (Bulk Processing - Fallback)
        else:
            safe_print("Using legacy bulk processing (no email_client configured)...")
            unread_emails = (
                self.fetch_unread_emails()
            )  # This marks as read immediately in legacy implementation
            emails_fetched = len(unread_emails)

            extracted_offers = []
            for email_data in unread_emails:
                safe_print(
                    f"\nProcessing email: {email_data.get('subject', 'Unknown')}"
                )
                offer = self.process_email(email_data)
                if offer:
                    extracted_offers.append(offer.model_dump())
                    offers_extracted += 1

            # Save Batch
            if extracted_offers:
                events = []
                if self.db_service:
                    try:
                        result = self.db_service.save_placement_offers(extracted_offers)
                        events = result.get("events", [])
                    except Exception as e:
                        safe_print(f"Error saving offers: {e}")
                        self.save_to_json(extracted_offers)
                else:
                    self.save_to_json(extracted_offers)

                # Notifications
                if events and self.notification_formatter:
                    new_notices = self.notification_formatter.process_events(
                        events, save_to_db=True
                    )
                    notices_created = len(new_notices)

        # Summary
        safe_print("\nSummary:")
        safe_print(f"   • Emails fetched: {len(unread_emails)}")
        safe_print(f"   • Valid offers extracted: {len(extracted_offers)}")
        safe_print(f"   • Notices created: {notices_created}")
        success_rate = (
            f"{(len(extracted_offers) / len(unread_emails) * 100):.1f}%"
            if unread_emails
            else "0%"
        )
        safe_print(f"   • Success rate: {success_rate}")

        return {
            "emails_fetched": len(unread_emails),
            "offers_extracted": len(extracted_offers),
            "notices_created": notices_created,
            "offers": extracted_offers,
        }


# ============================================================================
# Standalone Execution
# ============================================================================


if __name__ == "__main__":
    from services.database_service import DatabaseService

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    db = DatabaseService()
    service = PlacementService(db_service=db)
    service.update_placement_records()
    db.close_connection()
