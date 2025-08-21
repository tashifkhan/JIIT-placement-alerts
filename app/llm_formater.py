from typing import Any, Dict, List, Optional
from typing import Required, TypedDict
from pydantic import BaseModel
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process
from dotenv import load_dotenv
import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END


load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")


class EligibilityMark(BaseModel):
    level: str
    criteria: float


class Job(BaseModel):
    id: str
    job_profile: str
    company: str
    placement_category_code: int
    placement_category: str
    content: str
    createdAt: Optional[int]
    deadline: Optional[int]
    eligibility_marks: List[EligibilityMark]
    eligibility_courses: List[str]
    allowed_genders: List[str]
    job_description: str
    location: str
    package: float
    package_info: str
    required_skills: List[str]
    hiring_flow: List[str]
    placement_type: Optional[str] = None


class Notice(BaseModel):
    id: str
    title: str
    content: str
    author: str
    updatedAt: int
    createdAt: int


# State for LangGraph
class PostState(TypedDict, total=False):
    notice: Required["Notice"]
    jobs: Required[List["Job"]]

    id: str
    raw_text: str
    category: str
    matched_job: Optional["Job"]
    matched_job_id: Optional[str]
    extracted: Dict[str, Any]
    formatted_message: str


llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)


# Helper Function
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


# Graph Nodes


def extract_text(state: PostState) -> PostState:
    """Extracts clean text from the notice's HTML content."""
    soup = BeautifulSoup(state["notice"].content, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    state["raw_text"] = (state["notice"].title + "\n" + text).strip()
    state["id"] = state["notice"].id
    print("--- 1. Text Extracted ---")
    return state


def classify_post(state: PostState) -> PostState:
    """Classifies the notice into a predefined category."""
    classification_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a classifier. Categorize the notice into one of: "
                "[update, shortlisting, announcement, hackathon, webinar, job posting].",
            ),
            ("human", "{raw_text}"),
        ]
    )
    chain = classification_prompt | llm
    result = chain.invoke({"raw_text": state.get("raw_text", "")})
    category = _ensure_str_content(result.content).strip().lower()
    state["category"] = category
    print(f"--- 2. Classified as: {category} ---")
    return state


def match_job(state: PostState) -> PostState:
    """
    Intelligently matches the notice to a job by first extracting company names
    from the notice and then performing a fuzzy match.
    """
    notice_text = state.get("raw_text", "")
    jobs = state.get("jobs", [])

    # Prompt to specifically extract company names
    company_extraction_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert entity extractor. Your task is to identify and extract any company names mentioned in the text. List them separated by commas. If no company is mentioned, return an empty string.",
            ),
            ("human", "Text: {raw_text}"),
        ]
    )

    # 1. Use LLM to extract potential company names
    extraction_chain = company_extraction_prompt | llm
    result = extraction_chain.invoke({"raw_text": notice_text})
    extracted_names_str = _ensure_str_content(result.content).strip()

    if not extracted_names_str:
        print("--- 3. No company names extracted, skipping match ---")
        state["matched_job"] = None
        state["matched_job_id"] = None
        return state

    extracted_names = [name.strip() for name in extracted_names_str.split(",")]
    print(f"DEBUG: Extracted potential company names -> {extracted_names}")

    # 2. Perform a fuzzy match for each extracted name
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

    # 3. Assign the best match if it meets the threshold
    if best_overall_match_job and highest_score > 80:
        state["matched_job"] = best_overall_match_job
        state["matched_job_id"] = best_overall_match_job.id
        print(f"--- 3. Matched Job ID: {best_overall_match_job.id} ---")
    else:
        state["matched_job"] = None
        state["matched_job_id"] = None
        print("--- 3. No suitable job match found ---")

    return state


def extract_info(state: PostState) -> PostState:
    """Extracts structured information based on the notice category."""
    extraction_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an information extractor. Based on the category, "
                "extract structured details. Your response MUST be a valid JSON object.\n\n"
                "- For shortlisting: extract a list of students under the key 'students'. Each student should be an object with 'name' and 'enrollment'. Also extract 'total_shortlisted' if mentioned.\n"
                "- For all others: extract relevant details based on the context (e.g., 'deadline', 'message', 'event_name', etc.).",
            ),
            ("human", "Category: {category}\n\nNotice:\n{raw_text}"),
        ]
    )
    chain = extraction_prompt | llm

    result = chain.invoke(
        {
            "category": state.get("category", "announcement"),
            "raw_text": state.get("raw_text", ""),
        }
    )
    raw_content = _ensure_str_content(result.content)

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


def format_message(state: PostState) -> PostState:
    """Formats the final message based on all gathered data."""
    data = state.get("extracted", {})
    cat = state.get("category", "announcement")
    job = state.get("matched_job")
    msg = ""

    if cat == "shortlisting" and job:
        students = data.get("students", [])
        student_list = "\n".join(
            [
                f"- {s.get('name', 'Unknown')} ({s.get('enrollment', 'N/A')})"
                for s in students
                if isinstance(s, dict)
            ]
        )
        total_shortlisted = data.get("total_shortlisted", len(students))
        msg = (
            f"**🎉 Shortlisting Update**\n\n"
            f"**Company:** {job.company}\n"
            f"**Role:** {job.job_profile}\n\n"
            f"**Total Shortlisted:** {total_shortlisted}\n"
            f"Congratulations to the following students:\n"
            f"{student_list}"
        )
    else:
        deadline_str = (
            f"\n⚠️ **Deadline:** {data.get('deadline')}" if data.get("deadline") else ""
        )
        message_content = data.get(
            "message", "Please refer to the original notice for details."
        )
        msg = f"**🔔 {cat.capitalize()}**\n\n" f"{message_content}" f"{deadline_str}"

    state["formatted_message"] = msg.strip()
    print("--- 5. Message Formatted ---")
    return state


# Build LangGraph
workflow = StateGraph(PostState)

workflow.add_node("extract_text", extract_text)
workflow.add_node("classify_post", classify_post)
workflow.add_node("match_job", match_job)
workflow.add_node("extract_info", extract_info)
workflow.add_node("format_message", format_message)

workflow.set_entry_point("extract_text")
workflow.add_edge("extract_text", "classify_post")
workflow.add_edge("classify_post", "match_job")
workflow.add_edge("match_job", "extract_info")
workflow.add_edge("extract_info", "format_message")
workflow.add_edge("format_message", END)

app = workflow.compile()


if __name__ == "__main__":
    notice = Notice(
        id="1902cd5f-5870-4fdb-8eaa-28e0a6e68fbe",
        title="Shortlist published for Stage 4 (Technical interview 1) of Lending Labs (formerly Kuliza Technologies),'s Software Engineer Intern ",
        content="""
        Following students are shortlisted for Stage 4 (Technical interview 1)
        <ol>
            <li>Shiv Pandey (22103093)</li>
            <li>Vansh Tomar (22103274)</li>
            <li>Harsh Vardhan (22103281)</li>
        </ol>
        """,
        author="Anurag Srivastava",
        updatedAt=1755751057000,
        createdAt=1755751057000,
    )

    jobs = [
        Job(
            id="7d7dd5e9-51e6-46b6-a0e2-c8cabf06acdc",
            job_profile="Software Intern",
            company="Lending Labs (formerly Kuliza Technologies)",
            placement_category_code=3,
            placement_category="Offer is more than 4.6 lacs",
            content="",
            createdAt=1755688649000,
            deadline=1755751008000,
            eligibility_marks=[EligibilityMark(level="UG", criteria=7.0)],
            eligibility_courses=["B.Tech - CSE", "B.Tech - IT"],
            allowed_genders=["Male", "Female", "Other"],
            job_description="Internship role",
            location="Noida",
            package=600000,
            package_info="6 LPA (Fixed + Bonus)",
            required_skills=[],
            hiring_flow=["Test", "Interview", "HR"],
        )
    ]

    inputs = {
        "notice": notice,
        "jobs": jobs,
    }
    post_state = PostState(notice=notice, jobs=jobs)
    result = app.invoke(post_state)

    print("\n" + "=" * 30)
    print("      FINAL OUTPUT")
    print("=" * 30)
    print("Notice ID:", result.get("id"))
    print("Matched Job ID:", result.get("matched_job_id"))
    print("\n--- Formatted Message ---")
    print(result.get("formatted_message"))
    print("=" * 30)
