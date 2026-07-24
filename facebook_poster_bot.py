import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver
import pytz
import requests
import random


# --------------------------------------------------------------------------
# Config knobs you can override without touching code (handy for CI secrets)
# --------------------------------------------------------------------------

WEBSHARE_API_URL = os.environ.get("WEBSHARE_API_URL")
PROXY_HOST = os.environ.get("PROXY_HOST")
PROXY_PORT = os.environ.get("PROXY_PORT")
PROXY_USER = os.environ.get("PROXY_USER")
PROXY_PASS = os.environ.get("PROXY_PASS")

base_dir = os.path.dirname(os.path.abspath(__file__))
local_timezone = pytz.timezone("Asia/Colombo")
photo_number = random.randint(1, 10)
description_number = random.randint(1, 10)

desc_path = os.path.join(base_dir, 'poster', 'descriptions', f'{description_number}.txt')
if os.path.exists(desc_path):
    with open(desc_path, 'r', encoding="utf-8") as file:
        content = file.read()
else:
    content = "Property listing description."


def log(msg: str) -> None:
    """Timestamped print so CI logs are easy to correlate with real time."""
    stamp = datetime.now(local_timezone).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}")


def wait_until(condition_fn, timeout: int = 60, poll_interval: float = 2.0, description: str = "condition") -> bool:
    """Bounded polling helper."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if condition_fn():
                return True
        except Exception:
            pass
        time.sleep(poll_interval)
    raise TimeoutError(f"Timed out after {timeout}s waiting for: {description}")


def write_github_output(**kwargs) -> None:
    """Writes key=value pairs to GITHUB_OUTPUT."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        for key, value in kwargs.items():
            safe_value = str(value).replace("\n", " ").replace("\r", "")
            f.write(f"{key}={safe_value}\n")


@dataclass
class ListingConfig:
    number_of_bedrooms: str
    number_of_bathrooms: str
    location: str
    price: str  # digits only, e.g. "50000000"
    description: str
    fb_profile: str = os.path.join(base_dir, "profiles", "facebook_stable_session")
    photo_paths: list = field(default_factory=list)
    property_type: str = "House"
    fb_profile_dir: str = "Default"
    wait_seconds: int = 20


CONFIG = ListingConfig(
    number_of_bedrooms="4",
    number_of_bathrooms="2",
    price="5000",
    location="Wilson Street, 12 Colombo, Sri Lanka",
    description=content,
    photo_paths=[os.path.join(base_dir, "poster", "flyers", f"poster-{photo_number:02d}.png")],
)


def get_local_proxy() -> str:
    return f"socks5://{PROXY_HOST}:{PROXY_PORT}"


def get_owl_proxy() -> str:
    """Formats the Proxy string for SeleniumBase with socks5 scheme."""
    if PROXY_USER and PROXY_PASS:
        return f"{PROXY_USER}:{PROXY_PASS}@socks5://{PROXY_HOST}:{PROXY_PORT}"
    if PROXY_HOST and PROXY_PORT:
        return f"socks5://{PROXY_HOST}:{PROXY_PORT}"
    return ""


def get_webshare_proxy() -> str:
    if not WEBSHARE_API_URL:
        log("⚠️ No WEBSHARE_API_URL found in environment variables.")
        return ""

    try:
        log("🔄 Fetching private proxies from Webshare...")
        response = requests.get(WEBSHARE_API_URL, timeout=10)

        if response.status_code == 200:
            proxies = [p.strip() for p in response.text.splitlines() if p.strip()]

            if proxies:
                chosen = random.choice(proxies)
                parts = chosen.split(":")

                if len(parts) == 4:
                    ip, port, user, password = parts
                    formatted_proxy = f"{user}:{password}@socks5://{ip}:{port}"
                    log(f"✅ Successfully loaded Webshare proxy: {ip}:{port}")
                    return formatted_proxy
                else:
                    log("⚠️ Proxy format was unexpected.")

    except Exception as e:
        log(f"⚠️ Proxy fetch failed: {e}")

    return ""


def build_driver(cfg: ListingConfig):
    if not os.path.isdir(cfg.fb_profile):
        sys.exit(
            f"Chrome profile directory not found:\n  {cfg.fb_profile}\n"
            "Run facebook_profile_initializer.py once first to log in."
        )

    proxy_string = get_owl_proxy()
    max_attempts = 3

    for attempt in range(max_attempts):
        try:
            log(f"Attempting browser launch with proxy: {PROXY_HOST}:{PROXY_PORT} (Attempt {attempt + 1})")
            
            driver = Driver(
                browser="chrome",
                uc=True,
                headless2=True,
                user_data_dir=cfg.fb_profile,
                block_images=True,
                proxy=proxy_string if proxy_string else None,
            )

            driver.set_page_load_timeout(35)
            try:
                driver.get("https://api.ipify.org?format=json")
                time.sleep(1)
                ip = driver.find_element(By.TAG_NAME, "body").text.strip()
                log(f"✅ Proxy connection successful! Public IP Response: {ip}. Proceeding to Facebook...")
                return driver
            except Exception as e:
                log(f"❌ Proxy test failed on attempt {attempt + 1}/{max_attempts}: {e}")
                driver.quit()
                time.sleep(3)
                continue

        except Exception as e:
            if "already in use" in str(e).lower():
                sys.exit("❌ Chrome is already running with this profile. Close other Chrome windows.")
            log(f"⚠️ Driver initialization error on attempt {attempt + 1}/{max_attempts}: {e}")
            time.sleep(3)

    sys.exit("❌ All proxy connection attempts failed.")


def set_text_via_js(driver: webdriver.Chrome, element, text: str) -> None:
    tag = element.tag_name.lower()
    setter_class = "HTMLTextAreaElement" if tag == "textarea" else "HTMLInputElement"
    driver.execute_script(
        f"""
        var el = arguments[0];
        var value = arguments[1];
        var setter = Object.getOwnPropertyDescriptor(window.{setter_class}.prototype, 'value').set;
        setter.call(el, value);
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        """,
        element,
        text,
    )


def safe_fill(driver: webdriver.Chrome, wait: WebDriverWait, xpath: str, value: str, field_name: str) -> bool:
    try:
        el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        el.click()
        time.sleep(random.randint(0, 2))
        set_text_via_js(driver, el, value)
        log(f"  [ok] {field_name} filled")
        return True
    except TimeoutException:
        log(f"  [FAIL] Could not find '{field_name}' field (timed out).")
        return False
    except Exception as e:
        log(f"  [FAIL] Error filling '{field_name}': {e}")
        return False


def select_first_suggestion(driver: webdriver.Chrome, wait: WebDriverWait, xpath: str, value: str, field_name: str) -> bool:
    try:
        el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        el.click()
        time.sleep(1)
        el.clear()
        for char in value:
            el.send_keys(char)
            time.sleep(0.05)

        first_suggestion = wait.until(EC.element_to_be_clickable((By.XPATH, '//ul[@role="listbox"]//li[1]')))
        first_suggestion.click()
        time.sleep(1)
        log(f"  [ok] {field_name} filled and first suggestion selected")
        return True
    except TimeoutException:
        log(f"  [FAIL] Could not find '{field_name}' field or its suggestion dropdown (timed out).")
        return False
    except Exception as e:
        log(f"  [FAIL] Error filling '{field_name}': {e}")
        return False


def select_listing_type_for_rent(wait: WebDriverWait, driver: webdriver.Chrome) -> bool:
    dropdown = driver.find_elements(
        By.XPATH, "//span[contains(text(), 'Property for sale or to let')]/ancestor::*[@role='combobox'][1]"
    )
    if not dropdown:
        log("  [skip] No sale/rent selector on this page variant — nothing to select.")
        return True

    try:
        dropdown = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[contains(text(), 'Property for sale or to let')]/ancestor::*[@role='combobox'][1]")
            )
        )
        dropdown.click()
        time.sleep(1)

        option_candidates = ["Rent", "For rent", "for rent"]
        for label in option_candidates:
            opts = driver.find_elements(By.XPATH, f"//div[@role='option']//span[normalize-space()='{label}']")
            if opts:
                wait.until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[@role='option']//span[normalize-space()='{label}']"))
                ).click()
                time.sleep(1)
                log(f"  [ok] Listing type set to '{label}'")
                return True

        all_opts = driver.find_elements(By.XPATH, "//div[@role='option']")
        seen = [o.text for o in all_opts]
        log(f"  [info] No 'Rent' option found (seen: {seen}). Leaving default selection as-is.")
        driver.execute_script("document.activeElement.blur();")
        return True

    except TimeoutException:
        log("  [FAIL] Dropdown appeared present but wasn't clickable in time.")
        return False
    except ElementClickInterceptedException:
        log("  [FAIL] Dropdown click was blocked by another element.")
        return False
    except Exception as e:
        log(f"  [FAIL] Error selecting listing type: {e}")
        return False


def click_with_fallback(driver, element):
    try:
        element.click()
        time.sleep(1)
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


def select_property_subtype(wait: WebDriverWait, driver: webdriver.Chrome, property_type: str = "House") -> bool:
    try:
        try:
            WebDriverWait(driver, 3).until(EC.invisibility_of_element_located((By.XPATH, "//div[@role='option']")))
        except TimeoutException:
            pass

        label_xpath = (
            "//span[normalize-space()='Property type' "
            "or normalize-space()='Type of property for rent' "
            "or normalize-space()='Type of property for sale']"
            "/ancestor::*[@role='combobox'][1]"
        )

        dropdown = wait.until(EC.presence_of_element_located((By.XPATH, label_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", dropdown)
        time.sleep(0.5)
        click_with_fallback(driver, dropdown)
        time.sleep(1)

        option = wait.until(
            EC.presence_of_element_located((By.XPATH, f"//div[@role='option']//span[normalize-space()='{property_type}']"))
        )
        click_with_fallback(driver, option)
        log(f"  [ok] Property type set to '{property_type}'")
        return True

    except TimeoutException:
        all_opts = driver.find_elements(By.XPATH, "//div[@role='option']")
        log(f"  [FAIL] Could not find/click '{property_type}' option. Options seen (if any): {[o.text for o in all_opts]}")
        return False
    except ElementClickInterceptedException:
        log("  [FAIL] Dropdown click was blocked even after fallback attempt.")
        return False
    except Exception as e:
        log(f"  [FAIL] Error selecting property subtype: {e}")
        return False


def upload_photos(wait: WebDriverWait, photo_paths: list) -> bool:
    if not photo_paths:
        log("  [skip] No photos configured")
        return True

    missing = [p for p in photo_paths if not os.path.isfile(p)]
    if missing:
        for p in missing:
            log(f"  [FAIL] Photo file not found: {p}")
        return False

    try:
        uploader = wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file' and @accept='image/*,image/heif,image/heic']"))
        )
        for i, photo in enumerate(photo_paths):
            abs_path = os.path.abspath(photo)
            log(f"  [processing] Uploading photo {i+1}/{len(photo_paths)}: {abs_path}")
            uploader.send_keys(abs_path)
            time.sleep(1.5)

        log(f"  [ok] {len(photo_paths)} photo(s) submitted for upload successfully")
        time.sleep(2)
        return True

    except TimeoutException:
        log("  [FAIL] Could not find the photo upload input.")
        return False


def click_through_to_publish_or_update(driver: webdriver.Chrome, wait: WebDriverWait, state: str, max_next_clicks: int = 3) -> None:
    if state == 'Publish':
        for i in range(max_next_clicks):
            try:
                next_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Next')]"))
                )
            except TimeoutException:
                log(f"  [info] No more 'Next' button found after {i} click(s) — assuming final review page.")
                break
            click_with_fallback(driver, next_button)
            log(f"  [ok] Clicked 'Next' ({i + 1}/{max_next_clicks})")
            time.sleep(2)
    try:
        publish_or_Update_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(),'{state}')]"))
        )
        os.makedirs(os.path.join(base_dir, "screenshots"), exist_ok=True)
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{state}_page.png"))
        click_with_fallback(driver, publish_or_Update_button)
        log(f"  [ok] Clicked '{state}'")
    except TimeoutException:
        raise TimeoutException(
            f"Could not find '{state}' button after clicking through the form."
        )


def edit_previous_listing_if_present(driver: webdriver.Chrome, wait: WebDriverWait, cfg) -> None:
    edit_results = {}
    os.makedirs(os.path.join(base_dir, "screenshots"), exist_ok=True)
    
    nothing = driver.find_elements(by="xpath", value="//*[text()='When you start selling, your listings will appear here.']")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page.png"))
    if nothing:
        log("No previous listing found — nothing to edit.")
        return True

    wait_until(
        lambda: driver.find_elements(by="xpath", value="//h1[contains(text(),'Selling')]"),
        timeout=15,
        description="'Selling' page to load",
    )
    log("Step 0: Editing previous listing")

    more_options = driver.find_elements(by="xpath", value="(//div[@aria-label='More options for 4 beds 2 baths House'])[1]")
    if not more_options:
        log("  [skip] Could not locate the previous listing's options menu — skipping edit.")
        return True
    more_options[0].click()
    time.sleep(2)
    edit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//*[text()='Edit listing']"))
    )
    click_with_fallback(driver, edit_button)

    log("Step 1: Edit description")
    wait_until(
        lambda: driver.find_elements(by="xpath", value="//*[text()='Edit listing']"),
        timeout=15,
        description="'Edit listing' menu item",
    )
    
    edit_results["description"] = safe_fill(
        driver, wait, "//span[contains(text(), 'Rental description') or contains(text(), 'description')]/ancestor::label//textarea",
        cfg.description, "Description",
    )

    log("Step 2: Edit photos")
    remove_pics = driver.find_elements(by="xpath", value='//div[@aria-label="Remove photo from listing"]//*[local-name()="svg"]')
    for remove_pic in remove_pics:
        remove_pic.click()
        time.sleep(1)
    edit_results["photos"] = upload_photos(wait, cfg.photo_paths)

    if not edit_results["photos"]:
        log("❌ Aborting edit — required photo failed to upload.")
        return False

    log("=" * 60)
    log("Step 3: Update")
    click_through_to_publish_or_update(driver, wait, 'Update')
    log("SUMMARY")
    for step, ok in edit_results.items():
        log(f"  {'OK  ' if ok else 'FAIL'} - {step}")
    log("=" * 60)
    return True


def main() -> int:
    cfg = CONFIG
    log("Launching Chrome with your profile...")
    driver = build_driver(cfg)
    wait = WebDriverWait(driver, cfg.wait_seconds)
    results = {}
    succeeded = False

    try:
        driver.get("https://web.facebook.com/marketplace/you/selling?_rdc=1&_rdr#")
        time.sleep(3)
        
        if "login" in driver.current_url.lower():
            log("❌ Redirected to login page. Session expired or invalid.")
            sys.exit(99)

        try:
            nothing = edit_previous_listing_if_present(driver, wait, cfg)
        except TimeoutError as e:
            log(f"⚠️ {e} — continuing to create the new listing anyway.")
            nothing = True

        if nothing:
            driver.get("https://web.facebook.com/marketplace/create/rental")
            os.makedirs(os.path.join(base_dir, "screenshots"), exist_ok=True)
            driver.save_screenshot(os.path.join(base_dir, "screenshots", "rental_page.png"))
            
            wait_until(
                lambda: driver.find_elements(by="xpath", value="//span[contains(text(),'Number of bedrooms')] or //input"),
                timeout=30,
                description="marketplace 'create rental' form to load",
            )

            log("Step 1: Listing type")
            results["listing_type"] = select_listing_type_for_rent(wait, driver)

            log("Step 1b: Property type")
            results["property_type"] = select_property_subtype(wait, driver, cfg.property_type)

            log("Step 2: Number of bedrooms")
            results["number_of_bedrooms"] = safe_fill(
                driver, wait, "//span[contains(text(), 'Number of bedrooms')]/ancestor::label//input",
                cfg.number_of_bedrooms, "Number of bedrooms",
            )

            log("Step 3: Number of bathrooms")
            results["number_of_bathrooms"] = safe_fill(
                driver, wait, "//span[contains(text(), 'Number of bathrooms')]/ancestor::label//input",
                cfg.number_of_bathrooms, "Number of bathrooms",
            )

            log("Step 4: Price")
            results["price"] = safe_fill(
                driver, wait, "//span[contains(text(), 'Price')]/ancestor::label//input", cfg.price, "Price",
            )

            log("Step 5: Description")
            results["description"] = safe_fill(
                driver, wait,
                "//span[contains(text(), 'Rental description') or contains(text(), 'description')]/ancestor::label//textarea",
                cfg.description, "Description",
            )

            log("Step 6: Location")
            results["location"] = select_first_suggestion(
                driver, wait, "//input[@role='combobox' and @aria-autocomplete='list' and not(@placeholder)]",
                cfg.location, "Location",
            )

            log("Step 7: Photos")
            results["photos"] = upload_photos(wait, cfg.photo_paths)

            if not results["photos"]:
                log("❌ Aborting — required photo failed to upload. Not attempting submission.")
                raise RuntimeError("Photo upload failed; aborting before submission.")

            log("Step 8: Submission")
            click_through_to_publish_or_update(driver, wait, 'Publish')

            log("=" * 60)
            log("SUMMARY")
            for step, ok in results.items():
                log(f"  {'OK  ' if ok else 'FAIL'} - {step}")
            log("=" * 60)

        try:
            wait_until(
                lambda: driver.find_elements(by="xpath", value="//h1[contains(text(),'Selling')]"),
                timeout=30,
                description="listing to finish publishing",
            )
            succeeded = True
            log("Published.")
        except TimeoutError as e:
            log(f"⚠️ {e} — the listing may still have gone through; check the screenshot.")

    except SystemExit as e:
        raise e
    except Exception as e:
        log(f"❌ Unhandled error: {e}")
    finally:
        try:
            os.makedirs(os.path.join(base_dir, "screenshots"), exist_ok=True)
            driver.save_screenshot(os.path.join(base_dir, "screenshots", "Submission_page.png"))
        except Exception as e:
            log(f"⚠️ Could not save final screenshot: {e}")

        try:
            driver.quit()
        except Exception:
            pass

        published_time = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
        status_label = "published" if succeeded else "FAILED to publish"

        write_github_output(
            poster_number=photo_number,
            published_time=published_time,
            status=status_label,
        )
        log(f"Run finished — {status_label} at {published_time}")

        return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())