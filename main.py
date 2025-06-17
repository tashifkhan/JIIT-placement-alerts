import dotenv
import time
import os
import signal
from contextlib import contextmanager

# Selenium imports
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
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-plugins")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)
chrome_options.add_argument("--window-size=1920,1080")
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

        time.sleep(30)

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
