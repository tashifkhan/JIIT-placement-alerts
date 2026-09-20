"""Notice formatter service and implementation modules."""

from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, StateGraph

from core import get_settings
from core.llm import DEFAULT_GEMINI_MODEL, build_chat_model
from core.year_context import DEFAULT_PLACEMENT_YEAR, normalize_year
from services.notice_formatter.graph_nodes import NoticeFormatterGraphNodeMixin
from services.notice_formatter.helpers import NoticeFormatterHelperMixin
from services.notice_formatter.state import EligibilityMark, Job, Notice, PostState


class NoticeFormatterService(
    NoticeFormatterHelperMixin,
    NoticeFormatterGraphNodeMixin,
):
    """LLM-based structured extractor for SuperSet notices."""

    def __init__(
        self,
        google_api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        temperature: float = 0,
        placement_year: str | None = None,
    ):
        settings = get_settings()
        self.placement_year = normalize_year(
            placement_year
            or getattr(settings, "active_placement_year", None)
            or DEFAULT_PLACEMENT_YEAR
        )
        self.llm = build_chat_model(
            model=model,
            temperature=temperature,
            api_key=google_api_key,
        )
        self.app = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph notice-formatting workflow."""
        workflow = StateGraph(PostState)
        workflow.add_node("extract_text", self.extract_text)
        workflow.add_node("classify_post", self.classify_post)
        workflow.add_node("match_job", self.match_job)
        workflow.add_node("enrich_matched_job", self.enrich_matched_job)
        workflow.add_node("extract_info", self.extract_info)
        workflow.set_entry_point("extract_text")
        workflow.add_edge("extract_text", "classify_post")
        workflow.add_edge("classify_post", "match_job")
        workflow.add_edge("match_job", "enrich_matched_job")
        workflow.add_edge("enrich_matched_job", "extract_info")
        workflow.add_edge("extract_info", END)
        return workflow.compile()

    def format_notice(
        self,
        notice: Notice,
        jobs: Sequence[Job],
        job_enricher: Any | None = None,
    ) -> dict[str, Any]:
        """
        Format a notice with LLM-based classification, matching, and formatting.

        Args:
            notice: Notice to format.
            jobs: Jobs to match against.
            job_enricher: Optional callback for enriching a matched job before
                rendering and structured output mapping.

        Returns:
            Enriched notice dict with structured metadata.
        """
        inputs = {"notice": notice, "jobs": list(jobs), "job_enricher": job_enricher}
        result: PostState = self.app.invoke(inputs)  # type: ignore
        matched_job = result.get("matched_job")
        matched_job_id = result.get("matched_job_id")
        matched_job_summary = self._matched_job_summary(matched_job)
        extracted = result.get("extracted", {}) or {}
        category = (result.get("category") or "announcement").strip().lower()

        job_company = matched_job.company if matched_job else extracted.get("company_name")
        job_role = matched_job.job_profile if matched_job else extracted.get("role")
        job_location_out = result.get("job_location") or (
            matched_job.location if matched_job else extracted.get("location")
        )

        if matched_job:
            pkg_str = self._format_package(matched_job.package, matched_job.annum_months)
            pkg_breakdown = self.format_html_breakdown(matched_job.package_info) or None
            eligibility_criteria = self._job_eligibility(matched_job)
            hiring_flow = self._compact_list(matched_job.hiring_flow)
        else:
            pkg_val = extracted.get("package")
            pkg_str = str(pkg_val) if pkg_val is not None else None
            pkg_breakdown = None
            eligibility_criteria = self._compact_list(extracted.get("eligibility_criteria"))
            hiring_flow = self._compact_list(extracted.get("hiring_flow"))

        shortlisted_students = (
            self._normalize_students(extracted.get("students"))
            if category == "shortlisting"
            else []
        )

        return {
            **notice.model_dump(),
            "source": "Superset",
            "type": category.replace(" ", "_"),
            "category": category,
            "year": self.placement_year,
            "details": self._build_details(extracted),
            "matched_job_id": matched_job_id,
            "related_job_id": matched_job_id,
            "matched_job": matched_job_summary,
            "job_company": job_company,
            "job_role": job_role,
            "location": job_location_out,
            "package": pkg_str,
            "package_breakdown": pkg_breakdown,
            "eligibility_criteria": eligibility_criteria,
            "hiring_flow": hiring_flow,
            "shortlisted_students": shortlisted_students,
            "students_count": len(shortlisted_students) if shortlisted_students else None,
            "deadline": extracted.get("deadline"),
            "links": extracted.get("links"),
        }

    def format_many(
        self,
        notices: Sequence[Notice],
        jobs: Sequence[Job],
    ) -> list[dict[str, Any]]:
        """Format multiple notices."""
        return [self.format_notice(notice, jobs) for notice in notices]

__all__ = [
    "EligibilityMark",
    "Job",
    "Notice",
    "NoticeFormatterGraphNodeMixin",
    "NoticeFormatterHelperMixin",
    "NoticeFormatterService",
    "PostState",
]
