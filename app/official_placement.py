import requests
from bs4 import BeautifulSoup, Tag
import datetime
import logging
from typing import cast
from database import MongoDBManager

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Configuration for Scraping ---
TARGET_URL = "https://www.jiit.ac.in/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def get_html_content(url: str, headers: dict) -> str | None:
    """
    Fetches the HTML content from the given URL.
    """
    logging.info(f"Attempting to fetch HTML from: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=15)  # Increased timeout
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        logging.info(
            f"Successfully fetched HTML content (Status: {response.status_code})."
        )
        # logging.debug(f"First 500 chars of HTML: {response.text[:500]}...") # Optional: Debug received HTML
        return response.text

    except requests.exceptions.Timeout:
        logging.error("The request timed out while connecting to the URL.")
        return None

    except requests.exceptions.ConnectionError:
        logging.error(
            "A Connection Error occurred. Check your internet connection or the URL."
        )
        return None

    except requests.exceptions.HTTPError as http_err:
        logging.error(
            f"HTTP error occurred: {http_err} - Status code: {response.status_code}"
        )
        return None

    except requests.exceptions.RequestException as req_err:
        logging.error(f"An unexpected request error occurred: {req_err}")
        return None

    except Exception as e:
        logging.error(f"An unknown error occurred during HTML fetch: {e}")
        return None


def extract_batch_details(
    container_element: Tag, context_label: str = "Unknown"
) -> dict:
    """
    Extracts placement pointers (<li> elements) and package distribution table
    from a specific container element.
    """
    details = {"placement_pointers": [], "package_distribution": []}

    logging.debug(
        f"Searching for details within container for '{context_label}'. Container HTML (first 200 chars): {str(container_element)[:200]}..."
    )

    # 1. Extract <li> pointers
    list_items = container_element.find_all("li")
    if list_items:
        for li in list_items:
            text = li.get_text(strip=True)
            if text:
                details["placement_pointers"].append(text)
        logging.debug(
            f"Extracted {len(details['placement_pointers'])} pointers from container for '{context_label}'."
        )

    # 2. Extract Table (Distribution of Packages)
    table = container_element.find("table")
    if table:
        rows = table.find_all("tr")
        # Skipping header rows (0: Main title, 1: Category/Avg/Median)
        if len(rows) > 2:
            for row in rows[2:]:
                cols = row.find_all(["td", "th"])
                if len(cols) >= 3:
                    details["package_distribution"].append(
                        {
                            "category": cols[0].get_text(strip=True),
                            "average": cols[1].get_text(strip=True),
                            "median": cols[2].get_text(strip=True),
                        }
                    )
            logging.debug(
                f"Extracted {len(details['package_distribution'])} distribution entries for '{context_label}'."
            )

    return details


def parse_all_batches_data(html_content: str) -> dict | None:
    """
    Parses the HTML content to extract general info and data for all batches,
    including identifying the active batch.
    """
    logging.info("Starting HTML parsing for all batches data...")
    soup = BeautifulSoup(html_content, "html.parser")

    full_placement_data = {
        "scrape_timestamp": datetime.datetime.now().isoformat(),
        "main_heading": None,
        "intro_text": None,
        "recruiter_logos": [],
        "batches": [],
    }

    # 1. Extract Main Heading ("Training & Placement")
    # This selector targets the first div with both classes 'annouc-heading' and 'line-three'.
    # On the JIIT site, this specifically contains "Training & Placement".
    # The 'Announcements' heading is in a different div (class 'red-bg').
    main_heading_div = cast(
        Tag,
        soup.find(
            "div",
            class_="annouc-heading line-three",
        ),
    )

    if main_heading_div:
        # Get only the direct text, ignoring any nested tags like <span> with images
        text = main_heading_div.get_text(strip=True)
        if "Training & Placement" in text:
            full_placement_data["main_heading"] = text
            logging.info(
                f"Extracted Main Heading: {full_placement_data['main_heading']}"
            )

        else:
            # Fallback for if text isn't a direct child or contains other text
            full_placement_data["main_heading"] = "Training & Placement"
            logging.warning(
                "Could not precisely extract 'Training & Placement' text from main heading div. Assigning default."
            )
    else:
        logging.warning("Main heading div ('annouc-heading line-three') not found.")

    # 2. Extract Introductory Text (Few of our regular key recruiters...)
    intro_text_div = soup.find("div", class_="text")
    if intro_text_div:
        full_placement_data["intro_text"] = intro_text_div.get_text(strip=True)
        logging.info(f"Extracted Intro Text: {full_placement_data['intro_text']}")

    else:
        logging.warning("Introductory text div (class 'text') not found.")

    # 3. Extract Recruiter Logos
    recruiter_logo_div = cast(Tag, soup.find("div", class_="training-placement-logo"))
    if recruiter_logo_div:
        for img in recruiter_logo_div.find_all("img"):
            src = cast(Tag, img).get("src")
            alt = cast(Tag, img).get("alt")

            if (
                src
                and isinstance(src, str)
                and not (src.startswith("http://") or src.startswith("https://"))
            ):
                src = TARGET_URL.rstrip("/") + "/" + src.lstrip("/")

            full_placement_data["recruiter_logos"].append({"src": src, "alt": alt})

        logging.info(
            f"Extracted {len(full_placement_data['recruiter_logos'])} recruiter logos."
        )

    else:
        logging.warning("Recruiter logos div ('training-placement-logo') not found.")

    # 4. Extract Batch Data for all available batches
    tab_container = cast(Tag, soup.find("div", class_="tab-containerr"))
    if not tab_container:
        logging.error(
            "Could not find the main tab container for batch data ('tab-containerr')."
        )
        return None

    batch_list_items_ul = cast(Tag, soup.find("ul", class_="tab-ul"))

    if not batch_list_items_ul:
        logging.error("Could not find batch navigation list ('ul.tab-ul').")
        return None

    batch_names = [li.get_text(strip=True) for li in batch_list_items_ul.find_all("li")]
    logging.debug(f"Found batch names from navigation: {batch_names}")

    content_divs = cast(Tag, tab_container).find_all(
        "div", class_="content", recursive=False
    )

    if not content_divs:
        logging.error("No content divs found within 'tab-containerr'.")
        return None

    logging.debug(f"Found {len(content_divs)} content divs.")

    for i, content_div in enumerate(content_divs):
        batch_info = {}
        is_active = cast(Tag, content_div).get("style") == "display: block;"
        current_batch_name = (
            batch_names[i] if i < len(batch_names) else f"Unknown Batch {i+1}"
        )

        batch_info["batch_name"] = current_batch_name
        batch_info["is_active"] = is_active

        pointers_container = None
        context_label = f"{current_batch_name} content"

        logging.debug(
            f"Processing batch: {current_batch_name}, Active: {is_active}. Content Div HTML (first 200 chars): {str(content_div)[:200]}..."
        )

        if not content_div:
            logging.error(f"Content div is None for index {i}. Skipping.")
            continue

        # Corrected logic for finding pointers_container based on user's latest HTML snippets
        # Both active and inactive content divs have a very similar structure at this level:
        # content -> ach-contetn-outer [mCustomScrollbar] -> scroll_sec mCustomScrollbar (THIS IS THE CONTAINER)
        pointers_container = cast(Tag, content_div).find(
            "div", class_="scroll_sec mCustomScrollbar"
        )

        if pointers_container:
            logging.debug(
                f"Found 'div.scroll_sec.mCustomScrollbar' as potential container for {current_batch_name}."
            )

            batch_details = extract_batch_details(
                cast(Tag, pointers_container), context_label
            )
            batch_info.update(batch_details)

            logging.info(
                f"Extracted data for batch: {current_batch_name} (Active: {is_active}) "
                f"with {len(batch_info['placement_pointers'])} pointers and "
                f"{len(batch_info['package_distribution'])} distribution entries."
            )

        else:
            logging.error(
                f"Could not find 'div.scroll_sec.mCustomScrollbar' for batch: {current_batch_name}. No pointers extracted. "
                f"Content div for {current_batch_name} (first 500 chars): {str(content_div)[:500]}..."
            )
            batch_info["placement_pointers"] = []

        full_placement_data["batches"].append(batch_info)

    if not full_placement_data["batches"]:
        logging.warning(
            "No batch placement data found in the 'tab-containerr' section."
        )

    return full_placement_data


def main():
    """
    Main function to orchestrate the scraping and storage process for all batches.
    """
    logging.info("Starting JIIT All Batches Placement Scraper...")

    db_manager = MongoDBManager()

    html_content = get_html_content(TARGET_URL, HEADERS)
    if not html_content:
        logging.critical("Failed to retrieve HTML content. Exiting.")
        return

    scraped_data = parse_all_batches_data(html_content)
    if not scraped_data:
        logging.critical(
            "Failed to parse all batches placement data from HTML. Exiting."
        )
        return

    db_manager.save_official_placement_data(scraped_data)

    import json

    print(json.dumps(scraped_data, indent=2))

    logging.info("All batches scraping and storage process completed.")


if __name__ == "__main__":
    main()
