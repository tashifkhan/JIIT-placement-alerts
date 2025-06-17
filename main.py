import dotenv
import time
import os

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


dotenv.load_dotenv()
USER_ID = os.getenv("USER_ID", "default_user_id")
PASSWORD = os.getenv("PASSWORD", "default_password")


PORTAL_URL = "https://app.joinsuperset.com/students/login"


# Configure Chrome options
chrome_options = Options()
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

try:
    #  driver manager
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    print("ChromeDriver initialized successfully!")

except Exception as e:
    print(f"Failed to initialize Chrome driver: {e}")
    print("Trying fallback approach...")

    # Fallback: try without webdriver-manager
    try:
        driver = webdriver.Chrome(options=chrome_options)
        print("ChromeDriver initialized with fallback!")

    except Exception as e2:
        print(f"All attempts failed: {e2}")
        print("Please check your Chrome browser installation")
        exit(1)


# login form
# input id=":r3:"      id
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
    driver.get(PORTAL_URL)

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, ":r3:")))

    print("Page loaded successfully!")
    print("Found login elements:")
    username_field = driver.find_element(By.ID, ":r3:")
    password_field = driver.find_element(By.ID, ":r2:")

    print(
        f"Username field: {username_field.get_attribute('placeholder') or 'No placeholder'}"
    )
    print(
        f"Password field: {password_field.get_attribute('placeholder') or 'No placeholder'}"
    )

    # # Submit the form
    # driver.find_element(By.XPATH, "//button[@type='submit']").click()

    # Wait for the page to load after login
    time.sleep(5)

except Exception as e:
    print(f"An error occurred: {e}")

finally:

    if "driver" in locals():
        driver.quit()
        print("Browser closed successfully.")
