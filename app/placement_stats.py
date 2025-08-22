import os
import json
import re
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

# ---------------- Pydantic Schema for Data Validation ----------------


class Student(BaseModel):
    name: str
    enrollment_number: Optional[str] = None
    email: Optional[str] = None


class PackageBreakdown(BaseModel):
    base: Optional[str] = None
    bonus: Optional[str] = None
    rsu: Optional[str] = None  # Restricted Stock Units
    other_components: Optional[Dict[str, str]] = None


class PlacementOffer(BaseModel):
    company: str
    role: Optional[str] = None
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
    total_package: Optional[str] = None
    package_breakdown: Optional[PackageBreakdown] = None
    students_selected: List[Student]
    number_of_offers: int
    additional_info: Optional[str] = None
    email_subject: Optional[str] = None  # This will be added after extraction
    email_sender: Optional[str] = None  # This will be added after extraction


# ---------------- LangChain LLM Setup ----------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-lite",
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)

# The prompt is updated to request JSON matching the detailed Pydantic schema.
prompt = ChatPromptTemplate.from_template(
    """
    You are an expert assistant specializing in extracting structured data from placement offer emails.
    Analyze the email content and extract the information in a JSON format that strictly matches the schema below.

    Schema:
    {{
      "company": "string",
      "role": "string (optional)",
      "job_location": ["list of strings"] (optional),
      "joining_date": "string in YYYY-MM-DD format (optional)",
      "total_package": "string, e.g., '25 LPA' or '1,20,000 USD per annum'",
      "package_breakdown": {{
          "base": "string (optional)",
          "bonus": "string (optional)",
          "rsu": "string (optional)",
          "other_components": {{"key": "value"}} (optional)
      }} (optional),
      "students_selected": [
        {{
          "name": "string",
          "enrollment_number": "string (optional)",
          "email": "string (optional)"
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
    is_relevant: bool
    extracted_offer: Optional[PlacementOffer]


# Keywords to identify relevant emails
ALLOWED_KEYWORDS = ["tnp", "placement", "offer", "congratulations"]


def classify_email(state: GraphState) -> GraphState:
    """Node 1: Classifies if the email is a relevant placement offer."""
    print("--- Step 1: Classifying Email ---")
    email = state["email"]
    # Combine all text sources for a comprehensive keyword search
    search_text = (
        email["sender"].lower() + email["subject"].lower() + email["body"].lower()
    )

    if any(keyword in search_text for keyword in ALLOWED_KEYWORDS):
        print("✅ Email classified as RELEVANT.")
        return {"is_relevant": True}

    print("❌ Email classified as NOT RELEVANT. Halting workflow.")
    return {"is_relevant": False}


def extract_json_from_response(response_content: str) -> str:
    """Extract JSON from response content, handling markdown code blocks."""
    # Remove markdown code blocks if present
    json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, response_content)

    if match:
        return match.group(1).strip()

    # If no code blocks found, return the original content
    return response_content.strip()


def extract_info(state: GraphState) -> GraphState:
    """Node 2: Extracts information and validates it against the Pydantic schema."""
    print("\n--- Step 2: Extracting and Validating Information ---")
    email = state["email"]
    chain = prompt | llm

    response = chain.invoke(
        {"subject": email["subject"], "sender": email["sender"], "body": email["body"]}
    )

    try:
        # Extract JSON from response, handling markdown code blocks
        json_content = extract_json_from_response(response.content)
        data = json.loads(json_content)

        # Validate the extracted data by creating a PlacementOffer instance
        offer = PlacementOffer(**data)
        # Add metadata from the original email
        offer.email_subject = email["subject"]
        offer.email_sender = email["sender"]
        print("✅ Information extracted and validated successfully.")
        return {"extracted_offer": offer}
    except ValidationError as e:
        print(
            f"❌ Pydantic Validation Error: The LLM output did not match the required schema.\n{e}"
        )
        return {"extracted_offer": None}
    except json.JSONDecodeError as e:
        print(
            f"❌ JSON Parsing Error: The LLM output was not valid JSON.\nError: {e}\nResponse: {response.content}"
        )
        return {"extracted_offer": None}


def display_results(state: GraphState) -> None:
    """Node 3: Displays the final, validated placement offer details."""
    print("\n--- Step 3: Displaying Results ---")
    offer = state.get("extracted_offer")

    print("\n" + "=" * 50)
    print("    Final Extracted Placement Details")
    print("=" * 50)

    if not offer:
        print("No valid placement information could be extracted.")
    else:
        # Pydantic's .dict() method is useful for clean printing
        offer_dict = offer.dict()
        for key, value in offer_dict.items():
            if value is not None:
                formatted_key = key.replace("_", " ").title()
                print(f"- {formatted_key+':':<20} {json.dumps(value, indent=2)}")

    print("=" * 50 + "\n")


# ---------------- Graph Definition ----------------


def decide_to_extract(state: GraphState) -> str:
    """Determines the next step after classification."""
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

# ---------------- Run Pipeline with Manual Text Input ----------------
if __name__ == "__main__":
    # --- PASTE YOUR EMAIL DETAILS HERE TO TEST ---
    input_email_subject = "HackWithInfy 2025 - Infosys (Batch 2026) - Offers"
    input_email_sender = "anitamarwaha.tnp@gmail.com"
    input_email_body = """
    <p class="MsoNormal" style="line-height:16.5pt;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;margin:0cm 0cm 8pt;font-size:11pt;font-family:Calibri,sans-serif"><b><span style="font-size:10pt;font-family:Arial,sans-serif">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;</span></b></p>

<p class="MsoNormal" style="line-height:16.5pt;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;margin:0cm 0cm 8pt;font-size:11pt;font-family:Calibri,sans-serif"><b><span style="font-size:10pt;font-family:Arial,sans-serif">&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<span style="background:fuchsia">
!!! <span class="il">Congratulations</span> !!!</span></span></b><span style="font-size:10pt;font-family:Arial,sans-serif"></span></p>

<p class="MsoNormal" style="margin:8.35pt 0cm;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;line-height:107%;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;line-height:107%;font-family:Arial,sans-serif">&nbsp;</span></p>

<p class="MsoNormal" style="margin:8.35pt 0cm;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;line-height:107%;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;line-height:107%;font-family:Arial,sans-serif">The
following students of the 2026 batch have been offered by Infosys through HackwithInfy.</span><span style="font-size:10pt;line-height:107%;font-family:Arial,sans-serif"></span></p><p class="MsoNormal" style="margin:8.35pt 0cm;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;line-height:107%;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;line-height:107%;font-family:Arial,sans-serif"><br></span></p>

<table border="0" cellpadding="0" cellspacing="0" width="828" style="border-collapse:collapse;width:621pt">

 <colgroup><col width="39" style="width:29pt">
 <col width="102" style="width:77pt">
 <col width="145" style="width:109pt">
 <col width="214" style="width:161pt">
 <col width="175" style="width:131pt">
 <col width="86" style="width:64pt">
 <col width="67" style="width:50pt">
 </colgroup><tbody><tr height="18" style="height:13.8pt">
  <td height="18" width="39" style="height:13.8pt;width:29pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">S.No.</td>
  <td width="102" style="border-left:none;width:77pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Enrollment No.</td>
  <td width="145" style="border-left:none;width:109pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Candidate Name</td>
  <td width="214" style="border-left:none;width:161pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Email ID</td>
  <td width="175" style="border-left:none;width:131pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Role</td>
  <td width="86" style="border-left:none;width:64pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Results</td>
  <td width="67" style="border-left:none;width:50pt;font-size:10pt;font-weight:700;font-family:Arial,sans-serif;text-align:center;border-top:0.5pt solid windowtext;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">University</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">1</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">22103267</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SAHIL SHARMA</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:sahilgsm2003@gmail.com" target="_blank">sahilgsm2003@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Specialist Programmer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JIIT</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">2</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">22102028</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Ryan Khursheed&nbsp;</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:ryan.khursheedps@gmail.com" target="_blank">ryan.khursheedps@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Specialist Programmer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JIIT</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">3</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">21803026</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">ARYESH
  SRIVASTAVA&nbsp;</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:aryeshsrivastava@gmail.com" target="_blank">aryeshsrivastava@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Digital Specialist
  Engineer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JIIT</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">4</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">221B131</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Brij Sharma</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:brijs2207@gmail.com" target="_blank">brijs2207@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Specialist Programmer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JUET</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">5</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">221B150</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Divyansh Kashyap</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:duvyansh728@gmail.com" target="_blank">duvyansh728@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Digital Specialist
  Engineer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JUET</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">6</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">221030358</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Sanskar Pandey</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:sanskar.works.2004@gmail.com" target="_blank">sanskar.works.2004@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Specialist Programmer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JUIT</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">7</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">221031059</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Rajluxmi Singh</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:rajluxmi.224@gmail.com" target="_blank">rajluxmi.224@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Digital Specialist
  Engineer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JUIT</td>
 </tr>
 <tr height="18" style="height:13.8pt">
  <td height="18" style="height:13.8pt;border-top:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;border-left:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">8</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">221030437</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Khushi Mehta</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom"><a href="mailto:khushimeh2016@gmail.com" target="_blank">khushimeh2016@gmail.com</a></td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">Digital Specialist
  Engineer</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">SELECTED</td>
  <td style="border-top:none;border-left:none;font-size:10pt;font-family:Arial,sans-serif;text-align:center;border-right:0.5pt solid windowtext;border-bottom:0.5pt solid windowtext;padding-top:1px;padding-right:1px;padding-left:1px;color:black;vertical-align:bottom">JUIT</td>
 </tr>

</tbody></table>

<p class="MsoNormal" style="margin:0cm 0cm 7.5pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><br></p>

<table border="0" cellspacing="0" cellpadding="0" width="601" style="width:451pt;border-collapse:collapse">
 <tbody><tr style="height:13.8pt">
  <td width="173" nowrap="" style="width:130pt;border:1pt solid windowtext;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><b><span style="font-size:10pt;font-family:Arial,sans-serif">Role</span></b></p>
  </td>
  <td width="235" nowrap="" valign="bottom" style="width:176pt;border-top:1pt solid windowtext;border-right:1pt solid windowtext;border-bottom:1pt solid windowtext;border-left:none;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif;color:black">&nbsp;Specialist Programmer&nbsp;</span></p>
  </td>
  <td width="193" nowrap="" valign="bottom" style="width:145pt;border-top:1pt solid windowtext;border-right:1pt solid windowtext;border-bottom:1pt solid windowtext;border-left:none;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif;color:black">Digital Specialist Engineer&nbsp;</span></p>
  </td>
 </tr>
 <tr style="height:13.8pt">
  <td width="173" nowrap="" style="width:130pt;border-right:1pt solid windowtext;border-bottom:1pt solid windowtext;border-left:1pt solid windowtext;border-top:none;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><b><span style="font-size:10pt;font-family:Arial,sans-serif">Salary Package Details</span></b></p>
  </td>
  <td width="235" nowrap="" valign="bottom" style="width:176pt;border-top:none;border-left:none;border-bottom:1pt solid windowtext;border-right:1pt solid windowtext;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif;color:black">INR 9.5&nbsp;LPA</span></p>
  </td>
  <td width="193" nowrap="" style="width:145pt;border-top:none;border-left:none;border-bottom:1pt solid windowtext;border-right:1pt solid windowtext;padding:0cm 5.4pt;height:13.8pt">
  <p class="MsoNormal" align="center" style="margin:0cm 0cm 0.0001pt;text-align:center;line-height:normal;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif;color:black">INR 6.25 LPA</span></p>
  </td>
 </tr>
</tbody></table>

<p class="MsoNormal" style="margin:0cm 0cm 7.5pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">&nbsp;</span></p>

<p class="MsoNormal" style="margin:0cm 0cm 10pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><b><u><span style="font-size:10pt;font-family:Arial,sans-serif">Date of Joining: </span></u></b><span style="font-size:10pt;font-family:Arial,sans-serif">July 2026 onwards</span></p>

<p class="MsoNormal" style="margin:0cm 0cm 0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">&nbsp;</span></p>

<p class="MsoNormal" style="margin:0cm 0cm 7.5pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">Please
note, this is a conditional job offer subject to background verification of the
candidate. If falsification of data or any other discrepancy is detected during
the background verification process, Infosys will revoke the job offer made to
the candidate.</span></p>

<p class="MsoNormal" style="margin:8.35pt 0cm;line-height:11.75pt;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif">&nbsp;</p>

<p class="MsoNormal" style="margin:8.35pt 0cm;line-height:11.75pt;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">Besties,</span></p>

<p class="MsoNormal" style="margin:8.35pt 0cm;line-height:11.75pt;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">Anita Marwaha</span></p><font color="#888888">

<p class="MsoNormal" style="margin:0cm 0cm 7.5pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial;font-size:11pt;font-family:Calibri,sans-serif"><span style="font-size:10pt;font-family:Arial,sans-serif">&nbsp;</span></p></font>
    """
    # -------------------------------------------------

    test_email = {
        "subject": input_email_subject,
        "sender": input_email_sender,
        "body": input_email_body,
    }

    initial_state = {"email": test_email}

    print("🚀 Starting email processing pipeline...")
    app.invoke(initial_state)  # type: ignore
    print("✅ Pipeline finished.")
