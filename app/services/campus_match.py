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

from rapidfuzz import fuzz, utils

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


# Words that say what kind of entity a company is, not which one. Scoring on
# them makes every "X India Pvt Ltd" look like every other one.
_GENERIC_COMPANY_WORDS = _ACRONYM_IGNORED | {
    "co",
    "corp",
    "inc",
    "incorporated",
    "ltd",
    "plc",
    "solutions",
    "services",
    "software",
    "systems",
    "technologies",
    "technology",
    "tech",
    "labs",
    "holdings",
    "consulting",
}

_SHORT_NAME = 4


def company_names(value: str) -> list[str]:
    """Distinctive name forms for scoring.

    "JTG (Josh Technology Group)" gives both "jtg" and "josh" since either side
    of the bracket can be the brand. Generic words are dropped, falling back to
    the full name when nothing else is left ("Global Services" stays whole).
    """
    names = [re.sub(r"\(.*?\)", " ", value)]
    for inner in re.findall(r"\(([^)]+)\)", value):
        names.append(re.sub(r"^(formerly|previously)\s+", "", inner, flags=re.I))
    out = []
    for name in names:
        words = re.findall(r"[a-z0-9]+", name.casefold())
        core = [word for word in words if word not in _GENERIC_COMPANY_WORDS]
        text = " ".join(core or words)
        if text and text not in out:
            out.append(text)
    return out


def company_similarity(left: str, right: str) -> float:
    """Best 0..1 score between any name forms of two companies.

    Short names such as "EY" or "GS" only count on an exact word match, since
    a partial match would find them inside "Keyence" or "Signals".
    """
    best = 0.0
    for a in company_names(left):
        for b in company_names(right):
            if min(len(a), len(b)) < _SHORT_NAME:
                shorter, longer = sorted((a, b), key=len)
                score = 1.0 if shorter in longer.split() else fuzz.ratio(a, b) / 100
            else:
                score = fuzz.WRatio(a, b) / 100
            best = max(best, score)
    # "TotheNew" and "To The New" differ only in spacing.
    squash = lambda text: re.sub(r"[^a-z0-9]", "", text.casefold())  # noqa: E731
    if squash(left) and squash(left) == squash(right):
        return 1.0
    return best


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
            company_score = company_similarity(company, job_company)
            company_token = re.sub(r"[^A-Za-z0-9]", "", company).upper()
            acronym_match = (
                len(company_token) >= 2
                and company_token == company_acronym(job_company)
            )
            if acronym_match:
                company_score = 1.0

        role_score = fuzz.WRatio(role, job_role, processor=utils.default_process) / 100 if role and job_role else 0.0
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
    verdict = parse_campus_verdict(response_content, candidates, min_confidence)
    return verdict["likely"], verdict["confidence"], verdict["job"]


def parse_campus_verdict(
    response_content: str,
    candidates: list[dict[str, Any]],
    min_confidence: float,
) -> dict[str, Any]:
    """Like parse_campus_decision, plus the judge's stated reason.

    Keys: likely, confidence, job, job_id (the judge's pick even when it fell
    under the threshold), reason, signals, pre_placement_offer. Reason and
    signals are trimmed so a rambling model cannot bloat the document.
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
    reason = data.get("reason")
    signals = data.get("signals")
    return {
        "likely": likely,
        "confidence": confidence,
        "job": selected_job if likely else None,
        "job_id": str(selected_job["id"]) if selected_job else None,
        "reason": " ".join(str(reason).split())[:500] if reason else None,
        "signals": [str(item)[:80] for item in signals[:8]]
        if isinstance(signals, list)
        else [],
        "pre_placement_offer": data.get("pre_placement_offer") is True,
    }
