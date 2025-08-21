from typing import Any, Dict, List, Optional
from typing import Required, TypedDict
from pydantic import BaseModel
from bs4 import BeautifulSoup
from bs4.element import Tag
from rapidfuzz import fuzz, process
from dotenv import load_dotenv
import os
import json
from datetime import datetime
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


# state - LangGraph
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


llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-lite",
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)


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


def format_html_breakdown(html_content: Optional[str]) -> str:
    """
    Parses an HTML string (typically from package_info) and formats it into a
    clean, readable, multi-line string for display.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")
    lines = []

    # Process tables into "Key | Value" format for each row
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

    # Process paragraphs and list items
    for element in soup.find_all(["p", "li"]):
        text = element.get_text(separator=" ", strip=True)
        if text:
            lines.append(text)

    # If no specific elements were found, fall back to getting all text
    if not lines:
        fallback_text = soup.get_text(separator="\n", strip=True)
        if fallback_text:
            lines.append(fallback_text)

    # Clean up and format the final output
    if not lines:
        return ""

    # Join lines, replace non-breaking spaces, and wrap in parentheses
    result = "\n".join(lines).replace("\xa0", " ").strip()
    return f"(\n{result}\n)" if result else ""


# Graph Nodes
# -----------------------------


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

    company_extraction_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert entity extractor. Your task is to identify and extract any company names mentioned in the text. List them separated by commas. If no company is mentioned, return an empty string.",
            ),
            ("human", "Text: {raw_text}"),
        ]
    )

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


def extract_info(state: PostState) -> PostState:
    """Extracts structured information based on the notice category."""
    extraction_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an information extractor. Based on the category, "
                "extract structured details. Your response MUST be a valid JSON object.\n\n"
                "- For shortlisting: extract a list of students under the key 'students', each with 'name' and 'enrollment'. Also extract 'company_name' and 'role' if mentioned.\n"
                "- For job posting: extract 'company_name', 'role', 'package', and 'deadline'.\n"
                "- For all others: extract relevant details based on the context (e.g., 'message', 'event_name', etc.).",
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
        state["extracted"] = {"error": "Failed to parse JSON", "raw": cleaned_json_str}
    return state


def format_message(state: PostState) -> PostState:
    """
    Formats the final message using all available information, including the
    original notice fields, extracted data, and any matched job.
    """
    data = state.get("extracted", {})
    cat = state.get("category", "announcement")
    job = state.get("matched_job")
    job_location = state.get("job_location") or (job.location if job else None)
    notice = state["notice"]

    # --- Header ---
    post_date = datetime.fromtimestamp(notice.updatedAt / 1000).strftime(
        "%B %d, %Y at %I:%M %p"
    )
    title = notice.title
    msg_parts = [f"**{title}**\n"]

    # --- Body (category-specific) ---
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
            package_lpa = job.package / 100000
            package_info = f"{package_lpa:.2f} LPA"
            package_breakdown = format_html_breakdown(job.package_info)
        else:
            extracted_package = data.get("package")
            package_info = str(extracted_package) if extracted_package else None
            package_breakdown = ""

        msg_parts.append(f"**🎉 Shortlisting Update**")
        msg_parts.append(f"**Company:** {company_name}")
        msg_parts.append(f"**Role:** {role}")
        if job_location:
            msg_parts.append(f"**Location:** {job_location}")
        msg_parts.append("")  # blank line
        if total_shortlisted > 0 and student_list:
            msg_parts.append(f"**Total Shortlisted:** {total_shortlisted}")
            msg_parts.append("Congratulations to the following students:")
            msg_parts.append(student_list)

        if job and job.hiring_flow:
            hiring_flow_list = "\n".join(
                [f"{i+1}. {step}" for i, step in enumerate(job.hiring_flow)]
            )
            msg_parts.append(f"\n**Hiring Process:**\n{hiring_flow_list}")
        if package_info:
            msg_parts.append(f"\n**CTC:** {package_info} {package_breakdown}")

    elif cat == "job posting":
        if job:
            # details from the matched job object
            company_name = job.company
            role = job.job_profile
            job_location = job.location
            package_lpa = job.package / 100000
            package_info = f"{package_lpa:.2f} LPA"
            package_breakdown = format_html_breakdown(job.package_info)
            deadline = (
                datetime.fromtimestamp(job.deadline / 1000).strftime(
                    "%B %d, %Y, %I:%M %p"
                )
                if job.deadline
                else "Not specified"
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

            # Format hiring flow into a numbered list
            hiring_flow_list = "\n".join(
                [f"{i+1}. {step}" for i, step in enumerate(job.hiring_flow)]
            )
            hiring_flow_str = f"**Hiring Flow:**\n{hiring_flow_list}"

        else:
            # Fallback to extracted info if no job is matched
            company_name = data.get("company_name", "N/A")
            role = data.get("role", "N/A")
            job_location = None
            package_info = data.get("package", "Not specified")
            package_breakdown = ""
            deadline = data.get("deadline", "Not specified")
            eligibility_str = ""
            hiring_flow_str = ""

        msg_parts.append(f"**📢 Job Posting**")
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

    else:  # Fallback for announcement, update, etc.
        message_content = data.get(
            "message", state.get("raw_text", "See notice for details.")
        )
        msg_parts.append(f"**🔔 {cat.capitalize()}**\n")
        msg_parts.append(message_content.replace(title, "").strip())
        if data.get("deadline"):
            msg_parts.append(f"\n⚠️ **Deadline:** {data.get('deadline')}")

    # --- Footer ---
    msg_parts.append(f"*Posted by*: {notice.author} \n*On:* {post_date}")

    state["formatted_message"] = "\n".join(msg_parts)
    print("--- 5. Message Formatted ---")
    return state


# build LangGraph

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
    # Assume data files are in a 'data' subdirectory relative to the script
    data_dir = os.path.join(os.path.dirname(__file__), "data")

    notices_path = os.path.join(data_dir, "structured_notices.json")
    with open(notices_path, "r") as f:
        notices_data = json.load(f)

    jobs_path = os.path.join(data_dir, "structured_job_listings.json")
    with open(jobs_path, "r") as f:
        jobs_data = json.load(f)

    all_jobs = []
    for job_dict in jobs_data:
        eligibility_marks_data = job_dict.get("eligibility_marks", [])
        job_dict["eligibility_marks"] = [
            EligibilityMark(**mark) for mark in eligibility_marks_data
        ]
        all_jobs.append(Job(**job_dict))

    final_records: List[Dict[str, Any]] = []

    for notice_dict in notices_data:
        notice = Notice(**notice_dict)

        inputs = {
            "notice": notice,
            "jobs": all_jobs,
        }

        result = app.invoke(inputs)  # type: ignore

        print("\n" + "=" * 30)
        print("      FINAL OUTPUT")
        print("=" * 30)
        print("Notice ID:", result.get("id"))
        print("Matched Job ID:", result.get("matched_job_id"))
        print("\n--- Formatted Message ---")
        print(result.get("formatted_message"))
        print("=" * 30)

        # Build enriched record for output JSON
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
            pkg_str = f"{pkg_lpa:.2f} LPA"
            pkg_breakdown = format_html_breakdown(matched_job.package_info)
        else:
            pkg_val = extracted.get("package")
            pkg_str = str(pkg_val) if pkg_val is not None else None
            pkg_breakdown = ""

        enriched: Dict[str, Any] = {
            **notice_dict,
            "category": result.get("category"),
            "matched_job_id": result.get("matched_job_id"),
            "job_company": job_company,
            "job_role": job_role,
            "job_location": job_location_out,
            "package": pkg_str,
            "package_breakdown": pkg_breakdown,
            "formatted_message": result.get("formatted_message"),
        }
        final_records.append(enriched)

    # Write final results to data/final_notices.json
    final_out_path = os.path.join(data_dir, "final_notices.json")
    with open(final_out_path, "w") as f:
        json.dump(final_records, f, ensure_ascii=False, indent=4)
    print(f"\nSaved enriched notices to: {final_out_path}")
