"""LangGraph node handlers for SuperSet notice formatting."""

import json
import logging

from bs4 import BeautifulSoup
from langchain.prompts import ChatPromptTemplate
from rapidfuzz import fuzz, process

from services.notice_formatter.state import PostState


logger = logging.getLogger(__name__)


class NoticeFormatterGraphNodeMixin:
    """LLM graph node handlers for notice classification and extraction."""

    def extract_text(self, state: PostState) -> PostState:
        """Extract clean text from the notice's HTML content."""
        soup = BeautifulSoup(state["notice"].content, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        state["raw_text"] = (state["notice"].title + "\n" + text).strip()
        state["id"] = state["notice"].id
        logger.debug("Notice text extracted")
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
        logger.debug("Notice classified as %s", category)
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
            logger.debug("No company names extracted; skipping job match")
            state["matched_job"] = None
            state["matched_job_id"] = None
            return state

        extracted_names = [
            name.strip() for name in extracted_names_str.split(",") if name.strip()
        ]
        logger.debug("Extracted %s possible company names", len(extracted_names))

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

        logger.debug("Highest company match score: %s", highest_score)

        if best_overall_match_job and highest_score > 80:
            state["matched_job"] = best_overall_match_job
            state["matched_job_id"] = best_overall_match_job.id
            state["job_location"] = best_overall_match_job.location
            logger.debug("Matched notice to job %s", best_overall_match_job.id)
        else:
            state["matched_job"] = None
            state["matched_job_id"] = None
            state["job_location"] = None
            logger.debug("No suitable job match found")

        return state

    def enrich_matched_job(self, state: PostState) -> PostState:
        """Enrich the matched job if an enricher callback is provided."""
        matched_job = state.get("matched_job")
        enricher = state.get("job_enricher")

        if matched_job and enricher:
            try:
                logger.debug("Enriching matched job %s", matched_job.id)
                enriched_job = enricher(matched_job)
                if enriched_job:
                    state["matched_job"] = enriched_job
                    state["job_location"] = enriched_job.location
                    jobs = state.get("jobs", [])
                    state["jobs"] = [
                        enriched_job if j.id == matched_job.id else j for j in jobs
                    ]
                    logger.debug("Matched job enriched successfully")
            except Exception as e:
                logger.warning("Failed to enrich matched job", exc_info=True)

        return state

    def extract_info(self, state: PostState) -> PostState:
        """Extract structured information based on the notice category."""
        extraction_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You extract structured JSON for MongoDB notice documents. "
                    "Return ONLY one valid JSON object, with no markdown, no prose, and no formatted notification text. "
                    "Use null for unknown scalar fields and [] for unknown list fields. "
                    "Do not include email headers, sender email addresses, phone numbers, or forwarding metadata.\n\n"
                    "Allowed keys by category:\n"
                    "- shortlisting: company_name, role, round, venue, interview_date, total_shortlisted, students. "
                    "students must be an array of objects with name and enrollment only.\n"
                    "- job posting: company_name, role, package, deadline, location, hiring_flow, eligibility_criteria, links. "
                    "hiring_flow and eligibility_criteria must be arrays of strings.\n"
                    "- webinar: event_name, topic, speaker, date, time, venue, registration_link, deadline, links.\n"
                    "- hackathon: event_name, theme, start_date, end_date, registration_deadline, registration_link, prize_pool, team_size, venue, organizer, links.\n"
                    "- update, announcement, reminder: message, deadline, links, company_name, role when present.\n\n"
                    "Date-like values should be ISO strings when possible. Links must be arrays of URL strings. "
                    "The response is a data object only; it must not contain formatted_message or Telegram/Markdown-rendered content.",
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
            logger.debug("Structured notice information extracted")
        except json.JSONDecodeError:
            logger.warning("Failed to parse structured notice JSON")
            state["extracted"] = {
                "error": "Failed to parse JSON",
                "raw": cleaned_json_str,
            }
        return state
