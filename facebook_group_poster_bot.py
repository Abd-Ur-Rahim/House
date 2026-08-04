#!/usr/bin/env python3
"""
Facebook Group Poster Bot  (URL-based edition)
==============================================
Posts a random poster + description directly into ONE Facebook group per run.

CHANGES vs previous version
---------------------------
• TARGET_GROUPS is now a list of direct Facebook group URLs instead of
  group names.  The bot navigates straight to each URL — no search step.
• find_group_url() replaced by navigate_to_group() — simply does
  driver.get(url) and waits for the group page to load.
• is_buy_sell_by_name() removed (no group names to check).  Runtime
  page-content checks (is_buy_sell_on_page, is_admin_only_on_page,
  can_post) remain unchanged and still run after landing on the group.
• urllib.parse import removed (no longer needed).
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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

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
    used        = set(state.get("used_groups", []))
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
        # block_images=True,
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
        "//span[contains(text(),'Sell Something')"
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
            "                     'abcdefghijklmnopqrstuvwxyz'),"
            "           'only admins can post')"
            "  or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "                            'abcdefghijklmnopqrstuvwxyz'),"
            "              'admins can post')]",
        )
        log("  [admin-only] Admin-restriction element found in main content.")
        return True
    except NoSuchElementException:
        pass
    time.sleep(2)
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
        "                        or normalize-space()='Join Group']",
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
# NAVIGATION: navigate_to_group() — direct URL, no search
# ─────────────────────────────────────────────────────────────────────
def navigate_to_group(driver, group_url: str) -> "str | None":
    """
    Navigate directly to the given Facebook group URL and wait for the
    group page to finish loading.  Returns the final URL (after any
    redirects) or None on failure.

    The driver is already on the group page when this returns.
    """
    group_url = group_url.replace("web.facebook.com", "www.facebook.com")
    if not group_url.rstrip("/").endswith("/"):
        group_url = group_url.rstrip("/") + "/"

    log(f"  Navigating directly to: {group_url}")
    driver.get(group_url)

    try:
        WebDriverWait(driver, 20).until(
            lambda d: "/groups/" in d.current_url
                      and "/search/" not in d.current_url
                      and "/login" not in d.current_url.lower()
        )
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        time.sleep(2)
    except TimeoutException:
        log("  Timed out waiting for group page.")
        # sc(driver, "group_page_timeout")
        return None

    final_url = driver.current_url
    log(f"  Group page loaded: {final_url}")
    # sc(driver, "group_page_loaded")
    return final_url


# ─────────────────────────────────────────────────────────────────────
# Membership check
# ─────────────────────────────────────────────────────────────────────
def can_post(driver) -> bool:
    page_source_lower = driver.page_source.lower()

    pending_phrases = [
        "your request to participate is pending approval",
        "pending approval",
        "request to join",
    ]
    if any(phrase in page_source_lower for phrase in pending_phrases):
        log("  Not a group member — 'Pending approval' detected.")
        return False

    joins = driver.find_elements(
        By.XPATH,
        "//div[@role='button']//span[normalize-space()='Join group'"
        "                        or normalize-space()='Join Group']",
    )
    if joins:
        log("  Not a group member — 'Join group' button detected.")
        return False

    try:
        driver.find_element(
            By.XPATH,
            "//span[contains(text(), 'Write something')"
            "    or contains(text(), \"What's on your mind\")]",
        )
        return True
    except NoSuchElementException:
        pass

    return True


# ─────────────────────────────────────────────────────────────────────
# contenteditable text injection (React / Lexical compatible)
# ─────────────────────────────────────────────────────────────────────
def inject_text(driver, element, text: str) -> None:
    """Reliably insert text into a contenteditable / Lexical editor."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.3)

    # 1. Click to focus
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
    time.sleep(0.4)

    # 2. Select all existing content and delete it (works on contenteditable)
    ActionChains(driver)\
        .key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL)\
        .perform()
    time.sleep(0.2)
    ActionChains(driver).send_keys(Keys.DELETE).perform()
    time.sleep(0.2)

    # 3. Type text in chunks to avoid dropped characters on long strings
    chunk_size = 200
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        ActionChains(driver).send_keys(chunk).perform()
        time.sleep(0.15)

    time.sleep(0.5)

    # 4. Verify — fallback to execCommand if ActionChains failed
    current = driver.execute_script("return arguments[0].textContent;", element)
    if not current or len(current.strip()) < 5:
        log("  [fallback] ActionChains failed — using execCommand.")
        driver.execute_script(
            "arguments[0].focus();"
            "document.execCommand('selectAll', false, null);"
            "document.execCommand('delete', false, null);"
            "document.execCommand('insertText', false, arguments[1]);",
            element, text,
        )
        time.sleep(0.5)


# ─────────────────────────────────────────────────────────────────────
# Post composer: dialog-scoped XPaths + Lexical editor detection
# ─────────────────────────────────────────────────────────────────────
def post_to_current_group(driver, image_path: str, text: str) -> bool:

    # ── Step 1: Open composer ─────────────────────────────────────────
    log("  [1/4] Opening post composer dialog...")
    trigger_xpaths = [
        "//div[@role='main']//div[@role='button']"
        "    [.//span[contains(text(), 'Write something')"
        "            or contains(text(), \"What's on your mind\")]]",
        "//div[@role='main']//span[contains(text(), 'Write something')"
        "                        or contains(text(), \"What's on your mind\")]",
        "//div[@role='main']//div[@aria-label='Create a public post']",
        "//div[@role='main']//div[@aria-label='Create post']",
        "//div[@role='main']//div[@aria-label='Write something']",
    ]

    opened = False
    for xp in trigger_xpaths:
        try:
            el = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            click_safe(driver, el)
            opened = True
            log("  [ok] Composer trigger clicked.")
            break
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
            continue

    if not opened:
        log("  [FAIL] Could not click the post composer trigger.")
        sc(driver, "composer_trigger_fail")
        return False

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        time.sleep(1.5)
        log("  [ok] Composer dialog is open.")
    except TimeoutException:
        log("  [FAIL] Post composer dialog did not appear.")
        sc(driver, "dialog_not_found")
        return False

    # ── Step 2: Add photo ─────────────────────────────────────────────
    log("  [2/4] Attaching photo (bypassing OS dialog)...")
    
    # Step 1: Make the hidden file input interactable via JS — no button click needed
    try:
        # Wait for the file input to exist in the dialog DOM
        file_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog']//input[@type='file']")
            )
        )
    except TimeoutException:
        # File input not pre-loaded — need to click button to inject it,
        # but use JS click so it does NOT open the OS dialog
        log("  File input not in DOM yet — injecting via JS click on button...")
        photo_btn_xpaths = [
            "//div[@role='dialog']//div[@aria-label='Photo/video']",
            "//div[@role='dialog']//div[@aria-label='Photo or video']",
            "//div[@role='dialog']//span[normalize-space()='Photo/video']",
            "//div[@role='dialog']//span[contains(text(),'Photo')"
            "                            and not(contains(text(),'Tag'))]",
        ]
        for xp in photo_btn_xpaths:
            btns = driver.find_elements(By.XPATH, xp)
            if btns:
                # JS click bypasses Selenium's normal click — avoids OS dialog
                driver.execute_script("arguments[0].click();", btns[0])
                log("  [ok] Photo button JS-clicked (no OS dialog).")
                time.sleep(1)
                break
    
        try:
            file_input = WebDriverWait(driver, 12).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@role='dialog']//input[@type='file']")
                )
            )
        except TimeoutException:
            log("  [FAIL] File input still not found after JS click.")
            sc(driver, "file_input_fail")
            return False
    
    # Step 2: Strip the CSS that hides it so Selenium can interact with it
    driver.execute_script("""
        var el = arguments[0];
        el.style.display    = 'block';
        el.style.visibility = 'visible';
        el.style.opacity    = '1';
        el.style.position   = 'fixed';
        el.style.top        = '0';
        el.style.left       = '0';
        el.style.width      = '1px';
        el.style.height     = '1px';
        el.style.zIndex     = '9999';
    """, file_input)
    time.sleep(0.5)
    
    # Step 3: Send file path — this NEVER opens the OS dialog
    abs_path = os.path.abspath(image_path)
    file_input.send_keys(abs_path)
    log(f"  [ok] File path sent silently: {os.path.basename(abs_path)}")
    
    # Step 4: Wait for photo preview to confirm it was accepted
    log("  Waiting for photo preview...")
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[@role='dialog']//img[contains(@src,'blob:')"
                "    or contains(@src,'scontent')"
                "    or contains(@src,'fbcdn')]"
            ))
        )
        log("  [ok] Photo preview visible — file accepted.")
    except TimeoutException:
        log("  [WARN] Photo preview not seen in 30s — continuing.")
        sc(driver, "photo_preview_timeout")
    
    time.sleep(2)   # let the dialog settle after photo attaches
    
    # ── Step 3: Insert description into POST text (not caption) ───────
    log("  [3/4] Inserting description into post editor...")

    # Target the FIRST Lexical editor which is the main post text box.
    # After photo upload Facebook shows: [post text editor] then [caption editor].
    # We explicitly want index [1] (first match = post text).
    editor_xpaths = [
        # Most specific — Lexical editor explicitly for the post (aria-label)
        "//div[@role='dialog']//div[@data-lexical-editor='true']"
        "    [@aria-label and not(contains(@aria-label,'caption'))"
        "               and not(contains(@aria-label,'Caption'))]",
        # First Lexical editor in the dialog (post text, above photo preview)
        "(//div[@role='dialog']//div[@data-lexical-editor='true'])[1]",
        # Generic textbox fallback
        "(//div[@role='dialog']//div[@role='textbox' and @contenteditable='true'])[1]",
        # notranslate class (older Facebook layout)
        "(//div[@role='dialog']//div[@contenteditable='true']"
        "    [contains(@class,'notranslate')])[1]",
    ]

    text_added = False
    for xp in editor_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )

            # Extra guard: skip if this is inside a caption/comment container
            is_caption_or_comment = driver.execute_script(
                """
                var el = arguments[0];
                while (el) {
                    var lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (lbl.includes('caption') || lbl.includes('comment')
                            || lbl.includes('reply')) return true;
                    el = el.parentElement;
                }
                return false;
                """,
                tb,
            )
            if is_caption_or_comment:
                log("  [skip] Matched a caption/comment box — trying next XPath.")
                continue

            inject_text(driver, tb, text)

            actual = driver.execute_script(
                "return arguments[0].textContent;", tb
            )
            if actual and len(actual.strip()) > 5:
                log(f"  [ok] Description inserted ({len(text)} chars). "
                    f"Verified: '{actual[:40]}...'")
                text_added = True
                break
            else:
                log("  [warn] Text box still empty after inject — trying next XPath.")
                sc(driver, "text_inject_empty")
        except (TimeoutException, NoSuchElementException):
            continue

    if not text_added:
        log("  [WARN] Could not verify text was inserted. Proceeding anyway.")
        sc(driver, "text_not_verified")

    time.sleep(random.uniform(1.0, 2.0))

    # ── Step 4: Submit ────────────────────────────────────────────────
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
            post_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            log("  [ok] Post button found and enabled.")
            break
        except TimeoutException:
            continue

    if not post_btn:
        log("  [FAIL] Could not find an enabled Post button.")
        sc(driver, "post_btn_fail")
        return False

    sc(driver, "pre_submit")
    driver.execute_script("arguments[0].click();", post_btn)
    log("  [ok] Post button clicked. Waiting for dialog to close (up to 90s)...")

    try:
        WebDriverWait(driver, 90).until(
            EC.invisibility_of_element_located((By.XPATH, "//*[text()='Posting']"))
        )
        log("  [ok] Dialog closed — post submitted successfully.")
        sc(driver, "post_submitted")
        return True

    except TimeoutException:
        log("  [WARN] Dialog stuck open for 90s — forcing page refresh...")
        sc(driver, "post_dialog_stuck")
        driver.refresh()
        time.sleep(4)

        try:
            body_text = driver.execute_script(
                "return document.body.innerText.toLowerCase();"
            )
            probe = " ".join(text.split())[:60].lower()
            if probe in body_text:
                log("  [ok] Post verified in feed after forced refresh!")
                return True
            else:
                log("  [FAIL] Post NOT in feed after refresh.")
                return False
        except Exception:
            log("  [FAIL] Could not verify post after refresh.")
            return False


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    state = load_daily_state()
    driver = build_driver()
    driver.set_page_load_timeout(30)
    succeeded = False
    published_at = ""
    target_group = None

    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)
        if "login" in driver.current_url.lower():
            log("Facebook session expired.")
            sys.exit(99)

        # ── Keep trying groups until one succeeds or none remain ──────
        while True:
            target_group = pick_target_group(state)
            if target_group is None:
                log("No eligible groups remain for today.")
                break

            # Mark used BEFORE navigating (prevents re-pick on exception)
            state["used_groups"] = state.get("used_groups", []) + [target_group]
            save_daily_state(state)

            if not os.path.isfile(POSTER_PATH):
                log(f"Poster image missing: {POSTER_PATH}")
                break

            group_url = navigate_to_group(driver, target_group)
            if not group_url:
                log("Navigation failed — trying next group.")
                continue   # ← skips to next instead of exiting

            if is_buy_sell_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is Buy & Sell — skipping.")
                continue   # ← skips to next

            if is_admin_only_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is admin-only — skipping.")
                continue   # ← skips to next

            if not can_post(driver):
                log(f"Not a member of '{extract_group_id(target_group)}' — skipping.")
                continue   # ← skips to next

            # ── All checks passed — attempt the post ──────────────────
            log(f"Posting to: {extract_group_id(target_group)}")
            succeeded = post_to_current_group(driver, POSTER_PATH, POST_DESCRIPTION)

            if succeeded:
                published_at = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
                state["total_posts"] = state.get("total_posts", 0) + 1
                save_daily_state(state)
                log(f"SUCCESS — poster-{photo_number:02d} posted at {published_at}. "
                    f"Total today: {state['total_posts']}")
            break   # ← stop after one successful (or attempted) post

    except SystemExit:
        raise
    except Exception as exc:
        log(f"Unhandled error: {exc}")
    finally:
        if succeeded:
            time.sleep(5)
        try:
            driver.quit()
        except Exception:
            pass

    status_label = "published" if succeeded else "FAILED"
    write_github_output(
        group=target_group or "none",
        poster_number=photo_number,
        published_time=published_at or "N/A",
        status=status_label,
        total_posts_today=state.get("total_posts", 0),
    )
    log(f"Run finished — {status_label}")

    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
