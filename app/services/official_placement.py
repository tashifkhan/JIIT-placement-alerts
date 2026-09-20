"""
Official Placement Service

Wraps the official_placement.py scraping logic with DI support.
Implements IOfficialPlacementScraper protocol.
"""

import datetime
import json
import logging
import re
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from core.config import safe_print

logger = logging.getLogger(__name__)


# Pydantic Models
class RecruiterLogo(BaseModel):
    """Recruiter logo data"""

    src: str | None = Field(None, description="Image source URL")
    alt: str | None = Field(None, description="Image alt text")


class PackageDistribution(BaseModel):
    """Package distribution entry from table"""

    category: str = Field(..., description="Package category (e.g., '> 20 LPA')")
    average: str = Field(..., description="Average package for category")
    median: str = Field(..., description="Median package for category")


class PlacementHighlight(BaseModel):
    """Placement statistic displayed in a highlight card."""

    title: str = Field(..., description="Highlighted statistic or package")
    description: str = Field(..., description="Description of the statistic")


class BatchDetails(BaseModel):
    """Extracted details for a placement batch"""

    placement_pointers: list[str] = Field(
        default_factory=list, description="List of placement bullet points"
    )
    package_distribution: list[PackageDistribution] = Field(
        default_factory=list, description="Package distribution table data"
    )
    highlights: list[PlacementHighlight] = Field(
        default_factory=list, description="Placement highlight cards"
    )


class BatchInfo(BatchDetails):
    """Full batch information including metadata"""

    batch_name: str = Field(..., description="Name of the batch (e.g., '2024')")
    is_active: bool = Field(False, description="Whether this batch tab is active")


class OfficialPlacementData(BaseModel):
    """Complete scraped placement data"""

    scrape_timestamp: str = Field(..., description="ISO timestamp of scrape")
    main_heading: str | None = Field(None, description="Main heading text")
    intro_text: str | None = Field(None, description="Introductory text")
    recruiter_logos: list[RecruiterLogo] = Field(
        default_factory=list, description="List of recruiter logos"
    )
    batches: list[BatchInfo] = Field(
        default_factory=list, description="Placement data per batch"
    )


# Configuration
TARGET_URL = (
    "https://www.jiit.ac.in/existing-student/training-and-placement/"
    "students-placement"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# Service
class OfficialPlacementService:
    """
    Service for scraping official JIIT placement data.

    Implements IOfficialPlacementScraper protocol.
    """

    def __init__(
        self,
        db_service: object | None = None,
        target_url: str = TARGET_URL,
    ):
        """
        Initialize the service.

        Args:
            db_service: Optional database service for saving data
            target_url: URL to scrape (default: JIIT students placement page)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        self.target_url = target_url
        self.headers = HEADERS.copy()

        self.logger.info("OfficialPlacementService initialized")

    def get_html_content(self, url: str | None = None) -> str | None:
        """
        Fetches the HTML content from the given URL.

        Args:
            url: URL to fetch (default: self.target_url)

        Returns:
            HTML content as string, or None on error
        """
        url = url or self.target_url
        self.logger.info(f"Attempting to fetch HTML from: {url}")

        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            self.logger.info(
                f"Successfully fetched HTML content (Status: {response.status_code})."
            )
            return response.text

        except requests.exceptions.Timeout:
            self.logger.error("The request timed out while connecting to the URL.")
            return None

        except requests.exceptions.ConnectionError:
            self.logger.error(
                "A Connection Error occurred. Check your internet connection or the URL."
            )
            return None

        except requests.exceptions.HTTPError as http_err:
            self.logger.error(f"HTTP error occurred: {http_err}")
            return None

        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"An unexpected request error occurred: {req_err}")
            return None

        except Exception:
            self.logger.exception("An unknown error occurred during HTML fetch")
            return None

    def extract_batch_details(
        self,
        container_element: Tag,
        context_label: str = "Unknown",
    ) -> BatchDetails:
        """
        Extracts placement pointers (<li> elements) and package distribution table
        from a specific container element.

        Args:
            container_element: BeautifulSoup Tag to extract from
            context_label: Label for logging context

        Returns:
            BatchDetails with placement_pointers and package_distribution
        """
        placement_pointers: list[str] = []
        package_distribution: list[PackageDistribution] = []

        self.logger.debug(
            f"Searching for details within container for '{context_label}'."
        )

        # 1. Extract <li> pointers
        list_items = container_element.find_all("li")
        if list_items:
            for li in list_items:
                text = li.get_text(strip=True)
                if text:
                    placement_pointers.append(text)
            self.logger.debug(
                f"Extracted {len(placement_pointers)} pointers for '{context_label}'."
            )

        # 2. Extract Table (Distribution of Packages)
        table = container_element.find("table")
        if table:
            rows = cast(Tag, table).find_all("tr")
            # Skipping header rows (0: Main title, 1: Category/Avg/Median)
            if len(rows) > 2:
                for row in rows[2:]:
                    cols = cast(Tag, row).find_all(["td", "th"])
                    if len(cols) >= 3:
                        package_distribution.append(
                            PackageDistribution(
                                category=cols[0].get_text(strip=True),
                                average=cols[1].get_text(strip=True),
                                median=cols[2].get_text(strip=True),
                            )
                        )
                self.logger.debug(
                    f"Extracted {len(package_distribution)} distribution entries for '{context_label}'."
                )

        return BatchDetails(
            placement_pointers=placement_pointers,
            package_distribution=package_distribution,
        )

    def _next_payload_fragments(self, soup: BeautifulSoup) -> Iterator[str]:
        """Yield decoded text fragments from Next.js flight-data scripts."""
        prefix = "self.__next_f.push("

        for script in soup.find_all("script"):
            script_text = script.string
            if not script_text or not script_text.startswith(prefix):
                continue

            payload = script_text[len(prefix) :]
            payload = payload.removesuffix(")")

            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                self.logger.debug("Skipping an unrecognized Next.js payload fragment")
                continue

            if (
                isinstance(parsed, list)
                and len(parsed) > 1
                and isinstance(parsed[1], str)
            ):
                yield parsed[1]

    @staticmethod
    def _objects_containing(fragment: str, marker: str) -> Iterator[dict[str, Any]]:
        """Decode JSON objects beginning at a marker inside a payload fragment."""
        decoder = json.JSONDecoder()
        start = 0

        while True:
            marker_index = fragment.find(marker, start)
            if marker_index == -1:
                return

            object_start = fragment.rfind("{", 0, marker_index + 1)
            if object_start == -1:
                return

            try:
                value, end = decoder.raw_decode(fragment[object_start:])
            except json.JSONDecodeError:
                start = marker_index + len(marker)
                continue

            if isinstance(value, dict):
                yield value
            start = object_start + end

    @staticmethod
    def _batch_name(title: str, fallback_index: int) -> str:
        """Extract the graduating year from a placement-section title."""
        match = re.search(r"\b(20\d{2})\b", title)
        return match.group(1) if match else f"Unknown Batch {fallback_index}"

    @staticmethod
    def _highlights_from_section(section: Tag) -> list[PlacementHighlight]:
        """Read title/description pairs from a highlight-card grid."""
        highlights: list[PlacementHighlight] = []
        for item in section.select(".highlights .item"):
            item_title = item.select_one(".title")
            description = item.select_one(".desc")
            if not item_title or not description:
                continue
            title = item_title.get_text(" ", strip=True)
            desc = description.get_text(" ", strip=True)
            if title and desc:
                highlights.append(
                    PlacementHighlight(title=title, description=desc)
                )
        return highlights

    def _placement_sections(self, soup: BeautifulSoup) -> list[Tag]:
        """Find highlight-card sections in the students-placement markup.

        JIIT currently misspells the wrapper as `palcement-sec` and uses
        `student-placement-pg`. Prefer those, then the correctly spelled class,
        then any heading that says Placement Highlights.
        """
        for selector in (
            "div.student-placement-pg",
            "div.palcement-sec",
            "div.placement-sec",
        ):
            sections = [tag for tag in soup.select(selector) if isinstance(tag, Tag)]
            if sections:
                return sections

        sections: list[Tag] = []
        seen: set[int] = set()
        for heading in soup.select(".mainheading__large"):
            if not isinstance(heading, Tag):
                continue
            if "Placement Highlights" not in heading.get_text(" ", strip=True):
                continue
            container = heading.parent
            while isinstance(container, Tag):
                if container.select_one(".highlights .item"):
                    ident = id(container)
                    if ident not in seen:
                        seen.add(ident)
                        sections.append(container)
                    break
                parent = container.parent
                container = parent if isinstance(parent, Tag) else None
        return sections

    def _batches_from_dom(self, soup: BeautifulSoup) -> list[BatchInfo]:
        """Parse highlight cards from the HTML already in the document."""
        batches: list[BatchInfo] = []
        for index, section in enumerate(self._placement_sections(soup), start=1):
            heading = section.select_one(".mainheading__large")
            title = heading.get_text(" ", strip=True) if heading else ""
            highlights = self._highlights_from_section(section)
            if not highlights:
                continue
            batches.append(
                BatchInfo(
                    batch_name=self._batch_name(title, index),
                    is_active=index == 1,
                    highlights=highlights,
                )
            )
        return batches

    @staticmethod
    def _is_highlights_component(data: dict[str, Any]) -> bool:
        component = str(data.get("__component") or "")
        return component.endswith("placement-highlights")

    def _batches_from_payload(self, payload_fragments: list[str]) -> list[BatchInfo]:
        """Parse highlight cards from Next.js flight payloads."""
        batches: list[BatchInfo] = []
        for fragment in payload_fragments:
            for data in self._objects_containing(fragment, '"__component"'):
                if not self._is_highlights_component(data):
                    continue
                title = str(data.get("title") or "")
                raw_items = data.get("list")
                if not isinstance(raw_items, list):
                    continue

                highlights = [
                    PlacementHighlight(
                        title=str(item.get("title") or "").strip(),
                        description=str(item.get("description") or "").strip(),
                    )
                    for item in raw_items
                    if isinstance(item, dict)
                    and str(item.get("title") or "").strip()
                    and str(item.get("description") or "").strip()
                ]
                if not highlights:
                    continue

                batches.append(
                    BatchInfo(
                        batch_name=self._batch_name(title, len(batches) + 1),
                        is_active=len(batches) == 0,
                        highlights=highlights,
                    )
                )
        return batches

    def _extract_current_batches(
        self, soup: BeautifulSoup, payload_fragments: list[str]
    ) -> list[BatchInfo]:
        """Extract placement highlight cards from the current JIIT page."""
        batches = self._batches_from_dom(soup)
        if batches:
            return batches
        return self._batches_from_payload(payload_fragments)

    def _logo_from_src(
        self, src: str, alt: str | None = None
    ) -> RecruiterLogo:
        cleaned_alt = alt.strip() if isinstance(alt, str) else None
        return RecruiterLogo(
            src=urljoin(self.target_url, src),
            alt=cleaned_alt or None,
        )

    def _logos_from_payload(
        self, payload_fragments: list[str]
    ) -> list[RecruiterLogo]:
        """Recruiter slides in the flight payload include company names."""
        logos: list[RecruiterLogo] = []
        seen: set[str] = set()
        for fragment in payload_fragments:
            for data in self._objects_containing(fragment, '"slidecount"'):
                images = data.get("Images") or data.get("images")
                if not isinstance(images, list):
                    continue
                for item in images:
                    if not isinstance(item, dict) or not item.get("image"):
                        continue
                    src = urljoin(self.target_url, str(item["image"]))
                    if src in seen:
                        continue
                    seen.add(src)
                    logos.append(
                        self._logo_from_src(
                            src, str(item.get("name") or "") or None
                        )
                    )
        return logos

    def _logos_from_dom(self, soup: BeautifulSoup) -> list[RecruiterLogo]:
        """Read recruiter images from the Key Recruiters grid."""
        logos: list[RecruiterLogo] = []
        seen: set[str] = set()
        selectors = (
            ".placements-items img",
            ".recruiters img",
            ".key-recruiters img",
        )
        for selector in selectors:
            for img in soup.select(selector):
                src = img.get("src")
                if not isinstance(src, str) or not src or src in seen:
                    continue
                seen.add(src)
                alt = img.get("alt")
                logos.append(
                    self._logo_from_src(
                        src, alt if isinstance(alt, str) else None
                    )
                )
        return logos

    def _extract_current_recruiter_logos(
        self, soup: BeautifulSoup, payload_fragments: list[str]
    ) -> list[RecruiterLogo]:
        """Extract recruiter logos from rendered or serialized current markup."""
        # Payload includes company names; the rendered grid currently ships empty alts.
        logos = self._logos_from_payload(payload_fragments)
        if logos:
            return logos
        return self._logos_from_dom(soup)

    def parse_all_batches_data(
        self, html_content: str
    ) -> OfficialPlacementData | None:
        """
        Parses the HTML content to extract general info and data for all batches,
        including identifying the active batch.

        Args:
            html_content: HTML string to parse

        Returns:
            OfficialPlacementData with all parsed placement data, or None on error
        """
        self.logger.info("Starting HTML parsing for all batches data...")
        soup = BeautifulSoup(html_content, "html.parser")

        main_heading: str | None = None
        intro_text: str | None = None
        recruiter_logos: list[RecruiterLogo] = []
        batches: list[BatchInfo] = []

        payload_fragments = list(self._next_payload_fragments(soup))
        current_batches = self._extract_current_batches(soup, payload_fragments)
        if current_batches:
            heading = soup.select_one(".inner-banner .mainheading__large")
            main_heading = (
                heading.get_text(" ", strip=True)
                if heading
                else "Training & Placement"
            )

            intro = soup.select_one(".desc-sec .left")
            if intro:
                intro_text = intro.get_text(" ", strip=True)
            else:
                for fragment in payload_fragments:
                    html_start = fragment.find("<p>")
                    if (
                        html_start != -1
                        and "Training and Placement activities" in fragment
                    ):
                        intro_text = BeautifulSoup(
                            fragment[html_start:], "html.parser"
                        ).get_text(" ", strip=True)
                        break

            recruiter_logos = self._extract_current_recruiter_logos(
                soup, payload_fragments
            )
            self.logger.info(
                "Extracted %s current placement batches and %s recruiter logos.",
                len(current_batches),
                len(recruiter_logos),
            )
            return OfficialPlacementData(
                scrape_timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                main_heading=main_heading,
                intro_text=intro_text,
                recruiter_logos=recruiter_logos,
                batches=current_batches,
            )

        # 1. Extract Main Heading ("Training & Placement")
        main_heading_div = soup.find("div", class_="annouc-heading line-three")

        if main_heading_div:
            text = main_heading_div.get_text(strip=True)
            if "Training & Placement" in text:
                main_heading = text
                self.logger.info(f"Extracted Main Heading: {main_heading}")
            else:
                main_heading = "Training & Placement"
                self.logger.warning(
                    "Could not precisely extract 'Training & Placement' text. Assigning default."
                )
        else:
            self.logger.warning("Main heading div not found.")

        # 2. Extract Introductory Text
        intro_text_div = soup.find("div", class_="text")
        if intro_text_div:
            intro_text = intro_text_div.get_text(strip=True)
            self.logger.info(f"Extracted Intro Text: {intro_text}")
        else:
            self.logger.warning("Introductory text div not found.")

        # 3. Extract Recruiter Logos
        recruiter_logo_div = soup.find("div", class_="training-placement-logo")
        if recruiter_logo_div:
            for img in cast(Tag, recruiter_logo_div).find_all("img"):
                src = cast(Tag, img).get("src")
                alt = cast(Tag, img).get("alt")

                if (
                    src
                    and isinstance(src, str)
                    and not src.startswith(("http://", "https://"))
                ):
                    src = urljoin(self.target_url, src)

                recruiter_logos.append(
                    RecruiterLogo(
                        src=src if isinstance(src, str) else None,
                        alt=alt if isinstance(alt, str) else None,
                    )
                )

            self.logger.info(f"Extracted {len(recruiter_logos)} recruiter logos.")
        else:
            self.logger.warning("Recruiter logos div not found.")

        # 4. Extract Batch Data for all available batches
        tab_container = soup.find("div", class_="tab-containerr")
        if not tab_container:
            self.logger.error(
                "Could not find the main tab container for batch data ('tab-containerr')."
            )
            return None

        batch_list_items_ul = soup.find("ul", class_="tab-ul")

        if not batch_list_items_ul:
            self.logger.error("Could not find batch navigation list ('ul.tab-ul').")
            return None

        batch_names = [
            li.get_text(strip=True)
            for li in cast(Tag, batch_list_items_ul).find_all("li")
        ]
        self.logger.debug(f"Found batch names from navigation: {batch_names}")

        content_divs = cast(Tag, tab_container).find_all(
            "div", class_="content", recursive=False
        )

        if not content_divs:
            self.logger.error("No content divs found within 'tab-containerr'.")
            return None

        self.logger.debug(f"Found {len(content_divs)} content divs.")

        for i, content_div in enumerate(content_divs):
            is_active = cast(Tag, content_div).get("style") == "display: block;"
            current_batch_name = (
                batch_names[i] if i < len(batch_names) else f"Unknown Batch {i + 1}"
            )

            context_label = f"{current_batch_name} content"

            self.logger.debug(
                f"Processing batch: {current_batch_name}, Active: {is_active}."
            )

            if not content_div:
                self.logger.error(f"Content div is None for index {i}. Skipping.")
                continue

            # Find pointers container
            pointers_container = cast(Tag, content_div).find(
                "div", class_="scroll_sec mCustomScrollbar"
            )

            if pointers_container:
                self.logger.debug(f"Found scroll container for {current_batch_name}.")

                batch_details = self.extract_batch_details(
                    cast(Tag, pointers_container), context_label
                )

                batch_info = BatchInfo(
                    batch_name=current_batch_name,
                    is_active=is_active,
                    placement_pointers=batch_details.placement_pointers,
                    package_distribution=batch_details.package_distribution,
                )

                self.logger.info(
                    f"Extracted data for batch: {current_batch_name} (Active: {is_active}) "
                    f"with {len(batch_info.placement_pointers)} pointers and "
                    f"{len(batch_info.package_distribution)} distribution entries."
                )
            else:
                self.logger.error(
                    f"Could not find scroll container for batch: {current_batch_name}."
                )
                batch_info = BatchInfo(
                    batch_name=current_batch_name,
                    is_active=is_active,
                    placement_pointers=[],
                    package_distribution=[],
                )

            batches.append(batch_info)

        if not batches:
            self.logger.warning(
                "No batch placement data found in the 'tab-containerr' section."
            )

        return OfficialPlacementData(
            scrape_timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            main_heading=main_heading,
            intro_text=intro_text,
            recruiter_logos=recruiter_logos,
            batches=batches,
        )

    def scrape(self) -> OfficialPlacementData | None:
        """
        Main scraping function - implements IOfficialPlacementScraper protocol.

        Returns:
            Scraped placement data, or None on error
        """
        self.logger.info("Starting JIIT All Batches Placement Scraper...")
        safe_print(f"Fetching data from {self.target_url}...")

        html_content = self.get_html_content()
        if not html_content:
            self.logger.critical("Failed to retrieve HTML content.")
            safe_print("Failed to retrieve HTML content.")
            return None

        safe_print("Parsing placement data...")
        scraped_data = self.parse_all_batches_data(html_content)

        if not scraped_data:
            self.logger.critical(
                "Failed to parse all batches placement data from HTML."
            )
            safe_print("Failed to parse placement data.")
            return None

        batch_count = len(scraped_data.batches)
        safe_print(f"Found {batch_count} batch sections")

        return scraped_data

    def scrape_and_save(self) -> OfficialPlacementData | None:
        """
        Scrape data and save to database if db_service is available.

        Writes a full-page snapshot to OfficialPlacementData and upserts each
        scraped year into OfficialPlacementBatches (without overwriting seeded
        years).

        Returns:
            Scraped data, or None on error
        """
        scraped_data = self.scrape()

        if scraped_data and self.db_service:
            self.logger.info("Saving scraped data to database...")
            saved = self.db_service.save_official_placement_data(  # type: ignore
                scraped_data.model_dump()
            )
            if not saved:
                self.logger.error("Failed to persist official placement data")
                safe_print("Failed to save official placement data.")
                return None
            safe_print(
                "Official placement snapshot and live batches saved to database."
            )

        return scraped_data

    @staticmethod
    def default_seed_path():
        """Default path for frozen prior-year official batch seed JSON."""
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[1]
            / "data"
            / "official_placement_batches_seed.json"
        )

    def load_seed_batches(self, seed_path=None) -> list[dict[str, Any]]:
        """Load seeded graduating-year batches from JSON."""
        from pathlib import Path

        path = Path(seed_path) if seed_path else self.default_seed_path()
        payload = json.loads(path.read_text(encoding="utf-8"))
        batches = payload.get("batches") if isinstance(payload, dict) else payload
        if not isinstance(batches, list):
            raise TypeError(f"Seed file {path} must contain a batches list")
        seed_version = (
            str(payload.get("seed_version") or "1")
            if isinstance(payload, dict)
            else "1"
        )
        normalized: list[dict[str, Any]] = []
        for item in batches:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("seed_version", seed_version)
            normalized.append(row)
        return normalized

    def seed_batches(
        self,
        seed_path=None,
        *,
        overwrite_seeded: bool = False,
    ) -> dict[str, int]:
        """Upsert frozen prior-year batches from the seed file."""
        if not self.db_service:
            raise RuntimeError("db_service is required to seed official batches")
        batches = self.load_seed_batches(seed_path)
        return self.db_service.upsert_seeded_official_placement_batches(  # type: ignore
            batches,
            overwrite_seeded=overwrite_seeded,
        )

# ============================================================================
# Standalone Execution
# ============================================================================


def main() -> None:
    """
    Main function to orchestrate the scraping and storage process for all batches.
    """
    from clients.db_client import DBClient
    from services.database import DatabaseService

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    db_client = DBClient(use_global_database=True)
    db_client.connect()
    db_service = DatabaseService(db_client)
    service = OfficialPlacementService(db_service=db_service)

    scraped_data = service.scrape_and_save()

    if scraped_data:
        import json

        print(json.dumps(scraped_data.model_dump(), indent=2))

    db_client.close_connection()
    logger.info("All batches scraping and storage process completed.")


if __name__ == "__main__":
    main()
