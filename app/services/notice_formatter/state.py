"""Shared state and type exports for notice formatting."""

from typing import Any, Required, TypedDict

from clients.superset_client import EligibilityMark, Job, Notice


class PostState(TypedDict, total=False):
    """LangGraph state for SuperSet notice formatting."""

    notice: Required[Notice]
    jobs: Required[list[Job]]
    job_enricher: Any | None

    id: str
    raw_text: str
    category: str
    matched_job: Job | None
    matched_job_id: str | None
    job_location: str | None
    extracted: dict[str, Any]


__all__ = ["EligibilityMark", "Job", "Notice", "PostState"]
