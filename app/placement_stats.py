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
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

OUTPUT_FILE = "placement_offers.json"


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
    extracted_offer: Optional[PlacementOffer]


ALLOWED_KEYWORDS = ["tnp", "placement", "offer", "congratulations"]


def classify_email(state: GraphState) -> GraphState:
    print("--- Step 1: Classifying Email ---")
    email_data = state["email"]
    search_text = (
        email_data["sender"].lower()
        + email_data["subject"].lower()
        + email_data["body"].lower()
    )

    if any(keyword in search_text for keyword in ALLOWED_KEYWORDS):
        print("✅ Email classified as RELEVANT.")
        return {**state, "is_relevant": True}

    print("❌ Email classified as NOT RELEVANT. Halting workflow.")
    return {**state, "is_relevant": False}


def extract_json_from_response(response_content: str) -> str:
    json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, response_content)
    return match.group(1).strip() if match else response_content.strip()


def extract_info(state: GraphState) -> GraphState:
    print("\n--- Step 2: Extracting and Validating Information ---")
    email_data = state["email"]
    chain = prompt | llm

    response = chain.invoke(
        {
            "subject": email_data["subject"],
            "sender": email_data["sender"],
            "body": email_data["body"],
        }
    )

    try:
        json_content = extract_json_from_response(str(response.content))
        data = json.loads(json_content)
        offer = PlacementOffer(**data)
        offer.email_subject = email_data["subject"]
        offer.email_sender = email_data["sender"]
        print("✅ Information extracted and validated successfully.")
        return {**state, "extracted_offer": offer}
    except ValidationError as e:
        print(f"❌ Validation Error:\n{e}")
        return {**state, "extracted_offer": None}
    except json.JSONDecodeError as e:
        print(f"❌ JSON Error: {e}\nResponse: {response.content}")
        return {**state, "extracted_offer": None}


def display_results(state: GraphState) -> None:
    print("\n--- Step 3: Displaying Results ---")
    offer = state.get("extracted_offer")

    print("\n" + "=" * 50)
    print("    Final Extracted Placement Details")
    print("=" * 50)

    if not offer:
        print("No valid placement information could be extracted.")
    else:
        offer_dict = offer.dict()
        for key, value in offer_dict.items():
            if value is not None:
                formatted_key = key.replace("_", " ").title()
                print(f"- {formatted_key+':':<20} {json.dumps(value, indent=2)}")

    print("=" * 50 + "\n")


def decide_to_extract(state: GraphState) -> str:
    return "extract_info" if state.get("is_relevant") else END


workflow = StateGraph(GraphState)
workflow.add_node("classify", classify_email)
workflow.add_node("extract_info", extract_info)
workflow.add_node("display_results", display_results)
workflow.set_entry_point("classify")
workflow.add_conditional_edges("classify", decide_to_extract)
workflow.add_edge("extract_info", "display_results")
workflow.add_edge("display_results", END)
app = workflow.compile()


# ---------------- Gmail IMAP Fetching ----------------
def fetch_unread_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    status, messages = mail.search(None, "UNSEEN")
    email_ids = messages[0].split()

    emails = []
    for e_id in email_ids:
        res, msg_data = mail.fetch(e_id, "(RFC822)")
        raw_msg = msg_data[0][1]
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
                        body = part.get_payload(decode=True).decode(
                            "utf-8", errors="ignore"
                        )
                    except:
                        continue
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

        emails.append({"subject": subject, "sender": sender, "body": body})

        # Mark email as read
        mail.store(e_id, "+FLAGS", "\\Seen")

    mail.logout()
    return emails


def save_to_json(data, filename=OUTPUT_FILE):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            existing = json.load(f)
    else:
        existing = []

    existing.extend(data)

    with open(filename, "w") as f:
        json.dump(existing, f, indent=2)


# ---------------- Run Pipeline ----------------
if __name__ == "__main__":
    print("📩 Fetching unread emails...")
    unread_emails = fetch_unread_emails()

    extracted_offers = []
    for email_data in unread_emails:
        print(f"\n🚀 Processing email: {email_data['subject']}")
        state = {"email": email_data}
        result = app.invoke(state)  # run through pipeline
        if result.get("extracted_offer"):
            extracted_offers.append(result["extracted_offer"].dict())

    if extracted_offers:
        save_to_json(extracted_offers)
        print(f"✅ Saved {len(extracted_offers)} offers to {OUTPUT_FILE}")
    else:
        print("⚠️ No valid offers extracted.")
