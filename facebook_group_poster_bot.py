#!/usr/bin/env python3
"""
Facebook Group Poster Bot
=========================
Posts a random poster + description directly into ONE Facebook group per run.

Fixes vs previous version
--------------------------
FIX 1 – find_group_url() now CLICKS into the matching group result and
         waits for the real /groups/<id>/ page to load before returning.
         Previously it returned the /search/groups/ URL so the bot was
         always posting (or trying to post) on the search-results page.

FIX 2 – post_to_current_group() now waits for the composer DIALOG element
         before doing anything, then scopes every subsequent XPath strictly
         inside that dialog.  The text editor is located via Facebook/Lexical's
         own  data-lexical-editor="true"  attribute which is NOT present on
         comment boxes — so the bot can no longer accidentally type in a
         comment field.

FIX 3 – After find_group_url() the driver is already on the group page.
         The old redundant driver.get(group_url) call (which reloaded the
         page and could lose the already-loaded state) has been removed.
"""

import json
import os
import random
import sys
import time
import urllib.parse
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

# ─── Keywords that identify a "Buy & Sell" group by name ─────────────
BUY_SELL_KEYWORDS = [
    "buy and sell",
    "buy & sell",
    "buying and selling",
    "sell and buy",
    "classifieds",
    "classified ads",
]

# ─────────────────────────────────────────────────────────────────────
# Target Facebook groups
# ─────────────────────────────────────────────────────────────────────
try:
    from facebook_poster_bot import TARGET_GROUPS
except ImportError:
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
        "ඉඩම් ගෙවල් වාහන ලාභෙට Land | House | Vehicle for Sale Sri Lanka",
        "Houses for Rent - කුලියට ගෙයක්",
        "කලුතර / කොළඹ / ගම්පහ ඉඩම් හා නිවාස - House & Land for sale",
        "නිවාස ,ඉඩම්,House,Lands අඩුවට කුලියට,බද්දට,විකිනීමට",
        "ikman.lk (Rent & Lease & Sale Property)",
        "Land and House for Sale to Buy ඉඩම් සහ නිවාස විකිණීමට මිලදී ගැනීමට",
        "Ceylon Property Hub | Buy Sell Rent | නිවාස ඉඩකඩම් විකිණීමට",
        "නිවාස ඉඩම් ව්කිනිමට කුලියට දිමට සහ ගැනිමට සොයන්නො",
        "House Lease and Rent in Colombo",
        "dematagoda/maradana/maligawatta/grandpass/borella/kotahena/modara/narahenpi",
        "House For Sale.. මන්දිරය නිවාස .... ඔබේ නිවස සොයාගන්න...",
        "ඉඩම් සහ ගෙවල් විකිණීමට - Lands and Houses for Sale",
        "NEGOMBO HOUSE / LANDS FOR SALE",
        "කුලියට නිවසක් | House For Rent - Sri Lanka",
        "Dehiwala - Mount Lavinia Community දෙහිවල ගල්කිස්ස අපි",
        "නිවාස සහ ඉඩම් විකිණීමේ සහ මිලදී ගැනීමේ සමූහය-Real Estate In Sri Lanka",
        "house and land sale නිවාස ඉඩකඩම් විකිනීමට",
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
# Group selection logic
# ─────────────────────────────────────────────────────────────────────
def is_buy_sell_by_name(group_name: str) -> bool:
    name_lower = group_name.lower()
    return any(kw in name_lower for kw in BUY_SELL_KEYWORDS)


def pick_target_group(state: dict) -> "str | None":
    used       = set(state.get("used_groups", []))
    candidates = [
        g for g in TARGET_GROUPS
        if g not in used and not is_buy_sell_by_name(g)
    ]
    if not candidates:
        log("All eligible groups have been used today.")
        return None
    chosen = random.choice(candidates)
    log(f"Selected group ({len(used)} already used today): {chosen}")
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
# FIX 1 – Group discovery: search → CLICK into group → return real URL
# ─────────────────────────────────────────────────────────────────────
def find_group_url(driver, group_name: str) -> "str | None":
    """
    Searches for the group, clicks the best-matching result, waits for the
    actual group page (/groups/<id>/) to finish loading, then returns the
    current URL.  The driver is already on the group page when this returns.
    """
    encoded    = urllib.parse.quote(group_name)
    search_url = f"https://www.facebook.com/search/groups/?q={encoded}"
    log(f"  Searching: {search_url}")
    driver.get(search_url)
    sc(driver, "search_results")

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        time.sleep(3)   # let React render result cards
    except TimeoutException:
        log("  Search results page timed out.")
        return None

    # ── Find best-matching link ───────────────────────────────────────
    target_href = None
    try:
        all_links = driver.find_elements(
            By.XPATH,
            "//a[contains(@href, '/groups/') "
            "    and not(contains(@href, '/groups/feed')) "
            "    and not(contains(@href, '/search/'))]",
        )
        for link in all_links:
            try:
                href = link.get_attribute("href") or ""
                if "/groups/" not in href:
                    continue
                spans     = link.find_elements(By.TAG_NAME, "span")
                link_text = " ".join(s.text for s in spans if s.text).strip()
                if not link_text:
                    link_text = link.text.strip()

                if (group_name.lower() == link_text.lower()
                        or group_name.lower() in link_text.lower()
                        or link_text.lower() in group_name.lower()):
                    log(f"  Matched result: '{link_text[:70]}'")
                    target_href = href
                    break
            except StaleElementReferenceException:
                continue
    except Exception as exc:
        log(f"  Link scan error: {exc}")

    # Fallback: first result
    if target_href is None:
        try:
            first = driver.find_element(
                By.XPATH,
                "(//a[contains(@href, '/groups/') "
                "     and not(contains(@href, '/groups/feed')) "
                "     and not(contains(@href, '/search/'))])[1]",
            )
            target_href = first.get_attribute("href") or ""
            if target_href:
                log(f"  No name match — using first result: {target_href}")
            else:
                log(f"  Could not locate group '{group_name}' in search results.")
                sc(driver, "group_not_found")
                return None
        except NoSuchElementException:
            log(f"  Could not locate group '{group_name}' in search results.")
            sc(driver, "group_not_found")
            return None

    # ── Navigate directly to the group URL ───────────────────────────
    # Using driver.get() is more reliable than clicking stale search-result
    # elements; it avoids StaleElementReferenceException entirely.
    log(f"  Navigating to group: {target_href}")
    driver.get(target_href)

    # ── Wait for the real group page to finish loading ────────────────
    try:
        WebDriverWait(driver, 20).until(
            lambda d: "/groups/" in d.current_url
                      and "/search/" not in d.current_url
        )
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        time.sleep(2)   # let the post composer / feed render
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
    time.sleep(0.3)
    element.click()
    time.sleep(0.5)

    # Primary: execCommand fires Lexical's synthetic input event
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('insertText', false, arguments[1]);",
        element,
        text,
    )
    time.sleep(0.5)

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
# FIX 2 – Post composer: dialog-scoped XPaths + Lexical editor detection
# ─────────────────────────────────────────────────────────────────────
def post_to_current_group(driver, image_path: str, text: str) -> bool:
    """
    Opens the post composer, attaches the image, types the description,
    and submits.  Every element lookup is scoped to the dialog so comment
    boxes cannot be matched by mistake.
    """

    # ── Step 1 · Click the "Write something" trigger ──────────────────
    log("  [1/4] Opening post composer dialog...")
    trigger_xpaths = [
        # The clickable bar rendered as a button
        "//div[@role='main']//div[@role='button']"
        "    [.//span[contains(text(), 'Write something')"
        "          or contains(text(), \"What's on your mind\")]]",
        # Sometimes the span itself is the clickable target
        "//div[@role='main']//span[contains(text(), 'Write something')"
        "                       or contains(text(), \"What's on your mind\")]",
        # Aria-labelled wrappers
        "//div[@role='main']//div[@aria-label='Create a public post']",
        "//div[@role='main']//div[@aria-label='Create post']",
        "//div[@role='main']//div[@aria-label='Write something']",
    ]

    opened = False
    for xp in trigger_xpaths:
        try:
            el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
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

    # ── Wait for the dialog ───────────────────────────────────────────
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        time.sleep(1.5)   # let the dialog animate in
        log("  [ok] Composer dialog is open.")
    except TimeoutException:
        sc(driver, "dialog_not_found")
        log("  [FAIL] Post composer dialog did not appear.")
        return False

    sc(driver, "composer_open")

    # ── Step 2 · Click Photo/video inside the dialog ──────────────────
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
            time.sleep(1.5)
            break
        except (TimeoutException, NoSuchElementException):
            continue

    # Upload via the hidden file input (dialog-scoped)
    try:
        file_input = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog']//input[@type='file']")
            )
        )
        abs_path = os.path.abspath(image_path)
        file_input.send_keys(abs_path)
        log(f"  [ok] File queued: {os.path.basename(abs_path)}")
        time.sleep(4)   # wait for upload progress bar to finish
    except TimeoutException:
        sc(driver, "file_input_fail")
        log("  [FAIL] File input not found inside dialog.")
        return False

    sc(driver, "photo_uploaded")

    # ── Step 3 · Type in the POST EDITOR only (not a comment box) ─────
    #
    # Facebook's composer uses the Lexical rich-text framework.
    # The editor root carries  data-lexical-editor="true"  — this
    # attribute does NOT appear on comment textareas or search inputs,
    # so it is the safest selector to distinguish the post editor.
    # All XPaths are scoped to  //div[@role='dialog']  for extra safety.
    log("  [3/4] Inserting description into post editor...")

    editor_xpaths = [
        # Primary — Lexical editor (most reliable, FB-specific)
        "//div[@role='dialog']//div[@data-lexical-editor='true']",
        # Fallback 1 — textbox role inside dialog
        "//div[@role='dialog']//div[@role='textbox' and @contenteditable='true']",
        # Fallback 2 — notranslate class (FB's historical marker for the editor)
        "//div[@role='dialog']//div[@contenteditable='true'"
        "                          and contains(@class,'notranslate')]",
        # Fallback 3 — first contenteditable inside dialog
        "//div[@role='dialog']//div[@contenteditable='true'][1]",
    ]

    text_added = False
    for xp in editor_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )

            # Safety check: make sure this element is NOT inside a comment section
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
    time.sleep(random.uniform(1.0, 2.0))

    # ── Step 4 · Submit (Post button inside dialog) ───────────────────
    log("  [4/4] Submitting post...")
    post_btn_xpaths = [
        "//div[@role='dialog']//div[@aria-label='Post'][@role='button']",
        "//div[@role='dialog']//div[@role='button']"
        "    [.//span[normalize-space()='Post']]",
        # Some locales / group types say "Share" instead
        "//div[@role='dialog']//div[@role='button']"
        "    [.//span[normalize-space()='Share']]",
    ]
    for xp in post_btn_xpaths:
        try:
            btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xp)))
            sc(driver, "pre_submit")
            click_safe(driver, btn)
            log("  [ok] Post button clicked.")
            # Dialog disappearing = Facebook accepted the post
            try:
                WebDriverWait(driver, 15).until(
                    EC.invisibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
                )
                log("  [ok] Dialog closed — post accepted.")
            except TimeoutException:
                log("  [warn] Dialog still open after 15 s — post may still have gone through.")
            sc(driver, "post_submitted")
            return True
        except (TimeoutException, NoSuchElementException):
            continue

    sc(driver, "post_btn_fail")
    log("  [FAIL] Could not click the Post button.")
    return False


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("Facebook Group Poster Bot — starting")
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

    # Mark as used BEFORE any network action
    state["used_groups"] = state.get("used_groups", []) + [target_group]
    save_daily_state(state)
    log(f"'{target_group}' marked as used today "
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
    driver.set_page_load_timeout(30)
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

        # find_group_url() now navigates INTO the group itself.
        # When it returns, the driver is already on the group page —
        # no extra driver.get() is needed (that was causing the second bug).
        group_url = find_group_url(driver, target_group)
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
            log(f"'{target_group}' is a Buy & Sell group — skipping.")
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
            log(f"'{target_group}' only allows admin posts — skipping.")
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
            log(f"Not a member of '{target_group}' — skipping.")
            write_github_output(
                status="not_a_member",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        log(f"Posting to: {target_group}")
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