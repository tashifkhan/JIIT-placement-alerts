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

# --- Environment Variable Setup ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PLCAMENT_EMAIL = os.getenv("PLCAMENT_EMAIL")
PLCAMENT_APP_PASSWORD = os.getenv("PLCAMENT_APP_PASSWORD")

OUTPUT_FILE = "./data/placement_offers.json"


# ---------------- Pydantic Schema for Data Validation ----------------
class Student(BaseModel):
    name: str
    enrollment_number: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


class RolePackage(BaseModel):
    role: str
    packages: List[str]
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


# ---------------- LangChain LLM Setup ----------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-lite",
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)

prompt = ChatPromptTemplate.from_template(
    """
    You are an expert assistant specializing in extracting structured data from placement offer emails.
    Analyze the email content and extract the information in a JSON format that strictly matches the schema below.

    Schema:
    {{
      "company": "string",
      "roles": [
        {{
          "role": "string",
          "packages": ["array of package amounts/details as strings"],
          "package_details": "string containing detailed breakdown (optional)"
        }}
      ],
      "job_location": ["list of strings"] (optional),
      "joining_date": "string in YYYY-MM-DD format (optional)",
      "students_selected": [
        {{
          "name": "string",
          "enrollment_number": "string (optional)",
          "email": "string (optional)",
          "role": "string (optional)"
        }}
      ],
      "number_of_offers": "integer (count of students_selected)",
      "additional_info": "string containing any other relevant details (optional)"
    }}

    Return only the raw JSON object, without any surrounding text, explanations, or markdown.

    Email Content to analyze:
    Subject: {subject}
    From: {sender}
    Body: {body}
    """
)


# ---------------- LangGraph Workflow State and Nodes ----------------
class GraphState(TypedDict):
    email: Dict[str, str]
    is_relevant: Optional[bool]
    confidence_score: Optional[float]
    classification_reason: Optional[str]
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
    full_text = (
        email_data.get("sender", "").lower()
        + " "
        + email_data.get("subject", "").lower()
        + " "
        + email_data.get("body", "").lower()
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
            You are analyzing a HIGH-CONFIDENCE placement offer email. Extract ALL details meticulously.
            
            Email Content:
            Subject: {subject}
            From: {sender}
            Body: {body}
            
            Extract information in this exact JSON format:
            {{
              "company": "string",
              "roles": [
                {{
                  "role": "string",
                  "packages": ["array of package amounts/details as strings"],
                  "package_details": "string containing detailed breakdown (optional)"
                }}
              ],
              "job_location": ["list of strings"] (optional),
              "joining_date": "string in YYYY-MM-DD format (optional)",
              "students_selected": [
                {{
                  "name": "string",
                  "enrollment_number": "string (optional)",
                  "email": "string (optional)",
                  "role": "string (optional)"
                }}
              ],
              "number_of_offers": "integer (count of students_selected)",
              "additional_info": "string containing any other relevant details (optional)"
            }}
            
            Return ONLY the JSON object, no other text.
            """
        )
    else:
        extraction_prompt = ChatPromptTemplate.from_template(
            """
            You are analyzing a potential placement email. Be conservative but thorough.
            If this doesn't appear to be a genuine placement offer, return an empty JSON object: {{}}.
            
            Email Content:
            Subject: {subject}
            From: {sender}
            Body: {body}
            
            If this IS a placement offer, extract information in this JSON format:
            {{
              "company": "string",
              "roles": [
                {{
                  "role": "string",
                  "packages": ["array of package amounts/details as strings"],
                  "package_details": "string containing detailed breakdown (optional)"
                }}
              ],
              "job_location": ["list of strings"] (optional),
              "joining_date": "string in YYYY-MM-DD format (optional)",
              "students_selected": [
                {{
                  "name": "string",
                  "enrollment_number": "string (optional)",
                  "email": "string (optional)",
                  "role": "string (optional)"
                }}
              ],
              "number_of_offers": "integer (count of students_selected)",
              "additional_info": "string containing any other relevant details (optional)"
            }}
            
            Return ONLY the JSON object, no other text.
            """
        )

    chain = extraction_prompt | llm

    try:
        response = chain.invoke(
            {
                "subject": email_data["subject"],
                "sender": email_data["sender"],
                "body": email_data["body"],
            }
        )

        json_content = extract_json_from_response(str(response.content))
        data = json.loads(json_content)

        # Check if empty response (for low-confidence emails)
        if not data or len(data) == 0:
            print("⚠️ LLM determined this is not a placement offer.")
            return {**state, "extracted_offer": None, "validation_errors": None}

        offer = PlacementOffer(**data)
        offer.email_subject = email_data["subject"]
        offer.email_sender = email_data["sender"]

        print("✅ Information extracted and validated successfully.")
        return {**state, "extracted_offer": offer, "validation_errors": None}

    except ValidationError as e:
        error_messages = [str(err) for err in e.errors()]
        print(f"❌ Validation Error: {error_messages}")

        if retry_count < max_retries:
            print(f"🔄 Retrying extraction (attempt {retry_count + 1}/{max_retries})")
            return {
                **state,
                "validation_errors": error_messages,
                "retry_count": retry_count + 1,
            }
        else:
            print(f"❌ Max retries reached. Extraction failed.")
            return {
                **state,
                "extracted_offer": None,
                "validation_errors": error_messages,
            }

    except json.JSONDecodeError as e:
        error_msg = f"JSON parsing failed: {str(e)}"
        print(f"❌ {error_msg}")

        if retry_count < max_retries:
            print(f"🔄 Retrying extraction (attempt {retry_count + 1}/{max_retries})")
            return {
                **state,
                "validation_errors": [error_msg],
                "retry_count": retry_count + 1,
            }
        else:
            return {**state, "extracted_offer": None, "validation_errors": [error_msg]}


def validate_and_enhance(state: GraphState) -> GraphState:
    print("\n--- Step 3: Validation and Enhancement ---")
    offer = state.get("extracted_offer")

    if not offer:
        print("⚠️ No offer to validate - skipping validation step.")
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
            f"⚠️ Adjusting number_of_offers from {offer.number_of_offers} to {len(offer.students_selected)}"
        )
        offer.number_of_offers = len(offer.students_selected)

    # Check for role information
    if not offer.roles or len(offer.roles) == 0:
        validation_issues.append("No role information found")

    if validation_issues:
        print(f"⚠️ Validation issues found: {validation_issues}")
        return {**state, "validation_errors": validation_issues}

    print("✅ Validation passed successfully.")
    return {**state, "validation_errors": None}


def enhanced_display_results(state: GraphState) -> GraphState:
    print("\n--- Step 4: Enhanced Results Display ---")
    offer = state.get("extracted_offer")
    confidence = state.get("confidence_score", 0.0) or 0.0
    classification_reason = state.get("classification_reason", "")
    validation_errors = state.get("validation_errors", [])

    print("\n" + "=" * 60)
    print("    PLACEMENT EXTRACTION RESULTS")
    print("=" * 60)

    print(f"📊 Classification Confidence: {confidence:.2f}")
    print(f"🔍 Classification Reason: {classification_reason}")

    if validation_errors:
        print(f"⚠️  Validation Issues: {'; '.join(validation_errors)}")

    if not offer:
        print("❌ No valid placement information could be extracted.")
    else:
        print("✅ Successfully extracted placement offer:")
        offer_dict = offer.model_dump()
        for key, value in offer_dict.items():
            if value is not None:
                formatted_key = key.replace("_", " ").title()
                if isinstance(value, list) and len(value) > 0:
                    print(f"- {formatted_key+':':<25} {json.dumps(value, indent=2)}")
                elif not isinstance(value, list):
                    print(f"- {formatted_key+':':<25} {value}")

    print("=" * 60 + "\n")
    return state


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
            f"⏭️ Skipping extraction - Relevant: {is_relevant}, Confidence: {confidence:.2f}"
        )
        return "display_results"


# Build the enhanced workflow
workflow = StateGraph(GraphState)

# Add all nodes
workflow.add_node("classify", intelligent_classify_email)
workflow.add_node("extract_info", robust_extract_info)
workflow.add_node("validate_and_enhance", validate_and_enhance)
workflow.add_node("display_results", enhanced_display_results)

# Set entry point
workflow.set_entry_point("classify")

# Add conditional edges
workflow.add_conditional_edges("classify", decide_to_extract)
workflow.add_conditional_edges("extract_info", should_retry_extraction)
workflow.add_edge("validate_and_enhance", "display_results")
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


def save_to_json(data, filename=OUTPUT_FILE):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            existing = json.load(f)
    else:
        existing = []

    existing.extend(data)

    with open(filename, "w") as f:
        json.dump(existing, f, indent=2)


# ---------------- Run Enhanced Pipeline ----------------
if __name__ == "__main__":
    print("📩 Fetching unread emails...")
    unread_emails = fetch_unread_emails()

    extracted_offers = []
    for email_data in unread_emails:
        print(f"\n🚀 Processing email: {email_data['subject']}")

        # Initialize complete GraphState with all required fields
        state: GraphState = {
            "email": email_data,
            "is_relevant": None,
            "confidence_score": None,
            "classification_reason": None,
            "extracted_offer": None,
            "validation_errors": None,
            "retry_count": None,
        }

        result = app.invoke(state)

        if result.get("extracted_offer"):
            extracted_offers.append(result["extracted_offer"].model_dump())
            print(
                f"✅ Successfully processed email from {email_data.get('sender', 'Unknown')}"
            )
        else:
            print(
                f"⚠️ No valid offer extracted from email: {email_data.get('subject', 'Unknown')}"
            )

    if extracted_offers:
        save_to_json(extracted_offers)
        print(
            f"🎉 Successfully saved {len(extracted_offers)} placement offers to {OUTPUT_FILE}"
        )
        print(f"📈 Processing complete! Total emails processed: {len(unread_emails)}")
    else:
        print("⚠️ No valid placement offers were extracted from any emails.")
        print(f"📊 Total emails processed: {len(unread_emails)}")

    print("\n🔍 Summary:")
    print(f"   • Emails fetched: {len(unread_emails)}")
    print(f"   • Valid offers extracted: {len(extracted_offers)}")
    print(
        f"   • Success rate: {(len(extracted_offers)/len(unread_emails)*100):.1f}%"
        if unread_emails
        else "0%"
    )
