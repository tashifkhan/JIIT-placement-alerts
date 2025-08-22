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
    role: Optional[str] = None


class RolePackage(BaseModel):
    role: str
    packages: List[str]  # Array of package amounts/details
    package_details: Optional[str] = None  # Simplified package breakdown as string


class PlacementOffer(BaseModel):
    company: str
    roles: List[RolePackage]  # Array of roles with their packages
    job_location: Optional[List[str]] = None
    joining_date: Optional[str] = None
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
        return {**state, "is_relevant": True}

    print("❌ Email classified as NOT RELEVANT. Halting workflow.")
    return {**state, "is_relevant": False}


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
        json_content = extract_json_from_response(str(response.content))
        data = json.loads(json_content)

        # Validate the extracted data by creating a PlacementOffer instance
        offer = PlacementOffer(**data)
        # Add metadata from the original email
        offer.email_subject = email["subject"]
        offer.email_sender = email["sender"]
        print("✅ Information extracted and validated successfully.")
        return {**state, "extracted_offer": offer}
    except ValidationError as e:
        print(
            f"❌ Pydantic Validation Error: The LLM output did not match the required schema.\n{e}"
        )
        return {**state, "extracted_offer": None}
    except json.JSONDecodeError as e:
        print(
            f"❌ JSON Parsing Error: The LLM output was not valid JSON.\nError: {e}\nResponse: {response.content}"
        )
        return {**state, "extracted_offer": None}


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
    input_email_subject = "Oracle Financial Services Software (OFSS) - Hiring for Full Time Role from 2026 Batch - Offers"
    input_email_sender = "anitamarwaha.tnp@gmail.com"
    input_email_body = """
    <div class="aju"><div class="aCi"><div class="aFg" style="display: none;"></div><img id=":o6_7-e" name=":o6" src="https://lh3.googleusercontent.com/a-/ALV-UjW97098ddyNySVJTL1bc3RLVjxDvAWNYomMrUWBeYMvkVp1OJAm=s80-p" class="ajn" style="background-color: #cccccc" jid="vinod.jptnp@gmail.com" data-hovercard-id="vinod.jptnp@gmail.com" data-name="Vinod Kumar" aria-hidden="true"></div></div><div class="gs"><div class="gE iv gt"><table cellpadding="0" class="cf gJ"><tbody><tr class="acZ"><td class="gF gK"><table cellpadding="0" class="cf ix"><tbody><tr><td class="c2"><h3 class="iw gFxsud"><span translate="no" class="qu" role="gridcell" tabindex="-1"><span email="vinod.jptnp@gmail.com" name="Vinod Kumar" data-hovercard-id="vinod.jptnp@gmail.com" class="gD"><span>Vinod Kumar</span></span> <span class="cfXrwd"></span><span class="go"><span aria-hidden="true">&lt;</span>vinod.jptnp@gmail.com<span aria-hidden="true">&gt;</span></span> </span></h3><h3 class="iw rapwed"></h3></td></tr></tbody></table></td><td class="gH bAk"><div class="gK"><span></span><span id=":1wk" class="g3" title="20 Aug 2025, 13:19" alt="20 Aug 2025, 13:19" role="gridcell" tabindex="-1">20 Aug 2025, 13:19 (2 days ago)</span><div class="zd bi4" aria-label="Not starred" tabindex="0" role="checkbox" aria-checked="false" style="outline:0" jslog="20511; u014N:cOuCgd,Kr2w4b; 1:WyIjdGhyZWFkLWY6MTg0MDk1OTkwNTE5MjQ0MDIzMyJd; 4:WyIjbXNnLWY6MTg0MDk1OTkwNTE5MjQ0MDIzMyJd" data-tooltip="Not starred"><span class="T-KT"><img class="f T-KT-JX" src="images/cleardot.gif" alt=""></span></div></div></td><td class="gH"></td><td class="gH acX bAm" rowspan="2"><div class="T-I J-J5-Ji T-I-Js-IF R1Zuwf T-I-ax7 T-I-JE L3" role="button" jslog="190355; u014N:cOuCgd,Kr2w4b; 67:WzAsMTRd" style="user-select: none;" aria-disabled="true" aria-label="You can't react to a group with an emoji" data-tooltip="You can't react to a group with an emoji"><img class="qfynfc T-I-J3 " role="button" src="images/cleardot.gif" alt=""></div><div class="T-I J-J5-Ji T-I-Js-IF aaq T-I-ax7 L3" role="button" tabindex="0" jslog="21576; u014N:cOuCgd,Kr2w4b,xr6bB; 4:WyIjbXNnLWY6MTg0MDk1OTkwNTE5MjQ0MDIzMyIsbnVsbCxudWxsLG51bGwsMSwwLFsxLDAsMF0sMjgyLDIwOTUsbnVsbCxudWxsLG51bGwsbnVsbCxudWxsLDEsbnVsbCxudWxsLFsyXSxudWxsLG51bGwsbnVsbCxudWxsLG51bGwsbnVsbCwwLDBd" style="user-select: none;" data-tooltip="Reply" aria-label="Reply"><img class="hB T-I-J3 " role="button" src="images/cleardot.gif" alt=""></div><div id=":1wy" class="T-I J-J5-Ji T-I-Js-Gs aap T-I-awG T-I-ax7 L3" role="button" tabindex="0" style="user-select: none;" aria-expanded="false" aria-haspopup="true" aria-label="More message options" data-tooltip="More"><img class="hA T-I-J3" role="menu" src="images/cleardot.gif" alt=""></div></td></tr><tr class="acZ xD"><td colspan="3"><table cellpadding="0" class="cf adz"><tbody><tr><td class="ady"><div class="iw ajw"><span translate="no" class="hb">to <span email="jiitengg2026@googlegroups.com" name="jiitengg2026" data-hovercard-id="jiitengg2026@googlegroups.com" class="g2" data-hovercard-owner-id="25">jiitengg2026</span> </span></div><div id=":1wx" aria-haspopup="true" class="ajy" role="button" tabindex="0" data-tooltip="Show details" aria-label="Show details"><img class="ajz" src="images/cleardot.gif" alt=""></div></td></tr></tbody></table></td></tr></tbody></table></div><div id=":1wl"><div class="KKSLrd"></div><div class="qQVYZb"></div><div class="utdU2e"></div><div class="lQs8Hd" jsaction="SN3rtf:rcuQ6b" jscontroller="i3Ohde"></div><div class="wl4W9b" jsaction="LNSvUb:.CLIENT;xSdBYb:.CLIENT;CDWmBe:.CLIENT;EtHLdc:.CLIENT;pQnh7:.CLIENT;pKHw7e:.CLIENT;Z03mxd:.CLIENT;NZLNxf:.CLIENT;bXglpe:.CLIENT;mzh2Bc:.CLIENT"></div></div><div class=""><div class="aHl"></div><div id=":1ww" tabindex="-1"></div><div id=":1wo" class="ii gt" jslog="20277; u014N:xr6bB; 1:WyIjdGhyZWFkLWY6MTg0MDk1OTkwNTE5MjQ0MDIzMyJd; 4:WyIjbXNnLWY6MTg0MDk1OTkwNTE5MjQ0MDIzMyIsbnVsbCxudWxsLG51bGwsMSwwLFsxLDAsMF0sMjgyLDIwOTUsbnVsbCxudWxsLG51bGwsbnVsbCxudWxsLDEsbnVsbCxudWxsLFsyXSxudWxsLG51bGwsbnVsbCxudWxsLG51bGwsbnVsbCwwLDBd"><div id=":1wn" class="a3s aiL "><div dir="ltr"><div dir="ltr"><div dir="ltr"><div dir="ltr"><div dir="ltr"><div dir="ltr"><div class="gmail_default"><div class="gmail_default"><p class="MsoNormal" style="font-family:verdana,sans-serif;font-size:small;margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><b><font color="#0000ff"><span></span></font></b></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><font color="#0000ff"><span class="il"><span class="il"><span class="il">Congratulations</span></span></span>!!!</font></b><span></span></font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><span style="color:black"><font face="verdana, sans-serif">Following students have been offered by <b>Oracle Financial Services Software (OFSS).</b></font></span></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u><span style="color:black">List of students:</span></u></b><span></span></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><b><u><span style="color:black"><font face="verdana, sans-serif"><br></font></span></u></b></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif"><b><u><a href="http://S.NO" target="_blank" data-saferedirecturl="https://www.google.com/url?q=http://S.NO&amp;source=gmail&amp;ust=1755922713602000&amp;usg=AOvVaw2psZ7e941AdL9-hEuxFWaF">S.NO</a>.<span style="white-space:pre-wrap">	</span>ENROLLMENT NO<span style="white-space:pre-wrap">	</span>NAME<span style="white-space:pre-wrap">	</span>INSTITUTECODE<span style="white-space:pre-wrap">	</span>PROGRAMCODE<span style="white-space:pre-wrap">	</span>BRANCHCODE<span style="white-space:pre-wrap">	</span>GMAIL ID</u>&nbsp;</b></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">1<span style="white-space:pre-wrap">	</span>9922103156<span style="white-space:pre-wrap">	</span>ADITYA KUMAR SINGH<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:adisingh6678@gmail.com" target="_blank">adisingh6678@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">2<span style="white-space:pre-wrap">	</span>9922103044<span style="white-space:pre-wrap">	</span>CHAHAT KHATTAR<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:chahatkhattar3865@gmail.com" target="_blank">chahatkhattar3865@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">3<span style="white-space:pre-wrap">	</span>9922103017<span style="white-space:pre-wrap">	</span>SANVI SRIVASTAVA<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:sonaaurum04@gmail.com" target="_blank">sonaaurum04@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">4<span style="white-space:pre-wrap">	</span>22103302<span style="white-space:pre-wrap">	</span>ALOKIK GARG<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:alokikgarg24@gmail.com" target="_blank">alokikgarg24@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">5<span style="white-space:pre-wrap">	</span>22103082<span style="white-space:pre-wrap">	</span>ASTHA TIWARI<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:astha.tiwari922@gmail.com" target="_blank">astha.tiwari922@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">6<span style="white-space:pre-wrap">	</span>22103202<span style="white-space:pre-wrap">	</span>PANKHURI ASTHANA<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:p.asthana192@gmail.com" target="_blank">p.asthana192@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">7<span style="white-space:pre-wrap">	</span>22103326<span style="white-space:pre-wrap">	</span>YASHI JAITLY<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:jaitlyyashi26@gmail.com" target="_blank">jaitlyyashi26@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">8<span style="white-space:pre-wrap">	</span>22103091<span style="white-space:pre-wrap">	</span>PRAKRITI YADAV<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:prakriti14092004@gmail.com" target="_blank">prakriti14092004@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">9<span style="white-space:pre-wrap">	</span>22103221<span style="white-space:pre-wrap">	</span>MANYA RAI<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:manyarai945@gmail.com" target="_blank">manyarai945@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">10<span style="white-space:pre-wrap">	</span>22103169<span style="white-space:pre-wrap">	</span>SIDDHI SINGHAL<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>CSE<span style="white-space:pre-wrap">	</span><a href="mailto:singhalsiddhi5@gmail.com" target="_blank">singhalsiddhi5@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">11<span style="white-space:pre-wrap">	</span>9922102118<span style="white-space:pre-wrap">	</span>HARSH KUMAWAT<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>ECE<span style="white-space:pre-wrap">	</span><a href="mailto:kumawatharsh2004@gmail.com" target="_blank">kumawatharsh2004@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">12<span style="white-space:pre-wrap">	</span>22102085<span style="white-space:pre-wrap">	</span>AKSHAT TOMAR<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>ECE<span style="white-space:pre-wrap">	</span><a href="mailto:akshat.tomar2003@gmail.com" target="_blank">akshat.tomar2003@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">13<span style="white-space:pre-wrap">	</span>22102053<span style="white-space:pre-wrap">	</span>HITENDRA NARAYAN GOSWAMI<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>ECE<span style="white-space:pre-wrap">	</span><a href="mailto:hitendra.goswami17@gmail.com" target="_blank">hitendra.goswami17@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">14<span style="white-space:pre-wrap">	</span>22102115<span style="white-space:pre-wrap">	</span>SAHIL KHANNA<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>ECE<span style="white-space:pre-wrap">	</span><a href="mailto:sk12102003@gmail.com" target="_blank">sk12102003@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">15<span style="white-space:pre-wrap">	</span>22102153<span style="white-space:pre-wrap">	</span>VAIBHAV BHATT<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>ECE<span style="white-space:pre-wrap">	</span><a href="mailto:vaibhavbhatt9666@gmail.com" target="_blank">vaibhavbhatt9666@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">16<span style="white-space:pre-wrap">	</span>22104047<span style="white-space:pre-wrap">	</span>NIHARIKA MISHRA<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>IT<span style="white-space:pre-wrap">	</span><a href="mailto:mishraniharika108@gmail.com" target="_blank">mishraniharika108@gmail.com</a></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font color="#000000" face="verdana, sans-serif">17<span style="white-space:pre-wrap">	</span>22104056<span style="white-space:pre-wrap">	</span>SHAMBHAVI GAUR<span style="white-space:pre-wrap">	</span>JIIT<span style="white-space:pre-wrap">	</span>B.Tech<span style="white-space:pre-wrap">	</span>IT<span style="white-space:pre-wrap">	</span><a href="mailto:gaurshambhavi31@gmail.com" target="_blank">gaurshambhavi31@gmail.com</a></font></p><div><font face="verdana, sans-serif"><br></font></div>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u><span style="color:black">The offer is as below:</span></u></b><span></span></font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u><span style="color:black">Role</span></u></b><span style="color:black">: Associate Consultant</span></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><span style="color:black"><br></span></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><b style="font-family:verdana,sans-serif"><u><span style="color:black">Joining</span></u></b><b style="font-family:verdana,sans-serif"><span style="color:black">:&nbsp;&nbsp;</span></b><span style="font-family:verdana,sans-serif;color:black">June, 2026 and onwards.</span><br style="font-family:verdana,sans-serif"><font face="verdana, sans-serif"><span style="color:black"><br>
<b><u>Job Location</u></b>: Bengaluru, Mumbai, Pune or Chennai (Location will be allotted to&nbsp; students based on business requirements.)<br>
<b><u><br>Salary Package</u></b>: INR 9,82,054/- Per Annum</span><span></span></font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">&nbsp;</font></p>

<p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u>Salary Break-up / Additional Compensation</u>:</b></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u><br></u></b><b>Performance Incentives (Included in Year 1 Earning Potential):</b>&nbsp;10% of Base
pay - INR 85,100 (linked to individual performance)<br>
<br><b>
Additional Perks/Benefits (Included in Year 1 Earning
Potential):</b>&nbsp;Applicable Employer Contribution towards PF Fund<br>
<br><b>
Relocation</b> - Assistance for Relocating to the joining location</font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><br></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><b><u>Note</u></b>: Offer letter will be shared with the students directly near to the joining date.<br><br></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><br></font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><b><font face="verdana, sans-serif">Thanks &amp; Regards</font></b></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">Vinod Kumar</font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">Sr. Officer - T &amp; P</font></p><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif">JIIT, Noida</font></p><font color="#888888"><p class="MsoNormal" style="margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><font face="verdana, sans-serif"><br></font></p><p class="MsoNormal" style="font-family:verdana,sans-serif;font-size:small;margin-bottom:0.0001pt;line-height:normal;background-image:initial;background-position:initial;background-size:initial;background-repeat:initial;background-origin:initial;background-clip:initial"><span style="font-size:12pt;font-family:Arial,&quot;sans-serif&quot;"><br></span></p></font></div></div></div></div></div><font color="#888888">
</font></div></div></div><font color="#888888">

<p></p>

-- <br>
You received this message because you are subscribed to the Google Groups "JIIT Engg 2026" group.<br>
To unsubscribe from this group and stop receiving emails from it, send an email to <a href="mailto:jiitengg2026+unsubscribe@googlegroups.com" target="_blank">jiitengg2026+unsubscribe@<wbr>googlegroups.com</a>.<br>
To view this discussion visit <a href="https://groups.google.com/d/msgid/jiitengg2026/CAPBUcCbK-Wcyfo_zQbORjzBv1S%3D266zMVgTrLmMOzM-%3Dh-FYTQ%40mail.gmail.com?utm_medium=email&amp;utm_source=footer" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://groups.google.com/d/msgid/jiitengg2026/CAPBUcCbK-Wcyfo_zQbORjzBv1S%253D266zMVgTrLmMOzM-%253Dh-FYTQ%2540mail.gmail.com?utm_medium%3Demail%26utm_source%3Dfooter&amp;source=gmail&amp;ust=1755922713602000&amp;usg=AOvVaw0LrDeS8ksebLEUiNKn12eq">https://groups.google.com/d/<wbr>msgid/jiitengg2026/CAPBUcCbK-<wbr>Wcyfo_zQbORjzBv1S%<wbr>3D266zMVgTrLmMOzM-%3Dh-FYTQ%<wbr>40mail.gmail.com</a>.<br>
For more options, visit <a href="https://groups.google.com/d/optout" target="_blank" data-saferedirecturl="https://www.google.com/url?q=https://groups.google.com/d/optout&amp;source=gmail&amp;ust=1755922713602000&amp;usg=AOvVaw3EnK2fXbn5sSp1zSRd7gd2">https://groups.google.com/d/<wbr>optout</a>.<br>
</font></div><div class="yj6qo"></div></div><div class="WhmR8e" data-hash="0"></div></div></div><div class="ajx"></div>
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
