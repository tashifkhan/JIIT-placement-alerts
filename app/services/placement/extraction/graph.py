"""LangGraph pipeline nodes for placement offer extraction."""

import json
import re
from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from core.config import safe_print
from core.llm import message_text
from services.placement.extraction.constants import (
    COMPANY_INDICATORS,
    NEGATIVE_KEYWORDS,
    PLACEMENT_KEYWORDS,
)
from services.placement.extraction.email_utils import (
    extract_forwarded_date,
    extract_forwarded_sender,
    extract_json_from_response,
    strip_headers_and_forwarded_markers,
)
from services.placement.extraction.models import GraphState, PlacementOffer
from services.campus_match import find_job_candidates, parse_campus_decision
from services.placement.extraction.prompts import (
    EXTRACTION_PROMPT,
    OFFER_ON_CAMPUS_PROMPT,
)


class PlacementGraphMixin:
    """LangGraph workflow and node implementations."""

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow."""
        workflow = StateGraph(GraphState)

        workflow.add_node("classify", self._classify_email)
        workflow.add_node("extract_info", self._extract_info)
        workflow.add_node("validate_and_enhance", self._validate_and_enhance)
        workflow.add_node("sanitize_privacy", self._sanitize_privacy)
        workflow.add_node("classify_on_campus", self._classify_on_campus)
        workflow.add_node("display_results", self._display_results)

        workflow.set_entry_point("classify")

        workflow.add_conditional_edges("classify", self._decide_to_extract)
        workflow.add_conditional_edges("extract_info", self._should_retry_extraction)
        workflow.add_edge("validate_and_enhance", "sanitize_privacy")
        workflow.add_edge("sanitize_privacy", "classify_on_campus")
        workflow.add_edge("classify_on_campus", "display_results")
        workflow.add_edge("display_results", END)

        return workflow.compile()

    def _classify_email(self, state: GraphState) -> GraphState:
        """Classify whether an email is likely placement-related."""
        safe_print("--- Step 1: Intelligent Email Classification ---")
        email_data = state["email"]

        sanitized_body = strip_headers_and_forwarded_markers(email_data.get("body", ""))
        full_text = (
            email_data.get("sender", "").lower()
            + " "
            + email_data.get("subject", "").lower()
            + " "
            + sanitized_body.lower()
        )

        placement_score = sum(
            1 for keyword in PLACEMENT_KEYWORDS if keyword in full_text
        )
        company_score = sum(1 for keyword in COMPANY_INDICATORS if keyword in full_text)
        negative_score = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in full_text)

        has_student_names = bool(
            re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", email_data.get("body", ""))
        )
        has_numbers = bool(re.search(r"\d+", email_data.get("body", "")))
        has_email_format = bool(
            re.search(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                email_data.get("body", ""),
            )
        )

        security_indicators = [
            "security alert",
            "suspicious activity",
            "login attempt",
            "password",
            "verify",
            "account",
        ]
        has_security_indicators = any(
            indicator in full_text for indicator in security_indicators
        )

        confidence = 0.0
        reasons = []

        if placement_score > 0:
            confidence += min(placement_score * 0.3, 0.6)
            reasons.append(f"Contains {placement_score} placement-related keywords")

        if company_score > 0:
            confidence += min(company_score * 0.1, 0.2)
            reasons.append(f"Contains {company_score} company indicators")

        if has_student_names:
            confidence += 0.2
            reasons.append("Contains potential student names")

        if has_numbers:
            confidence += 0.1
            reasons.append("Contains numerical data")

        if has_email_format:
            confidence += 0.1
            reasons.append("Contains email addresses")

        if negative_score > 0:
            confidence -= negative_score * 0.2
            reasons.append(f"Contains {negative_score} spam indicators")

        if has_security_indicators:
            confidence -= 0.4
            reasons.append("Contains security/alert indicators")

        is_relevant = confidence >= 0.6
        classification_reason = (
            "; ".join(reasons) if reasons else "No clear indicators found"
        )

        safe_print(f"Confidence Score: {confidence:.2f}")
        safe_print(f"Classification: {'RELEVANT' if is_relevant else 'NOT RELEVANT'}")

        return {
            **state,
            "is_relevant": is_relevant,
            "confidence_score": confidence,
            "classification_reason": classification_reason,
            "retry_count": 0,
        }

    def _extract_info(self, state: GraphState) -> GraphState:
        """Extract placement offer details with the LLM."""
        safe_print("\n--- Step 2: Robust Information Extraction ---")
        email_data = state["email"]
        retry_count = state.get("retry_count", 0) or 0
        max_retries = 3

        chain = EXTRACTION_PROMPT | self.llm

        try:
            response = chain.invoke(
                {
                    "subject": email_data["subject"],
                    "body": strip_headers_and_forwarded_markers(email_data["body"]),
                }
            )

            json_content = extract_json_from_response(message_text(response))
            data = json.loads(json_content)

            if not data or len(data) == 0:
                safe_print(
                    "LLM returned an empty response; treating as non-placement offer."
                )
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": None,
                    "rejection_reason": "LLM returned empty response",
                }

            if data.get("is_final_placement_offer") is False:
                rejection_reason = data.get(
                    "rejection_reason",
                    "LLM indicated this is not a final placement offer.",
                )
                safe_print("LLM determined this email is not a final placement offer.")
                return {
                    **state,
                    "extracted_offer": None,
                    "validation_errors": None,
                    "rejection_reason": rejection_reason,
                }

            offer = PlacementOffer(**data)
            offer.email_subject = email_data["subject"]
            forwarded_sender = extract_forwarded_sender(email_data.get("body", ""))
            offer.email_sender = forwarded_sender or email_data.get("sender")
            offer.time_sent = email_data.get("time_sent") or extract_forwarded_date(
                email_data.get("body", "")
            )
            offer.created_at = offer.time_sent

            safe_print("Information extracted and validated successfully.")
            return {
                **state,
                "extracted_offer": offer,
                "validation_errors": None,
                "rejection_reason": None,
            }

        except ValidationError as e:
            error_messages = [
                f"Invalid extracted field: {'.'.join(str(part) for part in err['loc'])}"
                for err in e.errors()
            ]
            safe_print(f"Placement extraction failed {len(error_messages)} validation checks")

            if retry_count < max_retries:
                safe_print(
                    f"Retrying extraction (attempt {retry_count + 1}/{max_retries})"
                )
                return {
                    **state,
                    "validation_errors": error_messages,
                    "retry_count": retry_count + 1,
                }

            safe_print("Max retries reached. Extraction failed.")
            return {
                **state,
                "extracted_offer": None,
                "validation_errors": error_messages,
            }

        except json.JSONDecodeError:
            error_msg = "Placement extraction returned malformed JSON"
            safe_print(error_msg)

            if retry_count < max_retries:
                safe_print(
                    f"Retrying extraction (attempt {retry_count + 1}/{max_retries})"
                )
                return {
                    **state,
                    "validation_errors": [error_msg],
                    "retry_count": retry_count + 1,
                    "rejection_reason": state.get("rejection_reason"),
                }

            return {
                **state,
                "extracted_offer": None,
                "validation_errors": [error_msg],
                "rejection_reason": state.get("rejection_reason"),
            }

    def _validate_and_enhance(self, state: GraphState) -> GraphState:
        """Validate and enrich extracted offer fields."""
        safe_print("\n--- Step 3: Validation and Enhancement ---")
        offer = state.get("extracted_offer")

        if not offer:
            safe_print("No offer to validate - skipping validation step.")
            return {**state, "validation_errors": None}

        validation_issues = []

        if not offer.company or len(offer.company.strip()) < 2:
            validation_issues.append("Company name is too short or missing")

        if not offer.students_selected or len(offer.students_selected) == 0:
            validation_issues.append("No students listed in the offer")

        if offer.number_of_offers != len(offer.students_selected):
            safe_print(
                f"Adjusting number_of_offers from {offer.number_of_offers} to {len(offer.students_selected)}"
            )
            offer.number_of_offers = len(offer.students_selected)

        if not offer.roles or len(offer.roles) == 0:
            validation_issues.append("No role information found")
        else:
            role_packages = {role.role: role.package for role in offer.roles if role.role}
            if len(offer.roles) == 1:
                default_role = offer.roles[0].role
                default_package = offer.roles[0].package

                for student in offer.students_selected:
                    if not student.role:
                        student.role = default_role

                    if not student.package and default_package:
                        student.package = default_package

            for student in offer.students_selected:
                if student.role and not student.package and role_packages.get(student.role):
                    student.package = role_packages.get(student.role)

        default_location = ", ".join(offer.job_location) if offer.job_location else None
        for student in offer.students_selected:
            if not student.location and default_location:
                student.location = default_location
            if not student.joining_date and offer.joining_date:
                student.joining_date = offer.joining_date

        if validation_issues:
            safe_print(f"Validation issues found: {validation_issues}")
            return {**state, "validation_errors": validation_issues}

        safe_print("Validation passed successfully.")
        return {**state, "validation_errors": None}

    def _sanitize_privacy(self, state: GraphState) -> GraphState:
        """Sanitize extracted offer fields before display/storage."""
        offer = state.get("extracted_offer")
        if not offer:
            return state

        changed = False

        if offer.additional_info:
            cleaned = strip_headers_and_forwarded_markers(offer.additional_info)
            if cleaned != offer.additional_info:
                offer.additional_info = cleaned
                changed = True

        if offer.roles:
            for role_package in offer.roles:
                if role_package.package_details:
                    cleaned = strip_headers_and_forwarded_markers(
                        role_package.package_details
                    )
                    if cleaned != role_package.package_details:
                        role_package.package_details = cleaned
                        changed = True

        if offer.job_location:
            new_locations = []
            for location in offer.job_location:
                cleaned = strip_headers_and_forwarded_markers(location)
                new_locations.append(cleaned)
                if cleaned != location:
                    changed = True
            offer.job_location = new_locations

        if changed:
            safe_print("Privacy sanitization applied to extracted offer.")
        return {**state, "extracted_offer": offer}

    def _classify_on_campus(self, state: GraphState) -> GraphState:
        """Tag the offer as likely on campus when it matches a year-scoped drive.

        Runs after privacy sanitization and sends the judge only company, roles,
        location and the subject line. Student rows never reach this call.
        Any failure leaves the tag off rather than blocking the offer.
        """
        offer = state.get("extracted_offer")
        if not offer:
            return state

        offer.likely_on_campus = False
        offer.on_campus_confidence = None
        role = " / ".join(r.role for r in offer.roles if r.role)
        try:
            candidates = find_job_candidates(self._get_jobs(), offer.company, role)
        except Exception:
            self.logger.exception("Failed to build on-campus candidates for offer")
            return {**state, "extracted_offer": offer}
        if not candidates:
            return {**state, "extracted_offer": offer}

        offer_summary = {
            "company": offer.company,
            "roles": [r.model_dump() for r in offer.roles],
            "job_location": offer.job_location,
            "number_of_offers": offer.number_of_offers,
        }
        chain = OFFER_ON_CAMPUS_PROMPT | self.llm
        try:
            response = chain.invoke(
                {
                    "subject": state["email"].get("subject", ""),
                    "offer": json.dumps(offer_summary, default=str),
                    "candidates": json.dumps(candidates, default=str),
                }
            )
            likely, confidence, _ = parse_campus_decision(
                message_text(response),
                candidates,
                self.likely_on_campus_min_confidence,
            )
            offer.likely_on_campus = likely
            offer.on_campus_confidence = confidence
        except (TypeError, ValueError, json.JSONDecodeError):
            self.logger.warning("Offer on-campus judge returned invalid output", exc_info=True)
        except Exception:
            self.logger.exception("Offer on-campus judge failed")
        return {**state, "extracted_offer": offer}

    def _display_results(self, state: GraphState) -> GraphState:
        """Display placement extraction results."""
        safe_print("\n--- Step 4: Enhanced Results Display ---")
        offer = state.get("extracted_offer")
        confidence = state.get("confidence_score", 0.0) or 0.0
        rejection_reason = state.get("rejection_reason")

        safe_print("=" * 60)
        safe_print("    PLACEMENT EXTRACTION RESULTS")
        safe_print("=" * 60)
        safe_print(f"Classification Confidence: {confidence:.2f}")

        if rejection_reason:
            safe_print("Email rejected by placement extraction")

        if not offer:
            safe_print("No valid placement information could be extracted.")
        else:
            safe_print("Placement offer extracted successfully")
            safe_print(f"Students: {offer.number_of_offers}")
            safe_print(f"Roles: {len(offer.roles)}")

        safe_print("=" * 60 + "\n")
        return state

    def _decide_to_extract(self, state: GraphState) -> str:
        """Decide whether to proceed with LLM extraction."""
        is_relevant = state.get("is_relevant", False)
        confidence = state.get("confidence_score", 0.0) or 0.0

        if is_relevant and confidence >= 0.6:
            return "extract_info"

        safe_print(
            f"Skipping extraction - Relevant: {is_relevant}, Confidence: {confidence:.2f}"
        )
        return "display_results"

    def _should_retry_extraction(self, state: GraphState) -> str:
        """Determine whether extraction should be retried."""
        validation_errors = state.get("validation_errors", [])
        retry_count = state.get("retry_count", 0) or 0
        max_retries = 3
        extracted_offer = state.get("extracted_offer")

        if (
            not validation_errors
            or extracted_offer is not None
            or retry_count >= max_retries
            or validation_errors is None
        ):
            return "validate_and_enhance"

        return "extract_info"
