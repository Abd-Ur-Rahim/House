#!/usr/bin/env python3
"""
Facebook Group Poster Bot
=========================
Posts a random poster + description directly into ONE Facebook group per run.

Rules enforced:
  ① Runs up to 24 times per day (controlled by GitHub Actions hourly cron).
  ② Each run picks ONE group at random from TARGET_GROUPS.
  ③ If the chosen group is a "Buy & Sell" type (name keyword OR runtime page
     detection), it is skipped and another group is picked.
  ④ The same group is never selected more than once per calendar day
     (tracked in .group_tracker.json, persisted via GitHub Actions cache).

State file schema (.group_tracker.json):
  {
      "date":        "2025-07-28",         # SLT date; reset daily
      "used_groups": ["Group A", ...],     # attempted today (success or fail)
      "total_posts": 3                     # successful posts today
  }
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
# Facebook "Buy and sell" groups use a Marketplace-style post form
# (price / condition fields) which is incompatible with a standard post.
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
# (imported from the main bot to stay DRY — any edits there apply here)
# ─────────────────────────────────────────────────────────────────────
try:
    from facebook_poster_bot import TARGET_GROUPS          # preferred: single source
except ImportError:
    # Fallback: inline copy (kept in sync manually)
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
    """Loads today's tracking state; returns a fresh dict if none exists."""
    today = date.today().isoformat()
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                state = json.load(fh)
            if state.get("date") == today:
                used_count = len(state.get("used_groups", []))
                posts      = state.get("total_posts", 0)
                log(f"📋 Today's state loaded: {used_count} groups attempted, "
                    f"{posts} successful posts.")
                return state
        except (json.JSONDecodeError, KeyError, ValueError):
            log("⚠️ Corrupt state file — starting fresh.")
    log("📋 No state found for today — creating fresh state.")
    return {"date": today, "used_groups": [], "total_posts": 0}


def save_daily_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    log("💾 State saved.")


# ─────────────────────────────────────────────────────────────────────
# Group selection logic
# ─────────────────────────────────────────────────────────────────────
def is_buy_sell_by_name(group_name: str) -> bool:
    """Pre-flight name check; avoids launching a browser for obvious skips."""
    name_lower = group_name.lower()
    return any(kw in name_lower for kw in BUY_SELL_KEYWORDS)


def pick_target_group(state: dict) -> str | None:
    """
    Picks a random, un-used, non-buy/sell group from TARGET_GROUPS.
    Returns None when every eligible group has been used today.
    """
    used       = set(state.get("used_groups", []))
    candidates = [
        g for g in TARGET_GROUPS
        if g not in used and not is_buy_sell_by_name(g)
    ]
    if not candidates:
        log("⚠️ All eligible groups have been used today.")
        return None
    chosen = random.choice(candidates)
    log(f"🎯 Selected group ({len(used)} already used today): {chosen}")
    return chosen


# ─────────────────────────────────────────────────────────────────────
# Browser / driver helpers
# ─────────────────────────────────────────────────────────────────────
def build_driver() -> Driver:
    profile_path = os.path.join(base_dir, "profiles", "facebook_stable_session")
    if not os.path.isdir(profile_path):
        sys.exit(
            f"❌ Chrome profile not found:\n  {profile_path}\n"
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
    """Save a labelled screenshot to the screenshots folder."""
    try:
        driver.save_screenshot(os.path.join(SCREENSHOTS, f"grp_{name}.png"))
    except Exception:
        pass


def click_safe(driver, element) -> None:
    """Click with JS fallback if the standard click is intercepted."""
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


def wait_for(driver, timeout: int = 15) -> WebDriverWait:
    return WebDriverWait(driver, timeout)


# ─────────────────────────────────────────────────────────────────────
# Runtime Buy & Sell page detection
# ─────────────────────────────────────────────────────────────────────
def is_buy_sell_on_page(driver) -> bool:
    """
    Detects Facebook 'Buy and sell' group type at runtime.
    These groups show 'Sell something' / 'List an item' CTAs instead of
    the normal 'Write something...' post composer.
    """
    indicators = driver.find_elements(
        By.XPATH,
        "//span[contains(text(), 'Sell something')"
        "    or contains(text(), 'List an item')"
        "    or contains(text(), 'Add price')]",
    )
    return len(indicators) > 0


# ─────────────────────────────────────────────────────────────────────
# Group discovery: search → URL
# ─────────────────────────────────────────────────────────────────────
def find_group_url(driver, group_name: str) -> str | None:
    """
    Navigates to Facebook's group-search page and returns the URL of the
    best-matching group.  Returns None if no match is found.
    """
    encoded    = urllib.parse.quote(group_name)
    search_url = f"https://www.facebook.com/search/groups/?q={encoded}"
    log(f"  🔍 Searching: {search_url}")
    driver.get(search_url)
    sc(driver, "search_results")

    try:
        wait_for(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        time.sleep(2.5)
    except TimeoutException:
        log("  [!] Search results page timed out.")
        return None

    # ── Strategy 1: find a link whose visible text matches the group name ──
    try:
        all_group_links = driver.find_elements(
            By.XPATH,
            "//a[contains(@href, '/groups/') "
            "    and not(contains(@href, '/groups/feed')) "
            "    and not(contains(@href, '/search/'))]",
        )
        for link in all_group_links:
            try:
                href = link.get_attribute("href") or ""
                if "/groups/" not in href:
                    continue

                # Collect visible text from the link element
                spans = link.find_elements(By.TAG_NAME, "span")
                link_text = " ".join(s.text for s in spans if s.text).strip()
                if not link_text:
                    link_text = link.text.strip()

                # Exact or strong partial match
                if (group_name.lower() == link_text.lower()
                        or group_name.lower() in link_text.lower()
                        or link_text.lower() in group_name.lower()):
                    log(f"  ✅ Matched: '{link_text[:70]}' → {href}")
                    return href
            except StaleElementReferenceException:
                continue
    except Exception as exc:
        log(f"  [warn] Link scan error: {exc}")

    # ── Strategy 2: just take the very first group result ─────────────
    try:
        first = driver.find_element(
            By.XPATH,
            "(//a[contains(@href, '/groups/') "
            "     and not(contains(@href, '/groups/feed')) "
            "     and not(contains(@href, '/search/'))])[1]",
        )
        href = first.get_attribute("href") or ""
        if href:
            log(f"  ⚠️ No name match — using first result: {href}")
            return href
    except NoSuchElementException:
        pass

    sc(driver, "group_not_found")
    log(f"  ❌ Could not locate group '{group_name}' in search results.")
    return None


# ─────────────────────────────────────────────────────────────────────
# Membership check
# ─────────────────────────────────────────────────────────────────────
def can_post(driver) -> bool:
    """
    Returns True if the post composer ('Write something…') is visible,
    False if the group shows a 'Join group' button (not a member).
    """
    # Positive signal: composer is present
    try:
        driver.find_element(
            By.XPATH,
            "//span[contains(text(), 'Write something')"
            "    or contains(text(), \"What's on your mind\")]",
        )
        return True
    except NoSuchElementException:
        pass

    # Negative signal: join button present
    joins = driver.find_elements(
        By.XPATH,
        "//div[@role='button']//span[normalize-space()='Join group'"
        "                          or normalize-space()='Join Group']",
    )
    if joins:
        log("  ⚠️ Not a group member — 'Join group' button detected.")
        return False

    return True   # Ambiguous — try to post anyway


# ─────────────────────────────────────────────────────────────────────
# contenteditable text injection (React-compatible)
# ─────────────────────────────────────────────────────────────────────
def inject_text(driver, element, text: str) -> None:
    """
    Inserts text into a Facebook contenteditable div.
    Uses document.execCommand('insertText') which fires the React
    synthetic 'input' event correctly.  Falls back to textContent +
    InputEvent dispatch if execCommand yields an empty result.
    """
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.3)
    element.click()
    time.sleep(0.5)

    # Primary: execCommand (triggers React state update)
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('insertText', false, arguments[1]);",
        element,
        text,
    )
    time.sleep(0.5)

    # Verify — fallback if execCommand left the box empty
    current = driver.execute_script("return arguments[0].textContent;", element)
    if not current or len(current.strip()) < 5:
        log("  [fallback] execCommand yielded empty box — using textContent setter.")
        driver.execute_script(
            """
            var el   = arguments[0];
            var text = arguments[1];
            el.focus();
            // Clear then set via text node so React sees a real DOM change
            while (el.firstChild) { el.removeChild(el.firstChild); }
            var node = document.createTextNode(text);
            el.appendChild(node);
            el.dispatchEvent(new InputEvent('input', {
                bubbles:   true,
                inputType: 'insertText',
                data:      text,
            }));
            """,
            element,
            text,
        )


# ─────────────────────────────────────────────────────────────────────
# Core: post image + text to the currently-loaded group page
# ─────────────────────────────────────────────────────────────────────
def post_to_current_group(driver, image_path: str, text: str) -> bool:
    """
    Opens the post composer on the current group page, attaches an image,
    adds the description text, and submits.  Returns True on success.
    """

    # ── Step 1 · Open the post composer ──────────────────────────────
    log("  [1/4] Opening post composer…")
    composer_xpaths = [
        "//div[@role='main']//span[contains(text(), 'Write something')"
        "                         or contains(text(), \"What's on your mind\")]",
        "//span[contains(text(), 'Write something')]",
        "//div[@aria-label='Create a public post']",
        "//div[@aria-label='Write something']",
        "//div[@role='main']//div[@role='button' and @tabindex='0'][1]",
    ]
    opened = False
    for xp in composer_xpaths:
        try:
            el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
            click_safe(driver, el)
            opened = True
            log("  [ok] Composer opened.")
            time.sleep(2)
            break
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
            continue

    if not opened:
        sc(driver, "composer_fail")
        log("  [FAIL] Could not open post composer.")
        return False

    sc(driver, "composer_open")

    # ── Step 2 · Attach the photo ─────────────────────────────────────
    log("  [2/4] Attaching photo…")

    photo_btn_xpaths = [
        "//div[@role='dialog']//span[contains(text(), 'Photo/video')]",
        "//div[@role='dialog']//div[@aria-label='Photo/video']",
        "//span[contains(text(), 'Photo/video')]",
        "//div[@aria-label='Photo/video']",
        "//span[contains(text(), 'Photo') and not(contains(text(), 'video'))]",
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

    # Upload via the hidden file input
    try:
        file_input = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        abs_path = os.path.abspath(image_path)
        file_input.send_keys(abs_path)
        log(f"  [ok] File queued: {os.path.basename(abs_path)}")
        time.sleep(4)          # Allow the upload progress to settle
    except TimeoutException:
        sc(driver, "file_input_fail")
        log("  [FAIL] File input element not found.")
        return False

    sc(driver, "photo_uploaded")

    # ── Step 3 · Type the description ────────────────────────────────
    log("  [3/4] Inserting description…")
    text_box_xpaths = [
        "//div[@role='dialog']//div[@contenteditable='true' and @role='textbox']",
        "//div[@contenteditable='true' and @role='textbox']",
        "//div[@role='dialog']//div[@contenteditable='true'"
        "                          and contains(@class, 'notranslate')]",
        "//div[@role='dialog']//div[@contenteditable='true'][1]",
    ]
    text_added = False
    for xp in text_box_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            inject_text(driver, tb, text)
            actual = driver.execute_script("return arguments[0].textContent;", tb)
            if actual and len(actual.strip()) > 5:
                log(f"  [ok] Description inserted ({len(text)} chars).")
                text_added = True
                break
        except (TimeoutException, NoSuchElementException):
            continue

    if not text_added:
        log("  [WARN] Could not verify description box — continuing anyway.")

    sc(driver, "text_added")
    time.sleep(random.uniform(1.0, 2.0))

    # ── Step 4 · Click Post ───────────────────────────────────────────
    log("  [4/4] Submitting post…")
    post_btn_xpaths = [
        "//div[@role='dialog']//div[@aria-label='Post'][@role='button']",
        "//div[@role='dialog']//div[@role='button']"
        "    [.//span[normalize-space()='Post']]",
        "//div[@aria-label='Post'][@role='button']",
        "//div[@role='button'][.//span[normalize-space()='Post']]",
    ]
    for xp in post_btn_xpaths:
        try:
            btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xp)))
            sc(driver, "pre_submit")
            click_safe(driver, btn)
            log("  [ok] Post button clicked!")
            time.sleep(6)
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

    # 1. Load today's state ──────────────────────────────────────────
    state = load_daily_state()

    # 2. Pick a group ────────────────────────────────────────────────
    target_group = pick_target_group(state)
    if target_group is None:
        log("🏁 No eligible groups remain for today.")
        write_github_output(
            status="no_groups_left",
            group="none",
            poster_number=photo_number,
            published_time="N/A",
            total_posts_today=state.get("total_posts", 0),
        )
        return 0

    # 3. Mark group as used BEFORE any network action ─────────────────
    #    This prevents an infinite retry loop if the group is unreachable.
    state["used_groups"] = state.get("used_groups", []) + [target_group]
    save_daily_state(state)
    log(f"📌 '{target_group}' marked as used for today "
        f"({len(state['used_groups'])} total used).")

    # 4. Check poster image exists ───────────────────────────────────
    if not os.path.isfile(POSTER_PATH):
        log(f"❌ Poster image missing: {POSTER_PATH}")
        write_github_output(
            status="missing_poster",
            group=target_group,
            poster_number=photo_number,
            published_time="N/A",
            total_posts_today=state.get("total_posts", 0),
        )
        return 1

    # 5. Launch browser ──────────────────────────────────────────────
    log("🚀 Launching Chrome (headless, undetected)…")
    driver = build_driver()
    driver.set_page_load_timeout(30)
    succeeded    = False
    published_at = ""

    try:
        # Quick session verification
        driver.get("https://www.facebook.com")
        time.sleep(2)
        if "login" in driver.current_url.lower():
            log("❌ Facebook session expired — re-run facebook_profile_initializer.py.")
            sys.exit(99)
        sc(driver, "session_verified")
        log("✅ Session active.")

        # 6. Find the group URL ──────────────────────────────────────
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

        # 7. Navigate to the group page ──────────────────────────────
        log(f"  🌐 Navigating to group: {group_url}")
        driver.get(group_url)
        time.sleep(3)
        sc(driver, "group_page")

        # 8. Runtime buy/sell detection ──────────────────────────────
        if is_buy_sell_on_page(driver):
            log(f"⚠️ '{target_group}' is a Buy & Sell group → skipping.")
            sc(driver, "buy_sell_detected")
            write_github_output(
                status="buy_sell_skipped",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        # 9. Membership check ────────────────────────────────────────
        if not can_post(driver):
            log(f"⚠️ Not a member of '{target_group}' — skipping.")
            write_github_output(
                status="not_a_member",
                group=target_group,
                poster_number=photo_number,
                published_time="N/A",
                total_posts_today=state.get("total_posts", 0),
            )
            return 0

        # 10. Post! ──────────────────────────────────────────────────
        log(f"📢 Posting to: {target_group}")
        succeeded = post_to_current_group(driver, POSTER_PATH, POST_DESCRIPTION)

        if succeeded:
            published_at            = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
            state["total_posts"]    = state.get("total_posts", 0) + 1
            save_daily_state(state)
            log(f"✅ SUCCESS — poster-{photo_number:02d} posted at {published_at}. "
                f"Total today: {state['total_posts']}")

    except SystemExit:
        raise
    except Exception as exc:
        log(f"❌ Unhandled error: {exc}")
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
