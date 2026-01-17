import os
import json
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from typing import List, Optional, Dict, TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from database import MongoDBManager


load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PLCAMENT_EMAIL = os.getenv("PLCAMENT_EMAIL")
PLCAMENT_APP_PASSWORD = os.getenv("PLCAMENT_APP_PASSWORD")

OUTPUT_FILE = os.path.join(
    os.getcwd(),
    "data",
    "placement_offers.json",
)


class Student(BaseModel):
    name: str
    enrollment_number: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    package: Optional[float] = None


class RolePackage(BaseModel):
    role: str
    package: Optional[float] = None
    package_details: Optional[str] = None


class PlacementOffer(BaseModel):
    company: str
    roles: List[RolePackage]
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
    students_selected: List[Student]
    number_of_offers: int
    additional_info: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)

prompt = ChatPromptTemplate.from_template(
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


class GraphState(TypedDict):
    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
    rejection_reason: Optional[str]
    extracted_offer: Optional[PlacementOffer]
    validation_errors: Optional[List[str]]
    retry_count: Optional[int]


# Enhanced classification configuration
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


def intelligent_classify_email(state: GraphState) -> GraphState:
    print("--- Step 1: Intelligent Email Classification ---")
    email_data = state["email"]

    # Combine all text for analysis
    sanitized_body_for_analysis = _strip_headers_and_forwarded_markers(
        email_data.get("body", "")
    )
    full_text = (
        email_data.get("sender", "").lower()
        + " "
        + email_data.get("subject", "").lower()
        + " "
        + sanitized_body_for_analysis.lower()
    )

    # Calculate keyword scores
    placement_score = sum(1 for keyword in PLACEMENT_KEYWORDS if keyword in full_text)
    company_score = sum(1 for keyword in COMPANY_INDICATORS if keyword in full_text)
    negative_score = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in full_text)

    # Check for specific patterns
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

    # Check for security/spam indicators that should reduce confidence
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

    # Reduce confidence for negative indicators
    if negative_score > 0:
        confidence -= negative_score * 0.2
        reasons.append(f"Contains {negative_score} spam indicators")

    # Strong penalty for security alerts
    if has_security_indicators:
        confidence -= 0.4
        reasons.append("Contains security/alert indicators")

    # Final classification - increased threshold to reduce false positives
    is_relevant = confidence >= 0.6  # Increased from 0.5
    classification_reason = (
        "; ".join(reasons) if reasons else "No clear indicators found"
    )

    print(f"Confidence Score: {confidence:.2f}")
    print(f"Classification: {'RELEVANT' if is_relevant else 'NOT RELEVANT'}")
    print(f"Reasoning: {classification_reason}")

    return {
        **state,
        "is_relevant": is_relevant,
        "confidence_score": confidence,
        "classification_reason": classification_reason,
        "retry_count": 0,
    }


def extract_json_from_response(response_content: str) -> str:
    json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, response_content)
    return match.group(1).strip() if match else response_content.strip()


def robust_extract_info(state: GraphState) -> GraphState:
    print("\n--- Step 2: Robust Information Extraction ---")
    email_data = state["email"]
    retry_count = state.get("retry_count", 0) or 0
    max_retries = 3

    # Enhanced prompt based on confidence score
    confidence = state.get("confidence_score", 0.5) or 0.5

    if confidence > 0.8:
        extraction_prompt = ChatPromptTemplate.from_template(
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
    else:
        extraction_prompt = prompt

    chain = extraction_prompt | llm

    try:
        response = chain.invoke(
            {
                "subject": email_data["subject"],
                # Pre-strip headers/forward markers from body before sending to LLM
                "body": _strip_headers_and_forwarded_markers(email_data["body"]),
            }
        )

        json_content = extract_json_from_response(str(response.content))
        data = json.loads(json_content)

        # Check if empty response (for low-confidence emails)
        if not data or len(data) == 0:
            print("LLM returned an empty response; treating as non-placement offer.")
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
            print("LLM determined this email is not a final placement offer.")
            if rejection_reason:
                print(f"Reason: {rejection_reason}")
            return {
                **state,
                "extracted_offer": None,
                "validation_errors": None,
                "rejection_reason": rejection_reason,
            }

        offer = PlacementOffer(**data)
        # Attach original email metadata for internal deduplication only.
        # Privacy rule: this metadata must never be included in user-facing fields.
        offer.email_subject = email_data["subject"]
        offer.email_sender = email_data.get("sender")

        print("Information extracted and validated successfully.")
        return {
            **state,
            "extracted_offer": offer,
            "validation_errors": None,
            "rejection_reason": None,
        }

    except ValidationError as e:
        error_messages = [str(err) for err in e.errors()]
        print(f"Validation Error: {error_messages}")

        if retry_count < max_retries:
            print(f"Retrying extraction (attempt {retry_count + 1}/{max_retries})")
            return {
                **state,
                "validation_errors": error_messages,
                "retry_count": retry_count + 1,
            }
        else:
            print(f"Max retries reached. Extraction failed.")
            return {
                **state,
                "extracted_offer": None,
                "validation_errors": error_messages,
            }

    except json.JSONDecodeError as e:
        error_msg = f"JSON parsing failed: {str(e)}"
        print(f"{error_msg}")

        if retry_count < max_retries:
            print(f"Retrying extraction (attempt {retry_count + 1}/{max_retries})")
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


def validate_and_enhance(state: GraphState) -> GraphState:
    print("\n--- Step 3: Validation and Enhancement ---")
    offer = state.get("extracted_offer")

    if not offer:
        print("No offer to validate - skipping validation step.")
        return {**state, "validation_errors": None}

    # Additional validation and enhancement logic
    validation_issues = []

    # Check if company name is meaningful
    if not offer.company or len(offer.company.strip()) < 2:
        validation_issues.append("Company name is too short or missing")

    # Check if students are listed
    if not offer.students_selected or len(offer.students_selected) == 0:
        validation_issues.append("No students listed in the offer")

    # Validate number consistency
    if offer.number_of_offers != len(offer.students_selected):
        print(
            f"Adjusting number_of_offers from {offer.number_of_offers} to {len(offer.students_selected)}"
        )
        offer.number_of_offers = len(offer.students_selected)

    # Check for role information
    if not offer.roles or len(offer.roles) == 0:
        validation_issues.append("No role information found")
    else:
        # Auto-assign roles to students if missing
        if len(offer.roles) == 1:
            default_role = offer.roles[0].role
            default_package = offer.roles[0].package

            for student in offer.students_selected:
                if not student.role:
                    student.role = default_role
                    print(f"Assigned role '{default_role}' to student {student.name}")

                # Assign package if student doesn't have one and role has one
                if not student.package and default_package:
                    student.package = default_package
                    print(
                        f"Assigned package {default_package} LPA to student {student.name}"
                    )

    if validation_issues:
        print(f"Validation issues found: {validation_issues}")
        return {**state, "validation_errors": validation_issues}

    print("Validation passed successfully.")
    return {**state, "validation_errors": None}


def enhanced_display_results(state: GraphState) -> GraphState:
    print("\n--- Step 4: Enhanced Results Display ---")
    offer = state.get("extracted_offer")
    confidence = state.get("confidence_score", 0.0) or 0.0
    classification_reason = state.get("classification_reason", "")
    rejection_reason = state.get("rejection_reason")
    validation_errors = state.get("validation_errors", [])

    print("\n" + "=" * 60)
    print("    PLACEMENT EXTRACTION RESULTS")
    print("=" * 60)

    print(f"Classification Confidence: {confidence:.2f}")
    print(f"Classification Reason: {classification_reason}")
    if rejection_reason:
        print(f"Rejection Reason: {rejection_reason}")

    if validation_errors:
        print(f"Validation Issues: {'; '.join(validation_errors)}")

    if not offer:
        print("No valid placement information could be extracted.")
    else:
        print("Successfully extracted placement offer:")
        offer_dict = offer.model_dump()
        for key, value in offer_dict.items():
            if value is not None:
                formatted_key = key.replace("_", " ").title()
                if isinstance(value, list) and len(value) > 0:
                    # Special formatting for roles and students
                    if key == "roles":
                        roles_str = ""
                        for role in value:
                            roles_str += f"\n    Role: {role.get('role', 'N/A')}\n"
                            package = role.get("package")
                            if package is not None:
                                roles_str += f"    Package: {package} LPA\n"
                            if role.get("package_details"):
                                roles_str += (
                                    f"    Details: {role.get('package_details')}\n"
                                )
                        print(f"- {formatted_key+':':<25}{roles_str}")
                    elif key == "students_selected":
                        students_str = ""
                        for student in value:
                            students_str += (
                                f"\n    Name: {student.get('name', 'N/A')}\n"
                            )
                            if student.get("enrollment_number"):
                                students_str += f"    Enrollment: {student.get('enrollment_number')}\n"
                            if student.get("role"):
                                students_str += f"    Role: {student.get('role')}\n"
                            if student.get("package"):
                                students_str += (
                                    f"    Package: {student.get('package')} LPA\n"
                                )
                            if student.get("email"):
                                students_str += f"    Email: {student.get('email')}\n"
                        print(f"- {formatted_key+':':<25}{students_str}")
                    else:
                        print(
                            f"- {formatted_key+':':<25} {json.dumps(value, indent=2)}"
                        )
                elif not isinstance(value, list):
                    print(f"- {formatted_key+':':<25} {value}")

    print("=" * 60 + "\n")
    return state


# ---------------- Privacy Sanitization ----------------
def _strip_headers_and_forwarded_markers(text: str) -> str:
    """Remove lines that look like email headers or forwarded markers and redact obvious sender mentions.

    PRIVACY RULE (GLOBAL):
    - This application must never disclose the sender of an email or whether an email was forwarded in any user-facing content.
    - The LLM prompts explicitly instruct to ignore such content, and this sanitizer enforces the rule post-extraction.

    This function removes common patterns like:
      - From:, Sender:, Sent:, To:, Cc:, Subject: (when appearing as quoted headers in body)
      - Forwarded message, Begin forwarded message, Fwd:, FW:
      - Lines like: "On <date>, <name> <email@...> wrote:"
    """
    if not text:
        return text

    # Remove entire header-like lines
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

    # Also remove inline "via" sender mentions like "via Gmail" or "via <service>"
    cleaned = re.sub(r"\bvia\s+[^\s\n]+", "", cleaned, flags=re.IGNORECASE)

    # Redact explicit phrases stating it's forwarded
    cleaned = re.sub(r"\bforward(ed)?(\s+message)?\b", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


def sanitize_offer_for_privacy(state: GraphState) -> GraphState:
    """Sanitize extracted offer fields to ensure no sender or forwarded information is present.

    - Scrubs additional_info and role package_details.
    - Does not alter internal fields used for deduplication (email_subject/email_sender).
    - Adds a note to state if sanitization occurred.
    """
    offer = state.get("extracted_offer")
    if not offer:
        return state

    changed = False

    # Sanitize additional_info
    if offer.additional_info:
        cleaned = _strip_headers_and_forwarded_markers(offer.additional_info)
        if cleaned != offer.additional_info:
            offer.additional_info = cleaned
            changed = True

    # Sanitize role package_details
    if offer.roles:
        for rp in offer.roles:
            if rp.package_details:
                cleaned = _strip_headers_and_forwarded_markers(rp.package_details)
                if cleaned != rp.package_details:
                    rp.package_details = cleaned
                    changed = True

    # Sanitize job_location strings just in case
    if offer.job_location:
        new_loc = []
        for loc in offer.job_location:
            cleaned = _strip_headers_and_forwarded_markers(loc)
            new_loc.append(cleaned)
            if cleaned != loc:
                changed = True
        offer.job_location = new_loc

    if changed:
        print("Privacy sanitization applied to extracted offer.")
    return {**state, "extracted_offer": offer}


# ---- Local quick check for privacy sanitizer (dev aid) ----
def _dev_quick_sanitize_check() -> None:
    sample_text = (
        "Begin forwarded message:\n"
        "From: John Doe <john@example.com>\n"
        "Subject: Congrats!\n\n"
        "Offer details: 10 LPA full-time. Contact via HR portal."
    )
    cleaned = _strip_headers_and_forwarded_markers(sample_text)
    assert "From:" not in cleaned and "forwarded" not in cleaned.lower()
    # print result for manual verification when called directly
    print("Sanitizer sample output:\n", cleaned)


def should_retry_extraction(state: GraphState) -> str:
    """Conditional edge to determine if extraction should be retried"""
    validation_errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0) or 0
    max_retries = 3
    extracted_offer = state.get("extracted_offer")

    # Don't retry if:
    # 1. No validation errors (successful extraction)
    # 2. Extraction was successful (offer exists)
    # 3. Max retries reached
    # 4. LLM determined it's not a placement offer (validation_errors is None)
    if (
        not validation_errors
        or extracted_offer is not None
        or retry_count >= max_retries
        or validation_errors is None
    ):
        return "validate_and_enhance"

    # Only retry if there are actual validation errors and retries remaining
    return "extract_info"


def decide_to_extract(state: GraphState) -> str:
    """Conditional edge to decide whether to proceed with extraction"""
    is_relevant = state.get("is_relevant", False)
    confidence = state.get("confidence_score", 0.0) or 0.0

    # Only proceed if classified as relevant with sufficient confidence
    # Use a higher threshold to reduce false positives
    if is_relevant and confidence >= 0.6:
        return "extract_info"
    else:
        print(
            f"Skipping extraction - Relevant: {is_relevant}, Confidence: {confidence:.2f}"
        )
        return "display_results"


# Build the enhanced workflow
workflow = StateGraph(GraphState)

# Add all nodes
workflow.add_node("classify", intelligent_classify_email)
workflow.add_node("extract_info", robust_extract_info)
workflow.add_node("validate_and_enhance", validate_and_enhance)
workflow.add_node("sanitize_privacy", sanitize_offer_for_privacy)
workflow.add_node("display_results", enhanced_display_results)

# Set entry point
workflow.set_entry_point("classify")

# Add conditional edges
workflow.add_conditional_edges("classify", decide_to_extract)
workflow.add_conditional_edges("extract_info", should_retry_extraction)
workflow.add_edge("validate_and_enhance", "sanitize_privacy")
workflow.add_edge("sanitize_privacy", "display_results")
workflow.add_edge("display_results", END)

# Compile the workflow
app = workflow.compile()


# ---------------- Gmail IMAP Fetching ----------------
def fetch_unread_emails():
    if not PLCAMENT_EMAIL or not PLCAMENT_APP_PASSWORD:
        raise ValueError(
            "Email credentials not properly configured. Please check your environment variables."
        )

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(PLCAMENT_EMAIL, PLCAMENT_APP_PASSWORD)
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
                            if part.get_content_type() in ["text/plain", "text/html"]:
                                try:
                                    payload = part.get_payload(decode=True)
                                    if isinstance(payload, bytes):
                                        body = payload.decode("utf-8", errors="ignore")
                                except:
                                    continue
                    else:
                        payload = msg.get_payload(decode=True)
                        if isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")

                    emails.append({"subject": subject, "sender": sender, "body": body})

                    # Mark email as read
                    mail.store(e_id, "+FLAGS", "\\Seen")

        mail.logout()
        return emails

    except imaplib.IMAP4.error as e:
        raise ConnectionError(f"IMAP connection failed: {e}")
    except Exception as e:
        raise Exception(f"Failed to fetch emails: {e}")


def save_to_json(data, filename=None):
    """
    Append placement offers to JSON file with proper error handling and deduplication
    """
    if filename is None:
        filename = OUTPUT_FILE

    # Ensure the directory exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    # Load existing data
    existing = []
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not read existing file {filename}: {e}")
            # Create backup of corrupted file
            backup_file = (
                f"{filename}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            try:
                os.rename(filename, backup_file)
                print(f"Corrupted file backed up to: {backup_file}")
            except:
                pass
            existing = []

    # Simple deduplication based on email subject and sender
    existing_keys = set()
    for item in existing:
        if isinstance(item, dict):
            key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
            existing_keys.add(key)

    # Add new data, avoiding duplicates
    new_items_added = 0
    for item in data:
        if isinstance(item, dict):
            key = f"{item.get('email_subject', '')}__{item.get('email_sender', '')}"
            if key not in existing_keys:
                existing.append(item)
                existing_keys.add(key)
                new_items_added += 1
            else:
                print(
                    f"Skipping duplicate offer: {item.get('email_subject', 'Unknown')}"
                )

    # Save updated data
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved {new_items_added} new offers to {filename}")
        print(f"Total offers in file: {len(existing)}")
    except IOError as e:
        print(f"Error saving to file {filename}: {e}")
        raise


def update_placement_records() -> None:
    print("Fetching unread emails...")
    unread_emails = fetch_unread_emails()

    extracted_offers = []
    for email_data in unread_emails:
        print(f"\nProcessing email: {email_data['subject']}")

        # Initialize complete GraphState with all required fields
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

        result = app.invoke(state)

        if result.get("extracted_offer"):
            extracted_offers.append(result["extracted_offer"].model_dump())
            print("Successfully processed one email into an offer.")
        else:
            print(
                f"No valid offer extracted from email: {email_data.get('subject', 'Unknown')}"
            )

    # Initialize DB manager (fallback to JSON file if DB unavailable)
    db_manager = None
    try:
        db_manager = MongoDBManager()
    except Exception as e:
        print(
            f"Warning: Could not initialize MongoDBManager, falling back to JSON file. Error: {e}"
        )

    if extracted_offers:
        print(f"\nSaving {len(extracted_offers)} new offers...")
        if db_manager:
            try:
                result = db_manager.save_placement_offers(extracted_offers)
                print(f"Database save result: {result}")
            except Exception as e:
                print(f"Error saving offers to DB: {e}\nFalling back to JSON file.")
                save_to_json(extracted_offers)
        else:
            # fallback
            print(f"Output file: {OUTPUT_FILE}")
            save_to_json(extracted_offers)

        print(f"Processing complete! Total emails processed: {len(unread_emails)}")
    else:
        print("No valid placement offers were extracted from any emails.")
        print(f"Total emails processed: {len(unread_emails)}")

    print("\nSummary:")
    print(f"   • Emails fetched: {len(unread_emails)}")
    print(f"   • Valid offers extracted: {len(extracted_offers)}")
    print(f"   • Output file: {OUTPUT_FILE}")
    print(
        f"   • Success rate: {(len(extracted_offers)/len(unread_emails)*100):.1f}%"
        if unread_emails
        else "0%"
    )


# ---------------- Run Enhanced Pipeline ----------------
if __name__ == "__main__":
    update_placement_records()
