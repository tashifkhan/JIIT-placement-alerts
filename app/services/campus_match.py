"""Match placement records to year-scoped campus jobs.

Two stages. A lexical ranker narrows the Jobs collection to at most eight
plausible drives by company and role, then an LLM picks one. This module owns
the ranker and the checks applied to the LLM's answer, so notice job linking
and the placement-offer on-campus tag make the same decision the same way.
"""

import json
import math
import re
from typing import Any

from rapidfuzz import fuzz

_ACRONYM_IGNORED = {
    "and",
    "company",
    "corporation",
    "global",
    "group",
    "india",
    "limited",
    "llc",
    "llp",
    "of",
    "private",
    "pvt",
    "the",
}


def company_acronym(value: str) -> str:
    """Build a conservative acronym from a company name."""
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if word not in _ACRONYM_IGNORED
    ]
    return "".join(word[0] for word in words).upper() if len(words) > 1 else ""


def find_job_candidates(
    jobs: list[dict[str, Any]],
    company: str | None,
    role: str | None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Rank jobs by company and role text for the LLM judge."""
    company = " ".join((company or "").split())
    role = " ".join((role or "").split())
    if not company and not role:
        return []

    candidates: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("id") or job.get("_id") or "")
        job_company = " ".join(str(job.get("company") or "").split())
        job_role = " ".join(str(job.get("job_profile") or "").split())
        if not job_id or not job_company:
            continue

        company_score = 0.0
        acronym_match = False
        if company:
            company_score = fuzz.WRatio(company, job_company) / 100
            company_token = re.sub(r"[^A-Za-z0-9]", "", company).upper()
            acronym_match = (
                len(company_token) >= 2
                and company_token == company_acronym(job_company)
            )
            if acronym_match:
                company_score = 1.0

        role_score = fuzz.WRatio(role, job_role) / 100 if role and job_role else 0.0
        if company and role:
            rank_score = 0.6 * company_score + 0.4 * role_score
            eligible = company_score >= 0.55 or acronym_match
        elif company:
            rank_score = company_score
            eligible = company_score >= 0.55 or acronym_match
        else:
            rank_score = role_score
            eligible = role_score >= 0.7

        if not eligible:
            continue
        candidates.append(
            {
                "id": job_id,
                "company": job_company,
                "job_profile": job_role,
                "location": job.get("location"),
                "package": job.get("package"),
                "annum_months": job.get("annum_months"),
                "package_info": job.get("package_info"),
                "deadline": job.get("deadline"),
                "placement_type": job.get("placement_type"),
                "company_score": round(company_score, 4),
                "role_score": round(role_score, 4),
                "rank_score": round(rank_score, 4),
                "acronym_match": acronym_match,
            }
        )

    candidates.sort(key=lambda item: item["rank_score"], reverse=True)
    return candidates[:limit]


def extract_json(response_content: str) -> str:
    """Strip a Markdown code fence from an LLM response if there is one."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_content)
    return match.group(1).strip() if match else response_content.strip()


def parse_campus_decision(
    response_content: str,
    candidates: list[dict[str, Any]],
    min_confidence: float,
) -> tuple[bool, float, dict[str, Any] | None]:
    """Validate the judge's JSON and apply the confidence threshold.

    Returns (likely, confidence, selected_job). The job is only returned when
    the match passes. Raises ValueError, TypeError or JSONDecodeError on output
    that cannot be trusted, so callers can treat any of those as "no tag".
    """
    candidate_by_id = {str(candidate["id"]): candidate for candidate in candidates}
    # Models sometimes follow the object with a sentence or a second copy.
    # Decode the first object and ignore whatever trails it.
    text = extract_json(response_content)
    start = text.find("{")
    if start < 0:
        raise ValueError("response has no JSON object")
    data, _ = json.JSONDecoder().raw_decode(text, start)
    if not isinstance(data, dict):
        raise ValueError("response JSON is not an object")

    confidence = float(data.get("confidence", 0))
    if not math.isfinite(confidence):
        raise ValueError("confidence must be finite")
    confidence = min(1.0, max(0.0, confidence))

    selected_job = candidate_by_id.get(str(data.get("best_job_id") or ""))
    model_likely = data.get("likely_on_campus") is True
    if model_likely and selected_job is None:
        raise ValueError("likely result must select a supplied job id")

    likely = model_likely and selected_job is not None and confidence >= min_confidence
    return likely, confidence, selected_job if likely else None
