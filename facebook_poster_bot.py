import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException
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
PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = os.environ.get("PROXY_PORT", "10808")
# WHATSAPP_NOTIFY_PHONE = os.environ.get("WHATSAPP_NOTIFY_PHONE")

base_dir = os.path.dirname(os.path.abspath(__file__))
local_timezone = pytz.timezone("Asia/Colombo")
photo_number = random.randint(1, 10)
description_number = random.randint(1, 10)

with open(os.path.join(base_dir,'poster','descriptions',f'{description_number}.txt'),'r',encoding="utf-8") as file:
    content = file.read()
TARGET_GROUPS = [
    "Kolonnawa / Dematagoda / Wellampitiya Community",
    "Colombo Rent houses Apartment Annex",
    "House Rent for Around Colombo - කුලියට නිවසක් කොළඹ අවටින්",
    "wattala house for sale and rent",
    "House, Rooms & Annex for Rent - ඉක්මනින් නිවාස කුලියට",
    "Colombo Apartments - Rent",
    "කුලියට නිවසක් :: house for rent",
    "House for rent in kolonnawa",
    "House, Annex & Rooms For Rent - ඉක්මනින් හොයාගන්න",
    "බත්තරමුල්ල කුලී ගෙවල් - Battaramulla Rent Home or Annex",
    "House for rent wattala",
    "Sri Lanka Land & Property Exchange",
    "Rent/sale/lease/buy/kolonnawa/ Colombo/Houses",
    "ඉඩම් ගෙවල් විකිනීම කුලියට දීම Gewal idam selling rent home",
    "ඉඩම් ගෙවල් වාහන ලාභෙට Land | House | Vehicle for Sale Sri Lanka 🇱🇰",
    "Houses for Rent - කුලියට ගෙයක්",
    "කලුතර / කොළඹ / ගම්පහ ඉඩම් හා නිවාස - House & Land for sale",
    "නිවාස 🏠️,ඉඩම්,🏘️House,🏡️Lands අඩුවට කුලියට,බද්දට,විකිනීමට",
    "ikman.lk (Rent & Lease & Sale Property)",
    "Land and House for Sale to Buy ඉඩම් සහ නිවාස විකිණීමට මිලදී ගැනීමට",
    "Ceylon Property Hub 🏘️ | Buy • Sell • Rent | නිවාස ඉඩකඩම් විකිණීමට",
    "නිවාස ඉඩම් ව්කිනිමට කුලියට දිමට සහ ගැනිමට සොයන්නො",
    "House Lease and Rent in Colombo",
    "dematagoda/maradana/maligawatta/grandpass/borella/kotahena/modara/narahenpi",
    "House For Sale.. මන්දිරය නිවාස .... ඔබේ නිවස සොයාගන්න...",
    "ඉඩම් සහ ගෙවල් විකිණීමට - Lands and Houses for Sale",
    "NEGOMBO HOUSE / LANDS FOR SALE",
    "කුලියට නිවසක් | House For Rent - Sri Lanka",
    "Dehiwala - Mount Lavinia Community දෙහිවල ගල්කිස්ස අපි",
    "නිවාස සහ ඉඩම් විකිණී⁣මේ සහ මිලදී ගැනීමේ සමූහය-Real Estate In Sri Lanka",
    "house and land sale නිවාස ඉඩකඩම් විකිනීමට"
]

def auto_crosspost_to_target_groups(driver: webdriver.Chrome, target_group_names: list , final_target_count: int = 20) -> int:
    """
    Selects groups from a specific list first. If any are missing,
    it automatically clicks remaining available groups to guarantee 
    exactly 20 total selections.
    """
    selected_count = 0
    clicked_element_ids = set()  # Prevent double-clicking individual row elements
    already_selected_names = set()
    
    scroll_attempts = 0
    max_scroll_attempts = 20
    
    print(f"[*] Initializing group selector. Aiming for exactly {final_target_count} groups...")
    
    # Generic row selector for Facebook group list items
    rows_xpath = "//div[@role='listitem' or @role='checkbox' or contains(@class, 'x1n2onr6')]"
    
    # ================= SMART DYNAMIC WAIT (MAX 10 SECONDS) =================
    try:
        print("[*] Waiting for groups to render (Max 10s)...")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, rows_xpath)))
        time.sleep(1.0)  # Brief micro-buffer for list stability
        print("[ok] Groups detected on screen. Commencing selection...")
    except TimeoutException:
        # ================= BLANK SCREEN SAFEGUARD FALLBACK =================
        print("[!] Timeout: Groups failed to appear within 10 seconds (Blank panel detected).")
        print("[*] Safeguard Mode: Skipping group selection and publishing directly...")
        
        try:
            publish_btn_xpath = "//div[@role='button' and @aria-label='Publish'] | //span[text()='Publish']/ancestor::div[@role='button']"
            publish_btn = driver.find_element(By.XPATH, publish_btn_xpath)
            driver.execute_script("arguments.scrollIntoView({block: 'center'});", publish_btn)
            time.sleep(0.5)
            try:
                publish_btn.click()
            except Exception:
                driver.execute_script("arguments.click();", publish_btn)
            print("[ok] Safeguard Success: Listing submitted directly to Marketplace.")
        except Exception as e:
            print(f"[FAIL] Could not click final Publish button: {e}")
            
        return 0
    # Locate the internal scrollable pane inside the modal wrapper
    try:
        scroll_container = driver.find_element(By.XPATH, "//div[@role='dialog']//div[contains(@class, 'x1r93jhi')]")
    except NoSuchElementException:
        scroll_container = driver.find_element(By.TAG_NAME, "body")

    # ================= PHASE 1: TARGET SPECIFIC LIST =================
    print("[*] Phase 1: Searching for your specific listed groups...")
    for group_name in target_group_names:
        if selected_count >= final_target_count:
            break
            
        # Precise text match anchoring strategy
        xpath = f"//span[text()='{group_name}']/ancestor::div[@role='listitem' or @role='checkbox' or contains(@class, 'x1n2onr6')]"
        
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            if elements:
                group_row = elements[0]
                clicked_element_ids.add(group_row.id)  # Lock element ID for phase 2
                
                checkbox_trigger = group_row.find_element(By.XPATH, ".//div[@role='checkbox'] | .//input")
                is_checked = checkbox_trigger.get_attribute("aria-checked") == "true"
                
                if not is_checked:
                    driver.execute_script("arguments.scrollIntoView({block: 'center', behavior: 'smooth'});", checkbox_trigger)
                    time.sleep(0.3)
                    
                    try:
                        checkbox_trigger.click()
                    except Exception:
                        driver.execute_script("arguments.click();", checkbox_trigger)
                        
                    selected_count += 1
                    print(f"  [+] Specific Match: '{group_name}' ({selected_count}/{final_target_count})")
                    time.sleep(random.uniform(0.5, 0.8))
                
                already_selected_names.add(group_name)
            else:
                # Scroll a fixed step to uncover lazy loading options if list target wasn't in frame
                driver.execute_script("arguments.scrollTop += 300;", scroll_container)
                time.sleep(0.8)
                
        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    # ================= PHASE 2: AUTO-FILL FALLBACK =================
    if selected_count < final_target_count:
        gap = final_target_count - selected_count
        print(f"[!] Warning: Missing {gap} groups from your list. Activating auto-fill fallback...")
        
        while selected_count < final_target_count and scroll_attempts < max_scroll_attempts:
            visible_rows = driver.find_elements(By.XPATH, rows_xpath)
            
            for row in visible_rows:
                if selected_count >= final_target_count:
                    break
                    
                if row.id in clicked_element_ids:
                    continue  # Skip groups we already touched or processed in Phase 1
                    
                try:
                    checkbox_trigger = row.find_element(By.XPATH, ".//div[@role='checkbox'] | .//input")
                    is_checked = checkbox_trigger.get_attribute("aria-checked") == "true"
                    
                    if not is_checked:
                        driver.execute_script("arguments.scrollIntoView({block: 'center'});", checkbox_trigger)
                        time.sleep(0.3)
                        
                        try:
                            checkbox_trigger.click()
                        except Exception:
                            driver.execute_script("arguments.click();", checkbox_trigger)
                            
                        selected_count += 1
                        print(f"  [+] Fallback Selection: Group Row #{selected_count} ({selected_count}/{final_target_count})")
                        time.sleep(random.uniform(0.5, 0.8))
                        
                    clicked_element_ids.add(row.id)
                    
                except Exception:
                    continue
            
            # Scroll down to pull the next block of groups from the backend server
            driver.execute_script("arguments.scrollTop += 450;", scroll_container)
            time.sleep(1.8)
            scroll_attempts += 1

    print(f"[*] Finished. Total selected groups: {selected_count}/{final_target_count}")
    return selected_count
def log(msg: str) -> None:
    """Timestamped print so CI logs are easy to correlate with real time."""
    stamp = datetime.now(local_timezone).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}")


def wait_until(condition_fn, timeout: int = 60, poll_interval: float = 2.0, description: str = "condition") -> bool:
    """Bounded polling helper. Replaces bare `while True:` loops that could
    hang forever if a page never reaches the expected state.
    Returns True if condition_fn() returned truthy before the timeout.
    Raises TimeoutError otherwise."""
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
    """Writes key=value pairs to GITHUB_OUTPUT so the workflow step can
    read them via steps.<id>.outputs.<key>. No-ops locally (outside CI)
    where GITHUB_OUTPUT isn't set."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        for key, value in kwargs.items():
            # Flatten to one line — GITHUB_OUTPUT doesn't handle raw newlines safely
            safe_value = str(value).replace("\n", " ").replace("\r", "")
            f.write(f"{key}={safe_value}\n")
# class WhatsappSendMsg:
#     """Sends a WhatsApp Web notification once the listing has been posted.
#     Requires a Chrome profile in profiles/whatsapp_stable_session that has
#     already been logged in once (see whatsapp_profile_initializer.py)."""

#     def __init__(self, phone_no: str = WHATSAPP_NOTIFY_PHONE, published_time: str = "Error in time", status: str = "published"):
#         self.published_time = published_time
#         self.phone_number = phone_no
#         self.status = status

#     def main(self):
#         user_data_dir = os.path.join(base_dir, "profiles", "whatsapp_stable_session")
#         if not os.path.isdir(user_data_dir):
#             log("⚠️ WhatsApp profile not found — skipping notification.")
#             return

#         message = f"poster-{photo_number} {self.status} at {self.published_time}"
#         driver = Driver(
#             browser="Chrome",
#             uc=True,
#             headless2=True,
#             agent=(
#                 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#                 "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
#             ),
#             user_data_dir=user_data_dir,
#         )
#         try:
#             driver.get("https://web.whatsapp.com")

#             def ready_or_continue():
#                 cont_buttons = driver.find_elements(by="xpath", value='//span[contains(text(),"Continue")]')
#                 if cont_buttons:
#                     cont_buttons[0].click()
#                     return False  # keep polling; page needs a moment after the click
#                 main_pane = driver.find_elements(by="xpath", value='//div[@id="side"]')
#                 return bool(main_pane)

#             wait_until(ready_or_continue, timeout=90, poll_interval=2, description="WhatsApp Web to finish loading")

#             driver.save_screenshot(os.path.join(base_dir, "screenshots", "whatsapp_page1.png"))

#             search_box = driver.find_element(by="xpath", value="//*[@placeholder='Search or start a new chat']")
#             search_box.send_keys(f"{self.phone_number}\n")
#             time.sleep(2)

#             type_box = driver.switch_to.active_element
#             type_box.send_keys(f"{message}\n")
#             time.sleep(3)

#             checkmark_xpath = '//*[contains(@data-testid, "msg-check") or contains(@data-testid, "msg-dblcheck")]'
#             try:
#                 driver.wait_for_element_present(checkmark_xpath, timeout=15)
#                 log("✅ WhatsApp message confirmed delivered.")
#             except Exception:
#                 log("⚠️ Delivery checkmark not seen; message was likely still sent.")

#             driver.save_screenshot(os.path.join(base_dir, "screenshots", "whatsapp_page2.png"))
#         except Exception as e:
#             log(f"⚠️ WhatsApp notification failed (non-fatal): {e}")
#         finally:
#             driver.quit()
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
    price="50",
    location="Wilson Street, 12 Colombo, Sri Lanka",
    description=(
        content
    ),
    photo_paths=[os.path.join(base_dir, "poster","flyers",f"poster-{photo_number:02d}.png")],
)

def get_local_proxy() -> str:
    return f"socks5://{PROXY_HOST}:{PROXY_PORT}"


def get_webshare_proxy() -> str:
    """Fetches your private proxies from Webshare and formats them for SeleniumBase."""
    if not WEBSHARE_API_URL:
        log("⚠️ No WEBSHARE_API_URL found in environment variables.")
        return ""
        
    try:
        log("🔄 Fetching private proxies from Webshare...")
        response = requests.get(WEBSHARE_API_URL, timeout=10)
        
        if response.status_code == 200:
            # Webshare returns a text file separated by newlines
            proxies = [p.strip() for p in response.text.splitlines() if p.strip()]
            
            if proxies:
                chosen = random.choice(proxies)
                # Webshare format is IP:Port:User:Pass
                parts = chosen.split(":")
                
                if len(parts) == 4:
                    ip, port, user, password = parts
                    # SeleniumBase needs format: user:pass@ip:port
                    formatted_proxy = f"{user}:{password}@{ip}:{port}"
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

    max_attempts = 3
    
    for attempt in range(max_attempts):
        proxy_string = get_local_proxy()
        
        if not proxy_string:
            log("➡️ Proceeding without a proxy (using the runner's own IP)...")
            proxy_string = None # Let it run normally if proxy fails
        else:
            log(f"📡 Attempt {attempt + 1}/{max_attempts}: testing Webshare proxy...")

        try:
            # 🚀 Switch from webdriver.Chrome to SeleniumBase Driver!
            # It automatically bypasses bot detection AND handles proxy passwords
            driver = Driver(
                browser="chrome",
                uc=True,                  # Undetected mode (bypasses Facebook bot checks)
                headless=True,            # Runs invisibly in GitHub Actions
                user_data_dir=cfg.fb_profile,
                proxy=proxy_string,      # Automatically handles User:Pass!
                block_images=True 
               )

            # Give it a quick test to make sure the proxy connects
            driver.set_page_load_timeout(15)
            if proxy_string:
                try:
                    driver.get("https://google.com")
                    log("✅ Proxy connection successful! Proceeding to Facebook...")
                    return driver
                except Exception as e:
                    driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
                    log("❌ Selected proxy timed out. Retrying with a different one...")
                    driver.quit()
                    continue
            
            return driver

        except Exception as e:
            if "already in use" in str(e).lower():
                sys.exit("❌ Chrome is already running with this profile. Close other Chrome windows.")
            driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
            log(f"⚠️ Driver initialization error on attempt {attempt + 1}: {e}")

    sys.exit("❌ All connection attempts failed. Script terminated.")


def set_text_via_js(driver: webdriver.Chrome, element, text: str) -> None:
    """Set a textarea/input's value via JS, using the native value setter so
    React (which controls Facebook's form) picks up the change. This bypasses
    ChromeDriver's send_keys(), which cannot transmit characters outside the
    Basic Multilingual Plane (most emoji) and throws
    'unknown error: ChromeDriver only supports characters in the BMP'."""
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
        time.sleep(random.randint(0,5))
        set_text_via_js(driver, el, value)
        log(f"  [ok] {field_name} filled")
        return True
    except TimeoutException as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log(f"  [FAIL] Could not find '{field_name}' field (timed out). "
            f"Facebook may have changed the page layout, or the form hasn't loaded that field yet.")
        return False
    except Exception as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log(f"  [FAIL] Error filling '{field_name}': {e}")
        return False


def select_first_suggestion(driver: webdriver.Chrome, wait: WebDriverWait, xpath: str, value: str, field_name: str) -> bool:
    try:
        el = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        el.click()
        time.sleep(random.randint(0,5))
        el.clear()
        for char in value:
            el.send_keys(char)
            time.sleep(0.05)
        time.sleep(3)
        first_suggestion = wait.until(EC.element_to_be_clickable((By.XPATH, '//ul[@role="listbox"]//li[1]')))
        first_suggestion.click()
        time.sleep(random.randint(0,5))
        log(f"  [ok] {field_name} filled and first suggestion selected")
        return True
    except TimeoutException as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log(f"  [FAIL] Could not find '{field_name}' field or its suggestion dropdown (timed out).")
        return False
    except Exception as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log(f"  [FAIL] Error filling '{field_name}': {e}")
        return False

def select_listing_type_for_rent(wait: WebDriverWait, driver: webdriver.Chrome) -> bool:
    try:
        dropdown = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[contains(text(), 'Property for sale or to let')]/ancestor::*[@role='combobox'][1]")
            )
        )
        dropdown.click()
        time.sleep(1)

        option_candidates = ["Rent","For rent","for rent"]
        for label in option_candidates:
            opts = driver.find_elements(By.XPATH, f"//div[@role='option']//span[normalize-space()='{label}']")
            if opts:
                wait.until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[@role='option']//span[normalize-space()='{label}']"))
                ).click()
                time.sleep(random.randint(0,5))
                log(f"  [ok] Listing type set to '{label}'")
                return True

        all_opts = driver.find_elements(By.XPATH, "//div[@role='option']")
        log(f"  [debug] Dropdown opened but no known label matched. Options seen: {[o.text for o in all_opts]}")
        return False

    except TimeoutException as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log("  [FAIL] 'Property for sale or to let' dropdown not clickable in time.")
        return False
    except ElementClickInterceptedException as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log("  [FAIL] Dropdown click was blocked by another element.")
        return False
    except Exception as e:
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{e}.png"))
        log(f"  [FAIL] Error selecting listing type: {e}")
        return False


def click_with_fallback(driver, element):
    try:
        element.click()
        time.sleep(random.randint(0,5))
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


def select_property_subtype(wait: WebDriverWait, driver: webdriver.Chrome, property_type: str = "House") -> bool:
    try:
        try:
            WebDriverWait(driver, 3).until(EC.invisibility_of_element_located((By.XPATH, "//div[@role='option']")))
        except TimeoutException:
            pass

        dropdown = wait.until(
            EC.presence_of_element_located((By.XPATH, "//span[normalize-space()='Property type' or normalize-space()='Type of property for rent']/ancestor::*[@role='combobox'][1]"))
        )
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


def click_through_to_publish_or_update(driver: webdriver.Chrome, wait: WebDriverWait,state:str ='Update', max_next_clicks: int = 3,selected_groups: list = []) -> None:
    """Clicks 'Next' as many times as the form requires (Facebook's
    Marketplace flow sometimes has one review step, sometimes more),
    waiting properly for each button instead of guessing with a fixed
    sleep. Stops clicking Next once no more Next button appears, then
    waits for and clicks Publish."""
    if state =='Publish':
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
        auto_crosspost_to_target_groups(driver,target_group_names=selected_groups)
    try:
        publish_or_Update_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(),'{state}')]"))
        )
        driver.save_screenshot(os.path.join(base_dir, "screenshots", f"{state}_page.png"))
        click_with_fallback(driver, publish_or_Update_button)
        log("  [ok] Clicked 'Publish'")
    except TimeoutException:
        raise TimeoutException(
            f"Could not find '{state}' button after clicking through the form. "
            "Facebook's form may have shown a validation error or an unexpected "
            "extra step — check screenshots/Submission_page.png."
        )


def edit_previous_listing_if_present(driver: webdriver.Chrome,wait: WebDriverWait,cfg) -> None:
    """edits the previous 'For Sale' listing so the hourly re-post doesn't
    pile up duplicates. No-ops if there's nothing to edit."""
    edit_results={}
    nothing = driver.find_elements(by="xpath", value="//*[text()='When you start selling, your listings will appear here.']")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page.png"))
    if nothing:
        log("No previous listing found — nothing to edit.")
        return True

    wait_until(
        lambda: driver.find_elements(by="xpath", value="//h1[contains(text(),'Selling')]"),
        timeout=30,
        description="'Selling' page to load",
    )
    log("Step 0: Editing previous listing")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step_s0.png"))
    
    more_options = driver.find_elements(by="xpath", value="(//div[@aria-label='More options for 4 beds 2 baths House'])[1]")
    if not more_options:
        log("  [skip] Could not locate the previous listing's options menu — skipping edit.")
        return True
    more_options[0].click()
    time.sleep(3)
    edit_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//*[text()='Edit listing']"))
    )
    click_with_fallback(driver, edit_button)

    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step0.png"))

    log("Step 1: Edit description")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step1.png"))
    wait_until(
        lambda: driver.find_elements(by="xpath", value="//*[text()='Edit listing']"),
        timeout=20,
        description="'Edit listing' menu item",
    )
    textarea = driver.find_element(By.XPATH, "//span[contains(text(), 'Rental description') or contains(text(), 'description')]/ancestor::label//textarea")
    textarea.clear()
    time.sleep(1)
    edit_results["description"] = safe_fill(driver, wait,"//span[contains(text(), 'Rental description') or contains(text(), 'description')]/ancestor::label//textarea",
            cfg.description, "Description",
    )
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step1.png"))
    
    log("Step 2: Edit photos")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step2.png"))
    remove_pics =driver.find_elements(by="xpath", value='//div[@aria-label="Remove photo from listing"]//*[local-name()="svg"]')
    for remove_pic in remove_pics:
        remove_pic.click()
        time.sleep(1)
    edit_results["photos"] = upload_photos(wait, cfg.photo_paths)

    log("=" * 60)
    log("Step 3: Update")

    click_through_to_publish_or_update(driver, wait)
    log("SUMMARY")
    for step, ok in edit_results.items():
        log(f"  {'OK  ' if ok else 'FAIL'} - {step}")
    log("=" * 60)

    failed = [k for k, v in edit_results.items() if not v]
    if failed:
        log(f"{len(failed)} field(s) need manual attention: {', '.join(failed)}")
    else:
        log("All fields filled successfully edited.")
    driver.save_screenshot(os.path.join(base_dir, "screenshots", "Edit_selling_page_step2.png"))
    log("Previous listing edited.")
        
def main() -> int:
    cfg = CONFIG
    log("Launching Chrome with your profile...")
    driver = build_driver(cfg)
    wait = WebDriverWait(driver, cfg.wait_seconds)
    results = {}
    succeeded = False

    try:
        driver.get("https://www.facebook.com/marketplace/you/selling")
        driver.save_screenshot(os.path.join(base_dir, "screenshots", "edit_Selling_page.png"))
        if "login" in driver.current_url.lower():
            log("❌ Redirected to login page. Session expired or invalid. Requesting profile rebuild...")
            sys.exit(99)


        try:
            nothing = edit_previous_listing_if_present(driver,wait,cfg)
        except TimeoutError as e:
            log(f"⚠️ {e} — continuing to create the new listing anyway.")
            nothing = True
        if nothing:    
            driver.get("https://www.facebook.com/marketplace/create/rental")
            wait_until(
                lambda: driver.find_elements(by="xpath", value="//span[contains(text(),'Number of bedrooms')]"),
                timeout=30,
                description="marketplace 'create rental' form to load",
            )

            log("Step 1: Listing type")
            results["listing_type"] = select_listing_type_for_rent(wait, driver)
            time.sleep(2.5)

            log("Step 1b: Property type")
            results["property_type"] = select_property_subtype(wait, driver, cfg.property_type)
            time.sleep(2.5)

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

            log("Step 4: Location")
            results["location"] = select_first_suggestion(
                driver, wait, "//input[@role='combobox' and @aria-autocomplete='list' and not(@placeholder)]",
                cfg.location, "Location",
            )

            log("Step 5: Description")
            results["description"] = safe_fill(
                driver, wait,
                "//span[contains(text(), 'Rental description') or contains(text(), 'description')]/ancestor::label//textarea",
                cfg.description, "Description",
            )

            log("Step 6: Price")
            results["price"] = safe_fill(
                driver, wait, "//span[contains(text(), 'Price')]/ancestor::label//input", cfg.price, "Price",
            )
            driver.save_screenshot(os.path.join(base_dir, "screenshots", "price.png"))

            log("Step 7: Photos")
            results["photos"] = upload_photos(wait, cfg.photo_paths)
            
            log("Click the anonymous button")
            anonymous_btn=driver.find_element(by='xpath', value="(//span[contains(text(),'anyone')  or contains(text(),'anonymously')])[1]")
            anonymous_btn.click()

            log("Step 8: Submission")
            count = min(20, len(TARGET_GROUPS))
            selected_groups =random.sample(TARGET_GROUPS,k=count)
            click_through_to_publish_or_update(driver, wait,'Publish',selected_groups=selected_groups)
            log("=" * 60)
            log("SUMMARY")
            for step, ok in results.items():
                log(f"  {'OK  ' if ok else 'FAIL'} - {step}")
            log("=" * 60)

            failed = [k for k, v in results.items() if not v]
            if failed:
                log(f"{len(failed)} field(s) need manual attention: {', '.join(failed)}")
            else:
                log("All fields filled successfully.")

        try:
            wait_until(
                lambda: driver.find_elements(by="xpath", value="//h1[contains(text(),'Selling')]"),
                timeout=60,
                description="listing to finish publishing",
            )
            succeeded = True
            log("Published.")
        except TimeoutError as e:
            log(f"⚠️ {e} — the listing may still have gone through; check the screenshot.")

    except SystemExit as e:
        # Re-raise SystemExit so the script actually exits with the 99 status code
        raise e
    except Exception as e:
        log(f"❌ Unhandled error: {e}")
    finally:
        # SAFEGUARD: Catch errors if driver is already dead/closed
        try:
            driver.save_screenshot(os.path.join(base_dir, "screenshots", "Submission_page.png"))
        except Exception as e:
            log(f"⚠️ Could not save final screenshot (Browser might be closed): {e}")
            
        try:
            driver.quit()
        except Exception:
            pass

        published_time = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
        status_label = "published" if succeeded else "FAILED to publish"

        write_github_output(
            selected_groups =selected_groups,
            poster_number=photo_number,
            published_time=published_time,
            status=status_label,
        )
        log(f"Run finished — {status_label} at {published_time}")

        return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())