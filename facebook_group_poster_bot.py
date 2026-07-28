#!/usr/bin/env python3
"""
Facebook Group Poster Bot  (URL-based edition)
==============================================
Posts a random poster + description directly into ONE Facebook group per run.
"""

import json
import os
import random
import sys
import time
from datetime import datetime, date

import pytz
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver

# ─────────────────────────────────────────────────────────────────────
# Paths & runtime constants
# ─────────────────────────────────────────────────────────────────────
base_dir       = os.path.dirname(os.path.abspath(__file__))
local_timezone = pytz.timezone("Asia/Colombo")
SCREENSHOTS    = os.path.join(base_dir, "screenshots")
STATE_FILE     = os.path.join(base_dir, ".group_tracker.json")
os.makedirs(SCREENSHOTS, exist_ok=True)

PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = os.environ.get("PROXY_PORT", "10808")

# ─── Randomly pick poster image + description for this run ───────────
photo_number       = random.randint(1, 10)
description_number = random.randint(1, 10)

with open(
    os.path.join(base_dir, "poster", "descriptions", f"{description_number}.txt"),
    encoding="utf-8",
) as _fh:
    POST_DESCRIPTION = _fh.read()

POSTER_PATH = os.path.join(base_dir, "poster", "flyers", f"poster-{photo_number:02d}.png")

# ─────────────────────────────────────────────────────────────────────
# Target Facebook groups  —  DIRECT URLS (no search needed)
# ─────────────────────────────────────────────────────────────────────
TARGET_GROUPS = [
    "https://www.facebook.com/groups/3347281635431946/",
    "https://www.facebook.com/groups/369484437602681/",
    "https://www.facebook.com/groups/252729952602771/",
    "https://www.facebook.com/groups/998215060615857/",
    "https://www.facebook.com/groups/1110473696576146/",
    "https://www.facebook.com/groups/3376751779312628/",
    "https://www.facebook.com/groups/758342533900483/",
    "https://www.facebook.com/groups/698019161007962/",
    "https://www.facebook.com/groups/1040295236828015/",
    "https://www.facebook.com/groups/3293314177417926/",
    "https://www.facebook.com/groups/2614587088838165/",
    "https://www.facebook.com/groups/388416683550762/",
    "https://www.facebook.com/groups/464905197488015/",
    "https://www.facebook.com/groups/806605707066232/",
    "https://www.facebook.com/groups/865311145986357/",
    "https://www.facebook.com/groups/1454977945176885/",
    "https://www.facebook.com/groups/1291425895074789/",
    "https://www.facebook.com/groups/2982345928645904/",
    "https://www.facebook.com/groups/1196246380574780/",
    "https://www.facebook.com/groups/943062569458341/",
    "https://www.facebook.com/groups/651715026259479/",
    "https://www.facebook.com/groups/997624967920384/",
    "https://www.facebook.com/groups/717588028991805/",
    "https://www.facebook.com/groups/243559725394520/",
    "https://www.facebook.com/groups/694336761166835/",
    "https://www.facebook.com/groups/280487894082768/",
    "https://www.facebook.com/groups/729908459207984/",
    "https://www.facebook.com/groups/748138546422011/",
    "https://www.facebook.com/groups/447267004098054/",
    "https://www.facebook.com/groups/1805736339751449/",
    "https://www.facebook.com/groups/440590454604368/",
    "https://www.facebook.com/groups/2802018006761420/",
    "https://www.facebook.com/groups/735674309145618/",
    "https://www.facebook.com/groups/598319314175896/",
    "https://www.facebook.com/groups/1900241936950529/",
    "https://www.facebook.com/groups/1313948606027111/",
    "https://www.facebook.com/groups/687318265187753/",
    "https://www.facebook.com/groups/2502721233243547/",
    "https://www.facebook.com/groups/1493409651449007/",
    "https://www.facebook.com/groups/687809108737946/",
    "https://www.facebook.com/groups/811847530266654/",
    "https://www.facebook.com/groups/renthouselk/",
    "https://www.facebook.com/groups/dehiwala/",
    "https://www.facebook.com/groups/402402418691485/",
    "https://www.facebook.com/groups/270429608581198/",
]

# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    stamp = datetime.now(local_timezone).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)

# ─────────────────────────────────────────────────────────────────────
# GitHub Actions output helper
# ─────────────────────────────────────────────────────────────────────
def write_github_output(**kwargs) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            safe = str(value).replace("\n", " ").replace("\r", "")
            fh.write(f"{key}={safe}\n")

# ─────────────────────────────────────────────────────────────────────
# Daily state management
# ─────────────────────────────────────────────────────────────────────
def load_daily_state() -> dict:
    today = date.today().isoformat()
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                state = json.load(fh)
            if state.get("date") == today:
                used_count = len(state.get("used_groups", []))
                posts      = state.get("total_posts", 0)
                log(f"Today's state loaded: {used_count} groups attempted, "
                    f"{posts} successful posts.")
                return state
        except (json.JSONDecodeError, KeyError, ValueError):
            log("Corrupt state file — starting fresh.")
    log("No state found for today — creating fresh state.")
    return {"date": today, "used_groups": [], "total_posts": 0}

def save_daily_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    log("State saved.")

# ─────────────────────────────────────────────────────────────────────
# Group selection logic  (URL-based — no name filtering)
# ─────────────────────────────────────────────────────────────────────
def extract_group_id(url: str) -> str:
    """Extract the group ID / slug from a Facebook group URL for logging."""
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else url

def pick_target_group(state: dict) -> "str | None":
    used       = set(state.get("used_groups", []))
    candidates = [g for g in TARGET_GROUPS if g not in used]
    if not candidates:
        log("All eligible groups have been used today.")
        return None
    chosen = random.choice(candidates)
    log(f"Selected group ({len(used)} already used today): "
        f"{extract_group_id(chosen)}  →  {chosen}")
    return chosen

# ─────────────────────────────────────────────────────────────────────
# Browser / driver helpers
# ─────────────────────────────────────────────────────────────────────
def build_driver() -> Driver:
    profile_path = os.path.join(base_dir, "profiles", "facebook_stable_session")
    if not os.path.isdir(profile_path):
        sys.exit(
            f"Chrome profile not found:\n  {profile_path}\n"
            "Run facebook_profile_initializer.py first."
        )
    proxy = f"socks5://{PROXY_HOST}:{PROXY_PORT}"
    return Driver(
        browser="chrome",
        uc=True,
        headless=True,
        user_data_dir=profile_path,
        proxy=proxy,
        block_images=True,
    )

def sc(driver, name: str) -> None:
    try:
        driver.save_screenshot(os.path.join(SCREENSHOTS, f"grp_{name}.png"))
    except Exception:
        pass

def click_safe(driver, element) -> None:
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)

# ─────────────────────────────────────────────────────────────────────
# Runtime Buy & Sell page detection
# ─────────────────────────────────────────────────────────────────────
def is_buy_sell_on_page(driver) -> bool:
    indicators = driver.find_elements(
        By.XPATH,
        "//span[contains(text(), 'Sell something')"
        "    or contains(text(), 'List an item')"
        "    or contains(text(), 'Add price')]",
    )
    return len(indicators) > 0

# ─────────────────────────────────────────────────────────────────────
# Runtime admin-only group detection
# ─────────────────────────────────────────────────────────────────────
def is_admin_only_on_page(driver) -> bool:
    page_source_lower = driver.page_source.lower()

    admin_phrases = [
        "only admins can post",
        "only admin can post",
        "admins can post to this group",
        "only admins and moderators can post",
        "only group admins can post",
        "posting is limited to admins",
    ]
    if any(phrase in page_source_lower for phrase in admin_phrases):
        log("  [admin-only] Explicit 'admins only' text detected on page.")
        return True

    try:
        driver.find_element(
            By.XPATH,
            "//*[@role='main']//*["
            "  contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "                         'abcdefghijklmnopqrstuvwxyz'),"
            "            'only admins can post')"
            "  or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "                            'abcdefghijklmnopqrstuvwxyz'),"
            "               'admins can post')]",
        )
        log("  [admin-only] Admin-restriction element found in main content.")
        return True
    except NoSuchElementException:
        pass

    has_composer = bool(driver.find_elements(
        By.XPATH,
        "//div[@role='main']//*["
        "  contains(@placeholder, 'Write something')"
        "  or contains(@aria-label, 'Write something')"
        "  or (self::span and contains(text(), 'Write something'))]",
    ))
    has_join_btn = bool(driver.find_elements(
        By.XPATH,
        "//div[@role='button']//span[normalize-space()='Join group'"
        "                          or normalize-space()='Join Group']",
    ))
    has_discussion_tab = bool(driver.find_elements(
        By.XPATH,
        "//a[contains(@href, '/groups/') and ("
        "  contains(@aria-label, 'Discussion')"
        "  or contains(text(), 'Discussion'))]",
    ))

    if not has_composer and not has_join_btn and has_discussion_tab:
        log("  [admin-only] Member of group but no post composer visible.")
        return True

    return False

# ─────────────────────────────────────────────────────────────────────
# Navigate Directly to URL 
# ─────────────────────────────────────────────────────────────────────
def navigate_to_group(driver, group_url: str) -> "str | None":
    group_url = group_url.replace("web.facebook.com", "www.facebook.com")
    if not group_url.rstrip("/").endswith("/"):
        group_url = group_url.rstrip("/") + "/"

    log(f"  Navigating directly to: {group_url}")
    
    try:
        driver.get(group_url)
    except TimeoutException:
        log("  Page load took too long, but checking if DOM is ready anyway...")

    try:
        # Wait up to 40 seconds for the URL to settle into the group
        WebDriverWait(driver, 40).until(
            lambda d: "/groups/" in d.current_url
                      and "/search/" not in d.current_url
                      and "/login" not in d.current_url.lower()
        )
        # Wait up to 30 seconds for the main container to be visible
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.XPATH, "//div[@role='main']"))
        )
    except TimeoutException:
        log("  Timed out waiting for group page.")
        sc(driver, "group_page_timeout")
        return None

    final_url = driver.current_url
    log(f"  Group page loaded: {final_url}")
    sc(driver, "group_page_loaded")
    return final_url

# ─────────────────────────────────────────────────────────────────────
# Membership check
# ─────────────────────────────────────────────────────────────────────
def can_post(driver) -> bool:
    try:
        driver.find_element(
            By.XPATH,
            "//span[contains(text(), 'Write something')"
            "    or contains(text(), \"What's on your mind\")]",
        )
        return True
    except NoSuchElementException:
        pass

    joins = driver.find_elements(
        By.XPATH,
        "//div[@role='button']//span[normalize-space()='Join group'"
        "                          or normalize-space()='Join Group']",
    )
    if joins:
        log("  Not a group member — 'Join group' button detected.")
        return False

    return True

# ─────────────────────────────────────────────────────────────────────
# contenteditable text injection (React / Lexical compatible)
# ─────────────────────────────────────────────────────────────────────
def inject_text(driver, element, text: str) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    # Wait for element to actually be clickable before interacting
    WebDriverWait(driver, 5).until(EC.element_to_be_clickable(element))
    element.click()

    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('insertText', false, arguments[1]);",
        element,
        text,
    )

    current = driver.execute_script("return arguments[0].textContent;", element)
    if not current or len(current.strip()) < 5:
        log("  [fallback] execCommand empty — using textContent + InputEvent.")
        driver.execute_script(
            """
            var el   = arguments[0];
            var text = arguments[1];
            el.focus();
            while (el.firstChild) { el.removeChild(el.firstChild); }
            el.appendChild(document.createTextNode(text));
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true, inputType: 'insertText', data: text
            }));
            """,
            element,
            text,
        )

# ─────────────────────────────────────────────────────────────────────
# Post composer: dialog-scoped XPaths + Lexical editor detection
# ─────────────────────────────────────────────────────────────────────
def post_to_current_group(driver, image_path: str, text: str) -> bool:
    log("  [1/4] Opening post composer dialog...")
    trigger_xpaths = [
        "//div[@role='main']//div[@role='button']"
        "    [.//span[contains(text(), 'Write something')"
        "          or contains(text(), \"What's on your mind\")]]",
        "//div[@role='main']//span[contains(text(), 'Write something')"
        "                       or contains(text(), \"What's on your mind\")]",
        "//div[@role='main']//div[@aria-label='Create a public post']",
        "//div[@role='main']//div[@aria-label='Create post']",
        "//div[@role='main']//div[@aria-label='Write something']",
    ]

    opened = False
    for xp in trigger_xpaths:
        try:
            el = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xp)))
            # Scroll into view just in case it's hidden at the bottom of the screen
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.5)
            click_safe(driver, el)
            opened = True
            log("  [ok] Composer trigger clicked.")
            break
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
            continue

    if not opened:
        sc(driver, "composer_trigger_fail")
        log("  [FAIL] Could not click the post composer trigger.")
        return False

    try:
        # Wait up to 20 seconds for the dialog to be present
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        # Small pause to let the dialog render its internal elements
        time.sleep(1.0)
        log("  [ok] Composer dialog is open.")
    except TimeoutException:
        sc(driver, "dialog_not_found")
        log("  [FAIL] Post composer dialog did not appear.")
        return False

    sc(driver, "composer_open")

    log("  [2/4] Attaching photo...")
    photo_btn_xpaths = [
        "//div[@role='dialog']//div[@aria-label='Photo/video']",
        "//div[@role='dialog']//div[@aria-label='Photo or video']",
        "//div[@role='dialog']//span[normalize-space()='Photo/video']",
        "//div[@role='dialog']//span[contains(text(),'Photo')"
        "                           and not(contains(text(),'Tag'))]",
    ]
    for xp in photo_btn_xpaths:
        try:
            btn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, xp)))
            click_safe(driver, btn)
            log("  [ok] Photo/video button clicked.")
            break
        except (TimeoutException, NoSuchElementException):
            continue

    try:
        file_input = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog']//input[@type='file']")
            )
        )
        abs_path = os.path.abspath(image_path)
        file_input.send_keys(abs_path)
        log(f"  [ok] File queued: {os.path.basename(abs_path)}")
        
        # Wait dynamically for the image preview to appear in the dialog (means upload finished)
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.find_elements(By.XPATH, "//div[@role='dialog']//img[contains(@src, 'scontent') or contains(@src, 'fbcdn')]") or 
                          d.find_elements(By.XPATH, "//div[@role='dialog']//div[@aria-label='Remove photo']") or
                          d.find_elements(By.XPATH, "//div[@role='dialog']//i[@aria-label='Remove']")
            )
            log("  [ok] Photo preview detected (upload finished).")
        except TimeoutException:
            log("  [warn] Could not confirm photo preview, continuing anyway...")
            
    except TimeoutException:
        sc(driver, "file_input_fail")
        log("  [FAIL] File input not found inside dialog.")
        return False

    sc(driver, "photo_uploaded")

    log("  [3/4] Inserting description into post editor...")
    editor_xpaths = [
        "//div[@role='dialog']//div[@data-lexical-editor='true']",
        "//div[@role='dialog']//div[@role='textbox' and @contenteditable='true']",
        "//div[@role='dialog']//div[@contenteditable='true'"
        "                          and contains(@class,'notranslate')]",
        "//div[@role='dialog']//div[@contenteditable='true'][1]",
    ]

    text_added = False
    for xp in editor_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )

            is_comment = driver.execute_script(
                """
                var el = arguments[0];
                while (el) {
                    var lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (lbl.includes('comment') || lbl.includes('reply')) return true;
                    el = el.parentElement;
                }
                return false;
                """,
                tb,
            )
            if is_comment:
                log(f"  [skip] Matched a comment box, skipping XPath.")
                continue

            inject_text(driver, tb, text)
            actual = driver.execute_script("return arguments[0].textContent;", tb)
            if actual and len(actual.strip()) > 5:
                log(f"  [ok] Description inserted ({len(text)} chars).")
                text_added = True
                break
            else:
                log("  [warn] Text box empty after inject — trying next XPath.")
        except (TimeoutException, NoSuchElementException):
            continue

    if not text_added:
        log("  [WARN] Could not confirm text — continuing to submit.")

    sc(driver, "text_added")

    log("  [4/4] Submitting post...")
    post_btn_xpaths = [
        "//div[@role='dialog']//div[@aria-label='Post'][@role='button']",
        "//div[@role='dialog']//button[@aria-label='Post']",
        "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Post']]",
        "//div[@role='dialog']//button[.//span[normalize-space()='Post']]",
        "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Publish']]",
    ]
    
    post_btn = None
    for xp in post_btn_xpaths:
        try:
            # Wait up to 20 seconds for the button to be clickable (enabled)
            # This confirms the image has finished uploading
            post_btn = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, xp)))
            log("  [ok] Post button found and enabled.")
            break
        except TimeoutException:
            continue
            
    if not post_btn:
        sc(driver, "post_btn_fail")
        log("  [FAIL] Could not find an enabled Post button (image might still be uploading).")
        return False

    sc(driver, "pre_submit")
    click_safe(driver, post_btn)
    log("  [ok] Post button clicked.")
    
    # Wait for dialog to close
    try:
        WebDriverWait(driver, 20).until(
            EC.invisibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        log("  [ok] Dialog closed — post accepted.")
        sc(driver, "post_submitted")
        return True
    except TimeoutException:
        log("  [warn] Dialog still open after 20s. Checking for errors or retrying click...")
        sc(driver, "post_dialog_stuck")
        
        # Try pressing Enter as a fallback
        try:
            post_btn.send_keys(Keys.ENTER)
            WebDriverWait(driver, 10).until(
                EC.invisibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
            )
            log("  [ok] Dialog closed after fallback Enter key.")
            return True
        except TimeoutException:
            log("  [FAIL] Dialog still open. Post likely failed.")
            return False

# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("Facebook Group Poster Bot — starting (URL-based)")
    log(f"  poster-{photo_number:02d}  |  description-{description_number:02d}")
    log("=" * 60)

    state = load_daily_state()

    target_group = pick_target_group(state)
    if target_group is None:
        log("No eligible groups remain for today.")
        write_github_output(
            status="no_groups_left",
            group="none",
            poster_number=photo_number,
            published_time="N/A",
            total_posts_today=state.get("total_posts", 0),
        )
        return 0

    state["used_groups"] = state.get("used_groups", []) + [target_group]
    save_daily_state(state)
    log(f"'{extract_group_id(target_group)}' marked as used today "
        f"({len(state['used_groups'])} total used).")

    if not os.path.isfile(POSTER_PATH):
        log(f"Poster image missing: {POSTER_PATH}")
        write_github_output(
            status="missing_poster",
            group=target_group,
            poster_number=photo_number,
            published_time="N/A",
            total_posts_today=state.get("total_posts", 0),
        )
        return 1

    log("Launching Chrome (headless, undetected)...")
    driver = build_driver()
    driver.set_page_load_timeout(60)
    succeeded    = False
    published_at = ""

    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)
        if "login" in driver.current_url.lower():
            log("Facebook session expired — re-run facebook_profile_initializer.py.")
            sys.exit(99)
        sc(driver, "session_verified")
        log("Session active.")

        group_url = navigate_to_group(driver, target_group)
        if not group_url:
            write_github_output(
                status="group_not_found",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 1

        sc(driver, "group_page")

        if is_buy_sell_on_page(driver):
            log(f"'{extract_group_id(target_group)}' is a Buy & Sell group — skipping.")
            sc(driver, "buy_sell_detected")
            write_github_output(
                status="buy_sell_skipped",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        if is_admin_only_on_page(driver):
            log(f"'{extract_group_id(target_group)}' only allows admin posts — skipping.")
            sc(driver, "admin_only_detected")
            write_github_output(
                status="admin_only_skipped",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        if not can_post(driver):
            log(f"Not a member of '{extract_group_id(target_group)}' — skipping.")
            write_github_output(
                status="not_a_member",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        log(f"Posting to: {extract_group_id(target_group)}")
        succeeded = post_to_current_group(driver, POSTER_PATH, POST_DESCRIPTION)

        if succeeded:
            published_at         = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
            state["total_posts"] = state.get("total_posts", 0) + 1
            save_daily_state(state)
            log(f"SUCCESS — poster-{photo_number:02d} posted at {published_at}. "
                f"Total today: {state['total_posts']}")

    except SystemExit:
        raise
    except Exception as exc:
        log(f"Unhandled error: {exc}")
        sc(driver, "unhandled_error")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    status_label = "published" if succeeded else "FAILED"
    write_github_output(
        group=target_group,
        poster_number=photo_number,
        published_time=published_at or "N/A",
        status=status_label,
        total_posts_today=state.get("total_posts", 0),
    )
    log("=" * 60)
    log(f"Run finished — {status_label}")
    log("=" * 60)
    return 0 if succeeded else 1

if __name__ == "__main__":
    sys.exit(main())