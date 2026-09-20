"""Shared state and type exports for notice formatting."""

from typing import Any, Dict, List, Optional, Required, TypedDict

from clients.superset_client import EligibilityMark, Job, Notice


class PostState(TypedDict, total=False):
    """LangGraph state for SuperSet notice formatting."""

    notice: Required[Notice]
    jobs: Required[List[Job]]
    job_enricher: Optional[Any]

    id: str
    raw_text: str
    category: str
    matched_job: Optional[Job]
    matched_job_id: Optional[str]
    job_location: Optional[str]
    extracted: Dict[str, Any]


__all__ = ["EligibilityMark", "Job", "Notice", "PostState"]
