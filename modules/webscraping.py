import dotenv
import time
import os
import signal
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from .database import MongoDBManager

dotenv.load_dotenv()


class WebScraper:
    def __init__(self):
        self.USER_ID = os.getenv("USER_ID")
        self.PASSWORD = os.getenv("PASSWORD")
        self.PORTAL_URL = "https://app.joinsuperset.com/students/login"
        self.driver = None
        self.db_manager = MongoDBManager()
        self._setup_chrome_options()

    def _setup_chrome_options(self):
        """Setup Chrome browser options"""
        self.chrome_options = ChromeOptions()
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--disable-plugins")
        self.chrome_options.add_argument(
            "--disable-blink-features=AutomationControlled"
        )
        self.chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        self.chrome_options.add_experimental_option("useAutomationExtension", False)
        self.chrome_options.add_argument("--window-size=660,1080")
        self.chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    @contextmanager
    def timeout(self, duration):
        """Context manager for timeout handling"""

        def timeout_handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {duration} seconds")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(duration)

        try:
            yield
        finally:
            signal.alarm(0)

    def init_chrome_driver(self):
        """Initialize Chrome WebDriver"""
        try:
            print("Downloading/setting up ChromeDriver...")
            with self.timeout(30):
                service = ChromeService(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=self.chrome_options)
                print("ChromeDriver initialized successfully!")
                return driver

        except TimeoutError:
            print("ChromeDriver initialization timed out")

        except Exception as e:
            print(f"Failed to initialize Chrome driver with webdriver-manager: {e}")

        try:
            print("Trying Chrome without webdriver-manager...")
            with self.timeout(15):
                driver = webdriver.Chrome(options=self.chrome_options)
                print("ChromeDriver initialized with fallback!")
                return driver

        except TimeoutError:
            print("Chrome fallback initialization timed out")

        except Exception as e2:
            print(f"Chrome fallback also failed: {e2}")

        return None

    def init_firefox_driver(self):
        """Initialize Firefox WebDriver"""
        try:
            print("Setting up Firefox driver...")
            firefox_options = FirefoxOptions()
            firefox_options.add_argument("--headless")

            with self.timeout(30):
                service = FirefoxService(GeckoDriverManager().install())
                driver = webdriver.Firefox(service=service, options=firefox_options)
                print("Firefox driver initialized successfully!")
                return driver

        except TimeoutError:
            print("Firefox initialization timed out")

        except Exception as e:
            print(f"Failed to initialize Firefox driver: {e}")

        return None

    def initialize_driver(self):
        """Initialize the best available WebDriver"""
        print("Attempting to initialize Chrome driver...")
        self.driver = self.init_chrome_driver()

        if self.driver is None:
            print("Chrome failed, trying Firefox...")
            self.driver = self.init_firefox_driver()

        if self.driver is None:
            print("Both Chrome and Firefox initialization failed!")
            print("Please ensure you have either Chrome or Firefox installed.")
            raise Exception("Failed to initialize any WebDriver")

        return self.driver

    def login(self):
        """Perform login to the portal"""
        try:
            print(f"Navigating to: {self.PORTAL_URL}")
            self.driver.get(self.PORTAL_URL)
            print("Page request sent, waiting for elements...")

            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            print("Page body loaded!")

            print(f"Page title: {self.driver.title}")

            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, ":r1:"))
            )
            print("Login elements found!")

            username_field = self.driver.find_element(By.ID, ":r1:")
            password_field = self.driver.find_element(By.ID, ":r2:")

            print(
                f"Username field: {username_field.get_attribute('placeholder') or 'No placeholder'}"
            )
            print(
                f"Password field: {password_field.get_attribute('placeholder') or 'No placeholder'}"
            )

            username_field.send_keys(self.USER_ID)
            password_field.send_keys(self.PASSWORD)

            login_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            login_button.click()
            print("Login button clicked!")

            print("Waiting for login to complete...")
            time.sleep(3)
            print("Login attempt made, checking for success...")

            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.px-5.pt-5.pb-0"))
            )
            print("Login successful, job posts section loaded!")
            return True

        except Exception as login_error:
            print(f"Could not find login elements: {login_error}")
            print("Page title:", self.driver.title)
            print("Current URL:", self.driver.current_url)

            try:
                self.driver.save_screenshot("debug_screenshot.png")
                print("Screenshot saved as debug_screenshot.png")
            except:
                pass

            return False

    def scroll_and_load_content(self):
        """Scroll through the page and load all content"""
        print("Looking for scrollable inner containers...")

        scrollable_container = None
        try:
            containers = self.driver.find_elements(
                By.CSS_SELECTOR, "div[class*='overflow'], div[style*='overflow']"
            )

            for container in containers:
                scroll_height = self.driver.execute_script(
                    "return arguments[0].scrollHeight", container
                )
                client_height = self.driver.execute_script(
                    "return arguments[0].clientHeight", container
                )

                if scroll_height > client_height:
                    print(
                        f"Found scrollable container: scrollHeight={scroll_height}, clientHeight={client_height}"
                    )
                    scrollable_container = container
                    break

        except Exception as e:
            print(f"Error finding scrollable container: {e}")

        if scrollable_container:
            print("Scrolling the inner container...")
            last_scroll_top = 0
            scroll_attempts = 0
            max_attempts = 5
            clicked_buttons = set()  # using set to avoid double clicking the button

            while scroll_attempts < max_attempts:
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight",
                    scrollable_container,
                )
                time.sleep(2)

                try:
                    show_more_buttons = []
                    buttons_by_text = self.driver.find_elements(
                        By.XPATH,
                        "//button[contains(text(), 'See More') or contains(text(), 'see more')]",
                    )
                    show_more_buttons.extend(buttons_by_text)

                    mui_buttons = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "button.MuiButton-root.MuiButton-text.MuiButton-textPrimary",
                    )
                    for btn in mui_buttons:
                        if "see more" in btn.text.lower():
                            show_more_buttons.append(btn)

                    css_buttons = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "button[class*='MuiButton-root'][class*='!text-xs'][class*='!mt-3']",
                    )
                    for btn in css_buttons:
                        if "see more" in btn.text.lower():
                            show_more_buttons.append(btn)

                    print(
                        f"Found {len(show_more_buttons)} potential 'See More' buttons"
                    )

                    for button in show_more_buttons:
                        try:
                            button_id = f"{button.location['x']}-{button.location['y']}-{button.text.strip()}"

                            if (
                                button_id not in clicked_buttons
                                and button.is_displayed()
                                and button.is_enabled()
                                and "see more" in button.text.lower()
                            ):

                                print(
                                    f"Clicking 'See More' button: '{button.text.strip()}'"
                                )
                                try:
                                    button.click()
                                except:
                                    self.driver.execute_script(
                                        "arguments[0].click();", button
                                    )

                                clicked_buttons.add(button_id)
                                time.sleep(3)
                                scroll_attempts = 0
                                break

                        except Exception as button_error:
                            print(f"Error processing button: {button_error}")
                            continue

                except Exception as find_error:
                    print(f"Error finding see more buttons: {find_error}")

                current_scroll_top = self.driver.execute_script(
                    "return arguments[0].scrollTop", scrollable_container
                )
                scroll_height = self.driver.execute_script(
                    "return arguments[0].scrollHeight", scrollable_container
                )

                if current_scroll_top == last_scroll_top:
                    scroll_attempts += 1
                    print(
                        f"Container scroll position unchanged, attempt {scroll_attempts}/{max_attempts}"
                    )

                else:
                    scroll_attempts = 0
                    print(
                        f"Container scrolled from {last_scroll_top} to {current_scroll_top} (max: {scroll_height})"
                    )

                last_scroll_top = current_scroll_top

            print(
                f"Finished scrolling the inner container. Clicked {len(clicked_buttons)} 'Show more' buttons."
            )

        else:
            print("No scrollable inner container found!")

    def extract_content_incrementally(self):
        """Extract content from the page and check database incrementally"""
        print("\n📝 Extracting content with incremental database checking...")

        selectors_to_try = [
            "div.px-5.pt-6.pb-0",
            "div.px-5.pt-5.pb-0",
            "div[class*='px-5'][class*='pt-'][class*='pb-0']",
            "div.px-5",
        ]

        content_elements = []
        for selector in selectors_to_try:
            print(f"Trying selector: {selector}")
            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                print(f"Found {len(elements)} elements with selector: {selector}")
                content_elements = elements
                break

        if not content_elements:
            print(
                "No content elements found with any selector, trying to find all divs with px-5 class..."
            )
            content_elements = self.driver.find_elements(
                By.CSS_SELECTOR, "div[class*='px-5']"
            )
            print(f"Found {len(content_elements)} elements with px-5 class")

        new_posts = []
        processed_count = 0

        for i, element in enumerate(content_elements):
            try:
                element_text = element.text.strip()
                if element_text and len(element_text) > 50:
                    processed_count += 1
                    print(
                        f"Processing post #{processed_count} ({len(element_text)} characters)..."
                    )

                    result = self.process_single_post(element_text, processed_count)

                    if result == "duplicate":
                        print(
                            f"🛑 Found duplicate post #{processed_count}. Stopping scraping."
                        )
                        break
                    elif result == "saved":
                        new_posts.append(element_text)

            except Exception as element_error:
                print(f"Error processing element {i+1}: {element_error}")

        print(f"📊 Scraping Summary:")
        print(f"   Total posts processed: {processed_count}")
        print(f"   New posts saved: {len(new_posts)}")

        return new_posts, processed_count

    def fallback_content_extraction(self):
        """Fallback method for content extraction"""
        print("Attempting fallback content extraction...")

        try:
            # Try to find any divs with text content
            all_divs = self.driver.find_elements(By.TAG_NAME, "div")
            content_blocks = []

            for div in all_divs[:50]:  # Limit to first 50 divs
                try:
                    text = div.text.strip()
                    if (
                        len(text) > 100 and len(text) < 5000
                    ):  # Reasonable content length
                        content_blocks.append(text)
                        if len(content_blocks) >= 10:  # Limit fallback results
                            break
                except:
                    continue

            print(f"Fallback extraction found {len(content_blocks)} content blocks")
            return content_blocks

        except Exception as e:
            print(f"Fallback extraction failed: {e}")
            return []

    # Database saving is now handled individually in process_single_post method

    def extract_post_metadata_from_raw(self, content_lines):
        """Extract title, author, and posted time from raw content lines"""
        title = "Untitled Post"
        author = ""
        posted_time = ""

        for line in content_lines[:5]:

            if (
                any(
                    pattern in line.lower()
                    for pattern in [
                        "open for applications",
                        "hiring",
                        "placement",
                        "job",
                        "internship",
                        "hackathon",
                        "campus connect",
                        "webinar",
                    ]
                )
                and len(line) > 20
            ):
                title = line[:100]
                break

        author_names = [
            "anurag srivastava",
            "anita marwaha",
            "vinod kumar",
            "archita kumar",
            "deeksha jain",
            "placement team",
            "sanjay dawar",
            "breg. sanjay dawar",
        ]
        for line in content_lines:
            if any(name in line.lower() for name in author_names):
                author = line.strip()
                break

        time_keywords = [
            "days ago",
            "hours ago",
            "minutes ago",
            "yesterday",
            "today",
            "hrs",
            "mins",
            "ago",
        ]
        for line in content_lines:
            if any(keyword in line.lower() for keyword in time_keywords):
                posted_time = line.strip()
                break

        return title, author, posted_time

    def create_basic_formatted_content(self, content_lines):
        """Create basic formatted content for database storage"""
        formatted_lines = []

        for line in content_lines:
            line = line.strip()
            if not line:
                continue

            if line == "See Less":
                continue

            if line.strip() == "·":
                continue

            if self.is_title_line_simple(line):
                formatted_lines.append(f"## {line}")

            elif "deadline" in line.lower():
                formatted_lines.append(f"⚠️ DEADLINE: {line}")

            elif any(
                term in line.lower() for term in ["eligibility", "process", "benefits"]
            ):
                formatted_lines.append(f"**{line}:**")

            elif line.startswith("•") or line.startswith("-"):
                formatted_lines.append(line)

            elif "http" in line.lower() or "www." in line.lower():
                formatted_lines.append(f"🔗 {line}")

            else:
                formatted_lines.append(line)

        return "\n".join(formatted_lines)

    def is_title_line_simple(self, line):
        """Simple check for title lines"""
        title_patterns = [
            "open for applications",
            "hiring",
            "placement",
            "job",
            "internship",
            "hackathon",
            "campus connect",
            "webinar",
        ]

        return (
            any(pattern in line.lower() for pattern in title_patterns)
            and len(line) > 20
            and len(line) < 150
        )

    def scrape(self):
        """Main scraping method with incremental database checking"""
        try:
            self.initialize_driver()

            if not self.login():
                raise Exception("Login failed")

            self.scroll_and_load_content()
            new_posts, processed_count = self.extract_content_incrementally()

            print(f"\n🎯 Web scraping completed!")
            print(f"   Posts processed: {processed_count}")
            print(f"   New posts saved: {len(new_posts)}")

            try:
                stats = self.db_manager.get_posts_stats()
                print(f"📊 Database Summary:")
                print(f"   Total posts in database: {stats.get('total_posts', 0)}")
                print(f"   Unsent posts: {stats.get('pending_to_send', 0)}")
            except Exception as stats_error:
                print(f"Could not get database stats: {stats_error}")

            return True

        except Exception as e:
            print(f"An error occurred during scraping: {e}")
            print(f"Error type: {type(e).__name__}")

            try:
                print(
                    "Current URL:",
                    self.driver.current_url if self.driver else "Driver not available",
                )
                print(
                    "Page title:",
                    self.driver.title if self.driver else "Driver not available",
                )
            except:
                print("Could not get additional error information")

            return False

        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                print("Browser closed successfully.")

            except Exception as close_error:
                print(f"Error closing browser: {close_error}")

        if hasattr(self, "db_manager") and self.db_manager:
            try:
                self.db_manager.close_connection()

            except Exception as db_error:
                print(f"Error closing database connection: {db_error}")

    def process_single_post(self, content_text, post_number):
        """Process a single post and check if it already exists in database using exact matching
        Returns: 'saved' if new post saved, 'duplicate' if exact post exists, 'error' if error occurred
        """
        try:
            lines = content_text.split("\n")
            content_lines = []

            for line in lines:
                if line.strip().startswith("===") and "Content Block" in line:
                    continue
                if line.strip():
                    content_lines.append(line.strip())

            if not content_lines or len(content_lines) < 3:
                return "skipped"

            # Extract metadata from the post
            title, author, posted_time = self.extract_post_metadata_from_raw(
                content_lines
            )
            formatted_content = self.create_basic_formatted_content(content_lines)

            # Create content hash for exact duplicate detection
            content_hash = self.db_manager.create_post_hash(formatted_content)

            # Check if exact duplicate exists (no fuzzy matching)
            existing_post = self.db_manager.post_exists(content_hash)
            if existing_post:
                print(f"� EXACT DUPLICATE found for post #{post_number}: {title[:50]}...")
                print(f"   Stopping scraping - found identical content")
                return "duplicate"

            # Save new post to database
            raw_content = "\n".join(content_lines)
            success, result = self.db_manager.save_post(
                title=title,
                content=formatted_content,
                raw_content=raw_content,
                author=author,
                posted_time=posted_time,
            )

            if success:
                print(f"✅ Post #{post_number} saved: {title[:50]}...")
                return "saved"
            else:
                print(f"❌ Post #{post_number} failed to save: {result}")
                return "error"

        except Exception as e:
            print(f"❌ Error processing post #{post_number}: {e}")
            return "error"
