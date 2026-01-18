"""
Official Placement Service

Wraps the official_placement.py scraping logic with DI support.
Implements IOfficialPlacementScraper protocol.
"""

import logging
import datetime
from typing import Optional, List, cast

import requests
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from core.config import safe_print


# Pydantic Models
class RecruiterLogo(BaseModel):
    """Recruiter logo data"""

    src: Optional[str] = Field(None, description="Image source URL")
    alt: Optional[str] = Field(None, description="Image alt text")


class PackageDistribution(BaseModel):
    """Package distribution entry from table"""

    category: str = Field(..., description="Package category (e.g., '> 20 LPA')")
    average: str = Field(..., description="Average package for category")
    median: str = Field(..., description="Median package for category")


class BatchDetails(BaseModel):
    """Extracted details for a placement batch"""

    placement_pointers: List[str] = Field(
        default_factory=list, description="List of placement bullet points"
    )
    package_distribution: List[PackageDistribution] = Field(
        default_factory=list, description="Package distribution table data"
    )


class BatchInfo(BatchDetails):
    """Full batch information including metadata"""

    batch_name: str = Field(..., description="Name of the batch (e.g., '2024')")
    is_active: bool = Field(False, description="Whether this batch tab is active")


class OfficialPlacementData(BaseModel):
    """Complete scraped placement data"""

    scrape_timestamp: str = Field(..., description="ISO timestamp of scrape")
    main_heading: Optional[str] = Field(None, description="Main heading text")
    intro_text: Optional[str] = Field(None, description="Introductory text")
    recruiter_logos: List[RecruiterLogo] = Field(
        default_factory=list, description="List of recruiter logos"
    )
    batches: List[BatchInfo] = Field(
        default_factory=list, description="Placement data per batch"
    )


# Configuration
TARGET_URL = "https://www.jiit.ac.in/"

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
        db_service: Optional[object] = None,
        target_url: str = TARGET_URL,
    ):
        """
        Initialize the service.

        Args:
            db_service: Optional database service for saving data
            target_url: URL to scrape (default: JIIT homepage)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_service = db_service
        self.target_url = target_url
        self.headers = HEADERS.copy()

        self.logger.info("OfficialPlacementService initialized")

    def get_html_content(self, url: Optional[str] = None) -> Optional[str]:
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

        except Exception as e:
            self.logger.error(f"An unknown error occurred during HTML fetch: {e}")
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
        placement_pointers: List[str] = []
        package_distribution: List[PackageDistribution] = []

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

    def parse_all_batches_data(
        self, html_content: str
    ) -> Optional[OfficialPlacementData]:
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

        main_heading: Optional[str] = None
        intro_text: Optional[str] = None
        recruiter_logos: List[RecruiterLogo] = []
        batches: List[BatchInfo] = []

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
                    and not (src.startswith("http://") or src.startswith("https://"))
                ):
                    src = self.target_url.rstrip("/") + "/" + src.lstrip("/")

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
            li.get_text(strip=True) for li in cast(Tag, batch_list_items_ul).find_all("li")
        ]
        self.logger.debug(f"Found batch names from navigation: {batch_names}")

        content_divs = cast(Tag, tab_container).find_all("div", class_="content", recursive=False)

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
            scrape_timestamp=datetime.datetime.now().isoformat(),
            main_heading=main_heading,
            intro_text=intro_text,
            recruiter_logos=recruiter_logos,
            batches=batches,
        )

    def scrape(self) -> Optional[OfficialPlacementData]:
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

    def scrape_and_save(self) -> Optional[OfficialPlacementData]:
        """
        Scrape data and save to database if db_service is available.

        Returns:
            Scraped data, or None on error
        """
        scraped_data = self.scrape()

        if scraped_data and self.db_service:
            self.logger.info("Saving scraped data to database...")
            # Convert to dict for database storage
            self.db_service.save_official_placement_data(scraped_data.model_dump())  # type: ignore
            safe_print("Official placement data saved to database.")

        return scraped_data


# ============================================================================
# Standalone Execution
# ============================================================================


def main() -> None:
    """
    Main function to orchestrate the scraping and storage process for all batches.
    """
    from services.database_service import DatabaseService

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    db_service = DatabaseService()
    service = OfficialPlacementService(db_service=db_service)

    scraped_data = service.scrape_and_save()

    if scraped_data:
        import json

        print(json.dumps(scraped_data.model_dump(), indent=2))

    db_service.close_connection()
    logging.info("All batches scraping and storage process completed.")


if __name__ == "__main__":
    main()
