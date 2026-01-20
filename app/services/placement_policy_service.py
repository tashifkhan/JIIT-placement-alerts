"""
Placement Policy Service

Service for managing placement policies stored as Markdown in MongoDB.
Handles policy CRUD operations, TOC generation, and year extraction.
"""

import re
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from pydantic import BaseModel, Field

from core.config import safe_print, get_settings


# ============================================================================
# Pydantic Models
# ============================================================================


class TOCItem(BaseModel):
    """Table of Contents item"""

    id: str = Field(..., description="URL-friendly heading ID (github-slugger style)")
    text: str = Field(..., description="Heading text")
    level: int = Field(..., description="Heading level (2 for h2, 3 for h3)")


class PolicyDocument(BaseModel):
    """Policy document for MongoDB storage"""

    slug: str = Field(..., description="URL-friendly policy identifier")
    title: str = Field(default="Placement Policy", description="Policy title")
    description: str = Field(default="", description="Brief policy description")
    badge: str = Field(default="", description="Badge text for UI display")
    year: int = Field(..., description="Graduating batch year this policy addresses")
    updatedDates: List[str] = Field(
        default_factory=list, description="List of update dates (ISO format)"
    )
    published: bool = Field(default=True, description="Whether policy is published")
    contentFormat: str = Field(default="markdown", description="Content format")
    content: str = Field(..., description="Full Markdown content")
    toc: List[TOCItem] = Field(
        default_factory=list, description="Generated table of contents"
    )
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)


class ExtractedPolicyUpdate(BaseModel):
    """Extracted policy update data from email"""

    is_policy_update: bool = Field(
        default=False, description="Whether this is a policy update"
    )
    year: Optional[int] = Field(None, description="Graduating batch year")
    title: Optional[str] = Field(None, description="Policy title")
    content: Optional[str] = Field(None, description="Full policy content as Markdown")
    update_date: Optional[str] = Field(
        None, description="Date of this update (ISO format)"
    )
    summary: Optional[str] = Field(None, description="Brief summary of changes")
    sections_updated: Optional[List[str]] = Field(
        None, description="List of sections updated"
    )


# ============================================================================
# Placement Policy Service
# ============================================================================


class PlacementPolicyService:
    """
    Service for managing placement policies.

    Handles:
    - Extracting policy year from content
    - Generating TOC from Markdown headings
    - Creating/updating policies in MongoDB
    - GitHub-style slug generation for heading IDs
    """

    def __init__(
        self,
        db_service: Optional[Any] = None,
        google_api_key: Optional[str] = None,
    ):
        """
        Initialize placement policy service.

        Args:
            db_service: Database service for MongoDB operations
            google_api_key: API key for LLM (for content extraction)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        self.api_key = google_api_key or get_settings().google_api_key

        # Track slugs for uniqueness within a document (github-slugger style)
        self._slug_counts: Dict[str, int] = {}

        self.logger.info("PlacementPolicyService initialized")

    # =========================================================================
    # Slug Generation (GitHub-slugger style)
    # =========================================================================

    def _reset_slug_counts(self) -> None:
        """Reset slug counts for a new document"""
        self._slug_counts = {}

    def _generate_heading_slug(self, text: str) -> str:
        """
        Generate GitHub-style slug from heading text.

        Matches the algorithm used by github-slugger:
        - Convert to lowercase
        - Remove punctuation except hyphens and spaces
        - Replace spaces with hyphens
        - Handle duplicates with -1, -2, etc. suffixes
        """
        # Lowercase and strip
        slug = text.lower().strip()

        # Remove special characters except alphanumeric, spaces, and hyphens
        slug = re.sub(r"[^\w\s-]", "", slug)

        # Replace spaces and multiple hyphens with single hyphen
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)

        # Remove leading/trailing hyphens
        slug = slug.strip("-")

        # Handle duplicates
        base_slug = slug
        if base_slug in self._slug_counts:
            self._slug_counts[base_slug] += 1
            slug = f"{base_slug}-{self._slug_counts[base_slug]}"
        else:
            self._slug_counts[base_slug] = 0

        return slug

    def generate_policy_slug(self, title: str, year: int) -> str:
        """Generate URL-friendly slug for policy"""
        base = title.lower().replace(" ", "-")
        base = re.sub(r"[^a-z0-9-]", "", base)
        return f"{base}-{year}"

    # =========================================================================
    # TOC Generation
    # =========================================================================

    def generate_toc(self, markdown: str) -> List[TOCItem]:
        """
        Generate table of contents from Markdown headings.

        Extracts h2 (##) and h3 (###) headings and creates TOC items
        with GitHub-style slugs for IDs.

        Args:
            markdown: Markdown content

        Returns:
            List of TOCItem objects
        """
        self._reset_slug_counts()
        toc: List[TOCItem] = []

        # Match ## and ### headings (not inside code blocks)
        # Simple approach: split by lines and check each
        lines = markdown.split("\n")
        in_code_block = False

        for line in lines:
            # Toggle code block state
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            # Check for headings
            h3_match = re.match(r"^###\s+(.+?)(?:\s*\{#[\w-]+\})?\s*$", line)
            h2_match = re.match(r"^##\s+(.+?)(?:\s*\{#[\w-]+\})?\s*$", line)

            if h3_match:
                text = h3_match.group(1).strip()
                toc.append(
                    TOCItem(id=self._generate_heading_slug(text), text=text, level=3)
                )
            elif h2_match:
                text = h2_match.group(1).strip()
                toc.append(
                    TOCItem(id=self._generate_heading_slug(text), text=text, level=2)
                )

        return toc

    # =========================================================================
    # Year Extraction
    # =========================================================================

    def extract_policy_year(self, content: str) -> Optional[int]:
        """
        Extract graduating batch year from policy content.

        Looks for patterns like:
        - "2026 Graduating Batches"
        - "Placement Policy 2026"
        - "batch of 2026"
        - "Passing Out 2026"

        Args:
            content: Policy content (subject + body)

        Returns:
            Year as integer, or None if not found
        """
        patterns = [
            r"(\d{4})\s*(?:graduating|pass(?:ing)?(?:\s*out)?)\s*batch",
            r"(?:graduating|pass(?:ing)?(?:\s*out)?)\s*batch(?:es)?\s*(?:of\s*)?(\d{4})",
            r"placement\s*policy\s*(\d{4})",
            r"(\d{4})\s*placement\s*policy",
            r"batch\s*(?:of\s*)?(\d{4})",
            r"policy\s*(?:for\s*)?(\d{4})",
        ]

        content_lower = content.lower()

        for pattern in patterns:
            match = re.search(pattern, content_lower, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                # Sanity check: year should be reasonable (2020-2040)
                if 2020 <= year <= 2040:
                    self.logger.info(f"Extracted policy year: {year}")
                    return year

        self.logger.warning("Could not extract year from policy content")
        return None

    # =========================================================================
    # Policy Update Date Extraction
    # =========================================================================

    def extract_update_date(self, content: str) -> Optional[str]:
        """
        Extract the update date from policy content.

        Args:
            content: Policy content

        Returns:
            ISO format date string or None
        """
        # Common date patterns
        patterns = [
            # "February 8, 2025" or "Feb 8, 2025"
            r"((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})",
            # "8 February 2025" or "8 Feb 2025"
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})",
            # "2025-02-08" or "2025/02/08"
            r"(\d{4}[-/]\d{2}[-/]\d{2})",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                try:
                    # Try to parse and convert to ISO format
                    from dateutil import parser

                    dt = parser.parse(date_str)
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    # Return as-is if parsing fails
                    return date_str

        return None

    # =========================================================================
    # Policy CRUD Operations
    # =========================================================================

    def get_policy_by_year(self, year: int) -> Optional[PolicyDocument]:
        """
        Get policy document by year.

        Args:
            year: Graduating batch year

        Returns:
            PolicyDocument or None
        """
        if not self.db_service:
            self.logger.warning("No database service configured")
            return None

        doc = self.db_service.get_policy_by_year(year)
        if doc:
            # Convert MongoDB doc to PolicyDocument
            doc.pop("_id", None)
            return PolicyDocument(**doc)
        return None

    def create_policy(
        self,
        year: int,
        content: str,
        title: str = "Placement Policy",
        description: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Create a new policy document.

        Args:
            year: Graduating batch year
            content: Markdown content
            title: Policy title
            description: Optional description

        Returns:
            Tuple of (success, message/id)
        """
        if not self.db_service:
            return False, "No database service configured"

        now = datetime.utcnow()
        update_date = now.strftime("%Y-%m-%d")

        policy = PolicyDocument(
            slug=self.generate_policy_slug(title, year),
            title=title,
            description=description or f"{title} ({year} Graduating Batches)",
            badge=f"{title.upper()} {year}",
            year=year,
            updatedDates=[update_date],
            published=True,
            contentFormat="markdown",
            content=content,
            toc=self.generate_toc(content),
            createdAt=now,
            updatedAt=now,
        )

        return self.db_service.upsert_policy(policy.model_dump())

    def update_policy(
        self,
        year: int,
        new_content: str,
        merge_strategy: str = "replace",
    ) -> Tuple[bool, str]:
        """
        Update an existing policy.

        Args:
            year: Graduating batch year
            new_content: New Markdown content
            merge_strategy: "replace" (default), "append", or "merge"

        Returns:
            Tuple of (success, message)
        """
        if not self.db_service:
            return False, "No database service configured"

        existing = self.db_service.get_policy_by_year(year)

        if not existing:
            # Create new if doesn't exist
            return self.create_policy(year, new_content)

        now = datetime.utcnow()
        update_date = now.strftime("%Y-%m-%d")

        # Determine final content based on merge strategy
        if merge_strategy == "append":
            final_content = existing.get("content", "") + "\n\n---\n\n" + new_content
        elif merge_strategy == "merge":
            # TODO: Implement intelligent section merging
            final_content = new_content  # For now, just replace
        else:  # "replace" (default)
            final_content = new_content

        # Update document
        updated_dates = existing.get("updatedDates", [])
        if update_date not in updated_dates:
            updated_dates.append(update_date)

        updates = {
            "content": final_content,
            "toc": [t.model_dump() for t in self.generate_toc(final_content)],
            "updatedDates": updated_dates,
            "updatedAt": now,
        }

        return self.db_service.upsert_policy(
            {
                **existing,
                **updates,
            }
        )

    # =========================================================================
    # Email Processing
    # =========================================================================

    def process_policy_email(
        self,
        email_data: Dict[str, str],
        extracted: ExtractedPolicyUpdate,
    ) -> Optional[PolicyDocument]:
        """
        Process a policy update email.

        Args:
            email_data: Raw email data (subject, body)
            extracted: Extracted policy update info from LLM

        Returns:
            Created/updated PolicyDocument or None
        """
        if not extracted.is_policy_update:
            return None

        # Extract year from content or use extracted year
        combined = f"{email_data.get('subject', '')} {email_data.get('body', '')}"
        year = extracted.year or self.extract_policy_year(combined)

        if not year:
            safe_print("Could not determine policy year, skipping")
            return None

        content = extracted.content or email_data.get("body", "")

        # Check if policy exists for this year
        existing = self.get_policy_by_year(year)

        if existing:
            safe_print(f"Updating existing policy for year {year}")
            success, msg = self.update_policy(year, content, merge_strategy="replace")
        else:
            safe_print(f"Creating new policy for year {year}")
            success, msg = self.create_policy(
                year=year,
                content=content,
                title=extracted.title or "Placement Policy",
            )

        if success:
            return self.get_policy_by_year(year)
        else:
            safe_print(f"Failed to save policy: {msg}")
            return None
