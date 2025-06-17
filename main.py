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


dotenv.load_dotenv()
USER_ID = os.getenv("USER_ID", "default_user_id")
PASSWORD = os.getenv("PASSWORD", "default_password")


PORTAL_URL = "https://app.joinsuperset.com/students/login"


chrome_options = ChromeOptions()
# chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-plugins")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)
chrome_options.add_argument("--window-size=660,1080")
chrome_options.add_argument(
    "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@contextmanager
def timeout(duration):

    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {duration} seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(duration)

    try:
        yield

    finally:
        signal.alarm(0)


def init_chrome_driver():
    try:
        print("Downloading/setting up ChromeDriver...")
        with timeout(30):
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            print("ChromeDriver initialized successfully!")
            return driver

    except TimeoutError:
        print("ChromeDriver initialization timed out")

    except Exception as e:
        print(f"Failed to initialize Chrome driver with webdriver-manager: {e}")

    try:
        print("Trying Chrome without webdriver-manager...")
        with timeout(15):
            driver = webdriver.Chrome(options=chrome_options)
            print("ChromeDriver initialized with fallback!")
            return driver

    except TimeoutError:
        print("Chrome fallback initialization timed out")

    except Exception as e2:
        print(f"Chrome fallback also failed: {e2}")

    return None


def init_firefox_driver():
    try:
        print("Setting up Firefox driver...")
        firefox_options = FirefoxOptions()
        # firefox_options.add_argument("--headless")

        with timeout(30):
            service = FirefoxService(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=firefox_options)
            print("Firefox driver initialized successfully!")
            return driver

    except TimeoutError:
        print("Firefox initialization timed out")

    except Exception as e:
        print(f"Failed to initialize Firefox driver: {e}")

    return None


driver = None
print("Attempting to initialize Chrome driver...")
driver = init_chrome_driver()

if driver is None:
    print("Chrome failed, trying Firefox...")
    driver = init_firefox_driver()

if driver is None:
    print("Both Chrome and Firefox initialization failed!")
    print("Please ensure you have either Chrome or Firefox installed.")
    exit(1)


# login form
# input id=":r1:"      id
# input id=":r2:'      pass

# login button
# <button class="MuiButton-root MuiButton-contained MuiButton-containedPrimar-blue-500 text-white !p-2 !rounded Imt-2 !w-full css-184qn08" tabindex="0" type="submit">@

#  div containg thr job posts
# <div class="px-5 pt-5 pb-0">

#  show moew / less button
# ‹button class="MuiButton-root MuiButton-text MuiButton-textPrimary MuiButto..root !text-s !mt-3 !cursor-pointer !text-center css-1drph4l" tabindex="0" type="button">


#  all content in <p> tags --> option 1 extarct text from all <p> tags
#                          --> option 2 extract text from all <div> using htmltotext into md


# use that md to send to telegram

try:
    print(f"Navigating to: {PORTAL_URL}")
    driver.get(PORTAL_URL)
    print("Page request sent, waiting for elements...")

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    print("Page body loaded!")

    print(f"Page title: {driver.title}")

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, ":r1:")))
        print("Login elements found!")

        username_field = driver.find_element(By.ID, ":r1:")
        password_field = driver.find_element(By.ID, ":r2:")

        print(
            f"Username field: {username_field.get_attribute('placeholder') or 'No placeholder'}"
        )
        print(
            f"Password field: {password_field.get_attribute('placeholder') or 'No placeholder'}"
        )

        username_field.send_keys(USER_ID)
        password_field.send_keys(PASSWORD)

        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        print("Login button clicked!")

        print("Waiting for login to complete...")
        time.sleep(3)
        print("Login attempt made, checking for success...")

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.px-5.pt-5.pb-0"))
        )
        print("Login successful, job posts section loaded!")

        print("Looking for scrollable inner containers...")

        scrollable_container = None
        try:
            containers = driver.find_elements(
                By.CSS_SELECTOR, "div[class*='overflow'], div[style*='overflow']"
            )

            for container in containers:

                scroll_height = driver.execute_script(
                    "return arguments[0].scrollHeight", container
                )
                client_height = driver.execute_script(
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
                driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight",
                    scrollable_container,
                )
                time.sleep(2)

                try:
                    show_more_buttons = []
                    buttons_by_text = driver.find_elements(
                        By.XPATH,
                        "//button[contains(text(), 'See More') or contains(text(), 'see more')]",
                    )
                    show_more_buttons.extend(buttons_by_text)

                    mui_buttons = driver.find_elements(
                        By.CSS_SELECTOR,
                        "button.MuiButton-root.MuiButton-text.MuiButton-textPrimary",
                    )
                    for btn in mui_buttons:
                        if "see more" in btn.text.lower():
                            show_more_buttons.append(btn)

                    css_buttons = driver.find_elements(
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
                                    driver.execute_script(
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

                current_scroll_top = driver.execute_script(
                    "return arguments[0].scrollTop", scrollable_container
                )
                scroll_height = driver.execute_script(
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

        selectors_to_try = [
            "div.px-5.pt-6.pb-0",
            "div.px-5.pt-5.pb-0",
            "div[class*='px-5'][class*='pt-'][class*='pb-0']",
            "div.px-5",
        ]

        content_elements = []
        for selector in selectors_to_try:
            print(f"Trying selector: {selector}")
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                print(f"Found {len(elements)} elements with selector: {selector}")
                content_elements = elements
                break

        if not content_elements:
            print(
                "No content elements found with any selector, trying to find all divs with px-5 class..."
            )
            content_elements = driver.find_elements(
                By.CSS_SELECTOR, "div[class*='px-5']"
            )
            print(f"Found {len(content_elements)} elements with px-5 class")

        all_content = []
        for i, element in enumerate(content_elements):
            try:
                element_text = element.text.strip()
                if element_text and len(element_text) > 50:
                    all_content.append(f"=== Content Block {i+1} ===\n{element_text}\n")
                    print(
                        f"Extracted content from element {i+1} ({len(element_text)} characters)"
                    )

            except Exception as element_error:
                print(f"Error extracting content from element {i+1}: {element_error}")

        with open("page_content.txt", "w", encoding="utf-8") as f:
            if all_content:
                f.write("\n".join(all_content))
                print(
                    f"Successfully wrote {len(all_content)} content blocks to page_content.txt"
                )

            else:
                f.write("No substantial content found in matching elements")
                print("No substantial content found to write")

        with open("job_posts.txt", "w", encoding="utf-8") as f:
            if all_content:
                content_text = "\n\n".join(all_content)
                f.write(content_text)

            else:
                f.write("No content extracted")

        with open("job_posts_page.txt", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

    except Exception as login_error:
        print(f"Could not find login elements: {login_error}")
        print("Page title:", driver.title)
        print("Current URL:", driver.current_url)

        try:
            driver.save_screenshot("debug_screenshot.png")
            print("Screenshot saved as debug_screenshot.png")

        except:
            pass

    time.sleep(3)

except Exception as e:
    print(f"An error occurred during navigation: {e}")
    print(f"Error type: {type(e).__name__}")

    try:
        print("Current URL:", driver.current_url if driver else "Driver not available")
        print("Page title:", driver.title if driver else "Driver not available")

    except:
        print("Could not get additional error information")

finally:
    if driver:
        try:
            driver.quit()
            print("Browser closed successfully.")

        except Exception as close_error:
            print(f"Error closing browser: {close_error}")
