"""LangGraph nodes for email notice extraction."""

import json
import math
import re

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from core import safe_print
from core.llm import message_text
from services.email_notice.models import ExtractedNotice, NoticeGraphState
from services.email_notice.prompts import (
    LIKELY_ON_CAMPUS_PROMPT,
    NOTICE_EXTRACTION_PROMPT,
)
from services.placement_policy import POLICY_EXTRACTION_PROMPT, ExtractedPolicyUpdate


class EmailNoticeGraphMixin:
    """LangGraph workflow and node handlers for email notices."""

    def _build_graph(self):
        """Build the LangGraph workflow."""
        workflow = StateGraph(NoticeGraphState)

        workflow.add_node("classify", self._classify_email)
        workflow.add_node("extract_notice", self._extract_notice)
        workflow.add_node("validate", self._validate_notice)
        workflow.add_node("find_job_candidates", self._find_on_campus_candidates)
        workflow.add_node("classify_likely_on_campus", self._classify_likely_on_campus)
        workflow.add_node("display_results", self._display_results)

        workflow.set_entry_point("classify")

        workflow.add_conditional_edges("classify", self._decide_to_extract)
        workflow.add_conditional_edges("extract_notice", self._should_retry)
        workflow.add_conditional_edges(
            "validate",
            self._decide_to_match_job,
            {
                "find_job_candidates": "find_job_candidates",
                "display_results": "display_results",
            },
        )
        workflow.add_edge("find_job_candidates", "classify_likely_on_campus")
        workflow.add_edge("classify_likely_on_campus", "display_results")
        workflow.add_edge("display_results", END)

        return workflow.compile()

    def _classify_email(self, state: NoticeGraphState) -> NoticeGraphState:
        """Reject only obvious non-notice mail before authoritative extraction."""
        safe_print("--- Notice Classification ---")
        email_data = state["email"]
        text = f"{email_data.get('subject', '')} {email_data.get('body', '')}".casefold()
        notice_terms = (
            "placement",
            "internship",
            "job",
            "shortlist",
            "interview",
            "hackathon",
            "webinar",
            "workshop",
            "notice",
            "deadline",
            "policy",
            "noc",
            "campus",
            "register",
        )
        irrelevant_terms = (
            "security alert",
            "password reset",
            "verify your account",
            "one-time password",
            "promotional offer",
        )
        has_notice_signal = any(term in text for term in notice_terms)
        has_irrelevant_signal = any(term in text for term in irrelevant_terms)
        is_relevant = not has_irrelevant_signal or has_notice_signal

        if not is_relevant:
            confidence = 0.9
            reason = "Obvious account-security or promotional email"
        elif has_notice_signal:
            confidence = 0.75
            reason = "Contains notice-related terms; extraction remains authoritative"
        else:
            confidence = 0.5
            reason = "No obvious spam signal; deferred to authoritative extraction"

        return {
            **state,
            "is_relevant": is_relevant,
            "confidence_score": confidence,
            "classification_reason": reason,
            "retry_count": 0,
        }

    def _extract_notice(self, state: NoticeGraphState) -> NoticeGraphState:
        """Extract structured notice information with the LLM."""
        safe_print("--- Notice Extraction ---")
        email_data = state["email"]
        retry_count = state.get("retry_count", 0) or 0

        chain = NOTICE_EXTRACTION_PROMPT | self.llm

        try:
            response = chain.invoke(
                {
                    "subject": email_data.get("subject", ""),
                    "body": email_data.get("body", ""),
                }
            )

            json_content = self._extract_json(message_text(response))
            data = json.loads(json_content)

            if data.get("is_policy_update"):
                safe_print(
                    "Detected placement policy update - Running advanced extraction..."
                )
                return self._extract_policy_update(state, data)

            if not data.get("is_notice", False):
                rejection_reason = data.get(
                    "rejection_reason", "LLM determined this is not a valid notice"
                )
                safe_print("Email rejected by notice extraction")
                return {
                    **state,
                    "extracted_notice": None,
                    "rejection_reason": rejection_reason,
                }

            notice = ExtractedNotice(**data)
            safe_print("Notice fields extracted")

            return {
                **state,
                "extracted_notice": notice,
                "validation_errors": None,
                "rejection_reason": None,
            }

        except (ValidationError, json.JSONDecodeError) as e:
            error_msg = (
                f"Extracted notice failed {len(e.errors())} validation checks"
                if isinstance(e, ValidationError)
                else "Notice extraction returned malformed JSON"
            )
            safe_print(error_msg)

            if retry_count < 2:
                return {
                    **state,
                    "validation_errors": [error_msg],
                    "retry_count": retry_count + 1,
                }

            return {
                **state,
                "extracted_notice": None,
                "validation_errors": [error_msg],
            }

    def _extract_policy_update(
        self, state: NoticeGraphState, data: dict
    ) -> NoticeGraphState:
        """Run the specialized policy update extraction pass."""
        email_data = state["email"]
        policy_chain = POLICY_EXTRACTION_PROMPT | self.llm
        email_content = (
            f"Subject: {email_data.get('subject', '')}\n"
            f"From: {email_data.get('sender', '')}\n"
            f"Date: {email_data.get('time_sent', '')}\n\n"
            f"{email_data.get('body', '')}"
        )

        policy_response = policy_chain.invoke({"email_content": email_content})
        policy_json = self._extract_json(message_text(policy_response))
        policy_docs = json.loads(policy_json)

        if isinstance(policy_docs, list) and len(policy_docs) > 0:
            policy_doc = policy_docs[0]
            extracted_year = None
            year_match = re.search(r"20\d{2}", policy_doc.get("slug") or "")
            if not year_match:
                year_match = re.search(r"20\d{2}", policy_doc.get("badge") or "")
            if year_match:
                extracted_year = int(year_match.group(0))

            policy_data = {
                "is_policy_update": True,
                "year": extracted_year,
                "title": policy_doc.get("title"),
                "content": policy_doc.get("content"),
                "update_date": (policy_doc.get("updatedDates") or [None])[0],
                "summary": policy_doc.get("description"),
            }
            rejection_reason = "Policy update handled separately"
        else:
            safe_print(
                "Advanced policy extraction failed to return a list, falling back to basic."
            )
            policy_data = {
                "is_policy_update": True,
                "year": data.get("year"),
                "title": data.get("title"),
                "content": data.get("content"),
                "update_date": data.get("update_date"),
                "summary": data.get("summary"),
            }
            rejection_reason = "Policy update handled separately (basic fallback)"

        policy_extract = ExtractedPolicyUpdate(**policy_data)
        return {
            **state,
            "is_policy_update": True,
            "extracted_policy": policy_extract,
            "rejection_reason": rejection_reason,
        }

    def _validate_notice(self, state: NoticeGraphState) -> NoticeGraphState:
        """Validate extracted notice basics."""
        notice = state.get("extracted_notice")

        if not notice:
            return state

        issues = []
        if not notice.title or len(notice.title) < 3:
            issues.append("Title too short")
        if not notice.content or len(notice.content) < 10:
            issues.append("Content too short")
        if not notice.type:
            issues.append("Missing notice type")

        if issues:
            safe_print(f"Validation issues: {issues}")
            return {**state, "validation_errors": issues}

        safe_print("Notice validated successfully")
        return {**state, "validation_errors": None}

    def _display_results(self, state: NoticeGraphState) -> NoticeGraphState:
        """Display extraction results."""
        notice = state.get("extracted_notice")
        rejection = state.get("rejection_reason")

        safe_print("=" * 50)
        if rejection:
            safe_print("Email was not accepted as a notice")
        elif notice:
            safe_print("Valid notice extracted")
        else:
            safe_print("No valid notice extracted")
        safe_print("=" * 50)

        return state

    def _find_on_campus_candidates(
        self, state: NoticeGraphState
    ) -> NoticeGraphState:
        """Find plausible year-scoped jobs for a validated email notice."""
        notice = state.get("extracted_notice")
        if not notice:
            return {**state, "job_candidates": []}
        try:
            candidates = self._find_job_candidates(notice)
        except Exception:
            self.logger.exception("Failed to build likely-on-campus candidates")
            candidates = []
        return {**state, "job_candidates": candidates}

    def _classify_likely_on_campus(
        self, state: NoticeGraphState
    ) -> NoticeGraphState:
        """Ask the LLM whether the notice likely matches a campus job."""
        notice = state.get("extracted_notice")
        candidates = state.get("job_candidates") or []
        if not notice or not candidates:
            return {
                **state,
                "likely_on_campus": False,
                "on_campus_confidence": None,
                "selected_job": None,
            }

        email_data = state["email"]
        candidate_by_id = {str(candidate["id"]): candidate for candidate in candidates}
        chain = LIKELY_ON_CAMPUS_PROMPT | self.llm
        try:
            response = chain.invoke(
                {
                    "subject": email_data.get("subject", ""),
                    "body": email_data.get("body", "")[:6000],
                    "notice": json.dumps(notice.model_dump(), default=str),
                    "candidates": json.dumps(candidates, default=str),
                }
            )
            data = json.loads(self._extract_json(message_text(response)))
            confidence = float(data.get("confidence", 0))
            if not math.isfinite(confidence):
                raise ValueError("confidence must be finite")
            confidence = min(1.0, max(0.0, confidence))
            selected_job = candidate_by_id.get(str(data.get("best_job_id") or ""))
            model_likely = data.get("likely_on_campus") is True
            if model_likely and selected_job is None:
                raise ValueError("likely result must select a supplied job id")
            likely = model_likely and selected_job is not None
            likely = likely and confidence >= self.likely_on_campus_min_confidence
            return {
                **state,
                "likely_on_campus": likely,
                "on_campus_confidence": confidence,
                "selected_job": selected_job if likely else None,
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            self.logger.warning(
                "Likely-on-campus classifier returned invalid output", exc_info=True
            )
        except Exception:
            self.logger.exception("Likely-on-campus classifier failed")

        return {
            **state,
            "likely_on_campus": False,
            "on_campus_confidence": None,
            "selected_job": None,
        }

    def _decide_to_extract(self, state: NoticeGraphState) -> str:
        """Decide whether to proceed with extraction."""
        if state.get("is_relevant", False):
            return "extract_notice"
        return "display_results"

    def _should_retry(self, state: NoticeGraphState) -> str:
        """Determine if extraction should be retried."""
        errors = state.get("validation_errors")
        retry_count = state.get("retry_count", 0) or 0
        notice = state.get("extracted_notice")

        if not errors or notice is not None or retry_count >= 2:
            return "validate"
        return "extract_notice"

    @staticmethod
    def _decide_to_match_job(state: NoticeGraphState) -> str:
        """Run campus matching only for a valid extracted notice."""
        if state.get("extracted_notice") and not state.get("validation_errors"):
            return "find_job_candidates"
        return "display_results"

    @staticmethod
    def _extract_json(response_content: str) -> str:
        """Extract JSON from an LLM response."""
        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        match = re.search(json_pattern, response_content)
        return match.group(1).strip() if match else response_content.strip()
