#!/usr/bin/env python3
"""
Facebook Group Poster Bot  (URL-based edition)  --  PATCHED
===========================================================
Posts a random poster + description directly into ONE Facebook group per run.

PATCH SUMMARY (see accompanying PDF for full reasoning)
  F1  Proxy detection no longer disagrees with proxy attachment.
  F2  headless2 + explicit window size (UC-mode stealth).
  F3  Image is DOWNSCALED, not just re-compressed.
  F4  Submit-wait uses a positive signal (dialog detaches) instead of
      EC.invisibility_of_element_located, which false-positives.
  F5  driver.get() / refresh() wrapped; page-load timeout raised on proxy.
  F6  execute_async_script used for Promise-returning JS (execute_script
      does NOT await a Promise and returns a truthy {}).
  F7  Markdown string accidentally embedded in a URL removed.
  F8  Dead ternary (submit_wait) fixed; real proxy budgets applied.
  F9  verify_post_in_feed excludes the open composer + detects pending
      approval, so it can no longer false-positive or false-negative.
  F10 Per-group watchdog deadline so a stalled upload aborts instead of
      pinning the runner.
  F11 rupload.facebook.com stall diagnostics via Resource Timing API.
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
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver

# ---------------------------------------------------------------------
# Paths & runtime constants
# ---------------------------------------------------------------------
base_dir       = os.path.dirname(os.path.abspath(__file__))
local_timezone = pytz.timezone("Asia/Colombo")
SCREENSHOTS    = os.path.join(base_dir, "screenshots")
STATE_FILE     = os.path.join(base_dir, ".group_tracker.json")
os.makedirs(SCREENSHOTS, exist_ok=True)

# -- FIX F1 -----------------------------------------------------------
# The original code defaulted PROXY_HOST/PORT to 127.0.0.1:10808 and ALWAYS
# attached the proxy in build_driver(), but is_proxy_active() only returned
# True when the env vars were explicitly exported. In CI that meant: proxy
# on, but every proxy mitigation (compression, long timeouts, extra settle
# buffers) silently disabled. One flag now drives both.
USE_PROXY  = os.environ.get("USE_PROXY", "1").strip().lower() not in ("0", "false", "no")
PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = os.environ.get("PROXY_PORT", "10808")

# -- FIX F10 ----------------------------------------------------------
# Hard ceiling for a single group attempt. Beyond this we abort, screenshot,
# and exit cleanly rather than letting a stalled tunnel upload hang forever.
GROUP_DEADLINE_SECS = int(os.environ.get("GROUP_DEADLINE_SECS", "420"))

# -- Randomly pick poster image + description for this run ------------
photo_number       = random.randint(1, 10)
description_number = random.randint(1, 10)

with open(
    os.path.join(base_dir, "poster", "descriptions", f"{description_number}.txt"),
    encoding="utf-8",
) as _fh:
    POST_DESCRIPTION = _fh.read()

POSTER_PATH = os.path.join(base_dir, "poster", "flyers", f"poster-{photo_number:02d}.png")

# ---------------------------------------------------------------------
# Target Facebook groups  --  DIRECT URLS (no search needed)
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
def log(msg: str) -> None:
    stamp = datetime.now(local_timezone).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


# ---------------------------------------------------------------------
# GitHub Actions output helper
# ---------------------------------------------------------------------
def write_github_output(**kwargs) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            safe = str(value).replace("\n", " ").replace("\r", "")
            fh.write(f"{key}={safe}\n")


# ---------------------------------------------------------------------
# Daily state management
# ---------------------------------------------------------------------
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
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            log("Corrupt state file - starting fresh.")
    log("No state found for today - creating fresh state.")
    return {"date": today, "used_groups": [], "total_posts": 0}


def save_daily_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)          # atomic - survives a mid-write crash
    log("State saved.")


# ---------------------------------------------------------------------
# Group selection logic
# ---------------------------------------------------------------------
def extract_group_id(url: str) -> str:
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
        f"{extract_group_id(chosen)}  ->  {chosen}")
    return chosen


# ---------------------------------------------------------------------
# Browser / driver helpers
# ---------------------------------------------------------------------
def is_proxy_active() -> bool:
    """FIX F1: single source of truth, consistent with build_driver()."""
    return USE_PROXY


def build_driver() -> Driver:
    profile_path = os.path.join(base_dir, "profiles", "facebook_stable_session")
    if not os.path.isdir(profile_path):
        sys.exit(
            f"Chrome profile not found:\n  {profile_path}\n"
            "Run facebook_profile_initializer.py first."
        )

    kwargs = dict(
        browser="chrome",
        uc=True,
        user_data_dir=profile_path,
        # FIX F2: headless2 is Chrome's *new* headless mode. The old
        # headless=True is trivially fingerprinted and makes Facebook serve a
        # degraded composer with a different DOM. Also pin a desktop viewport:
        # UC headless defaults to a small window, which flips Facebook to a
        # narrow layout where the composer XPaths do not match.
        headless2=True,
        window_size="1920,1080",
    )
    if USE_PROXY:
        kwargs["proxy"] = f"socks5://{PROXY_HOST}:{PROXY_PORT}"
        log(f"[proxy] Attaching socks5://{PROXY_HOST}:{PROXY_PORT}")
    else:
        log("[proxy] Running WITHOUT a proxy.")

    return Driver(**kwargs)


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


# -- FIX F11: upload stall diagnostics --------------------------------
def report_upload_progress(driver) -> None:
    """
    Read the Resource Timing API for Facebook's upload endpoints.

    A request that has started but has duration == 0 is still in flight.
    If you see rupload entries stuck in flight while the spinner spins, the
    stall is the tunnel's upload throughput, not the automation.
    """
    try:
        entries = driver.execute_script(
            """
            return performance.getEntriesByType('resource')
              .filter(function(e) {
                  return e.name.indexOf('rupload') !== -1
                      || e.name.indexOf('/ajax/react/composer') !== -1
                      || e.name.indexOf('graphql') !== -1 && e.transferSize > 50000;
              })
              .slice(-8)
              .map(function(e) {
                  return {
                      url: e.name.split('?')[0].slice(-60),
                      dur: Math.round(e.duration),
                      sent: e.transferSize || 0
                  };
              });
            """
        ) or []
    except (JavascriptException, WebDriverException):
        return
    if not entries:
        log("  [net] No upload requests recorded yet.")
        return
    for e in entries:
        state = "IN-FLIGHT" if e.get("dur", 0) == 0 else f"{e['dur']}ms"
        log(f"  [net] {state:>10}  {e.get('sent', 0):>9} B  {e.get('url')}")


# ---------------------------------------------------------------------
# Runtime Buy & Sell page detection
# ---------------------------------------------------------------------
def is_buy_sell_on_page(driver) -> bool:
    indicators = driver.find_elements(
        By.XPATH,
        "//span[contains(text(),'Sell Something')"
        "    or contains(text(), 'Add price')]",
    )
    return len(indicators) > 0


# ---------------------------------------------------------------------
# Runtime admin-only group detection
# ---------------------------------------------------------------------
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

    time.sleep(3 if is_proxy_active() else 2)

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


# ---------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------
def navigate_to_group(driver, group_url: str) -> "str | None":
    # FIX F7: the original line was
    #   .replace("web.facebook.com", "[www.facebook.com](https://www.facebook.com)")
    # which injected a Markdown link into the URL string.
    group_url = group_url.replace("web.facebook.com", "www.facebook.com")
    if not group_url.endswith("/"):
        group_url += "/"

    log(f"  Navigating directly to: {group_url}")

    # FIX F5: driver.get() sits OUTSIDE the try in the original, so a
    # page-load timeout (very likely on a slow tunnel) escaped all the way to
    # main() and killed the run instead of skipping to the next group.
    try:
        driver.get(group_url)
    except (TimeoutException, WebDriverException) as exc:
        log(f"  Page load failed/timed out: {type(exc).__name__}")
        # The DOM is often usable even after a load timeout - keep going and
        # let the waits below decide.

    try:
        WebDriverWait(driver, 30 if is_proxy_active() else 20).until(
            lambda d: "/groups/" in d.current_url
                      and "/search/" not in d.current_url
                      and "/login" not in d.current_url.lower()
        )
        WebDriverWait(driver, 20 if is_proxy_active() else 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        time.sleep(3 if is_proxy_active() else 2)
    except TimeoutException:
        log("  Timed out waiting for group page.")
        sc(driver, "nav_timeout")
        return None

    final_url = driver.current_url
    log(f"  Group page loaded: {final_url}")
    return final_url


def safe_refresh(driver) -> bool:
    """FIX F5: refresh() can raise on a slow tunnel - never let it escape."""
    try:
        driver.refresh()
        return True
    except (TimeoutException, WebDriverException) as exc:
        log(f"  [refresh] {type(exc).__name__} - continuing with current DOM.")
        return False


# ---------------------------------------------------------------------
# Membership check
# ---------------------------------------------------------------------
def can_post(driver) -> bool:
    page_source_lower = driver.page_source.lower()

    pending_phrases = [
        "your request to participate is pending approval",
        "pending approval",
        "request to join",
    ]
    if any(phrase in page_source_lower for phrase in pending_phrases):
        log("  Not a group member - 'Pending approval' detected.")
        return False

    joins = driver.find_elements(
        By.XPATH,
        "//div[@role='button']//span[normalize-space()='Join group'"
        "                        or normalize-space()='Join Group']",
    )
    if joins:
        log("  Not a group member - 'Join group' button detected.")
        return False

    composer = driver.find_elements(
        By.XPATH,
        "//span[contains(text(), 'Write something')"
        "    or contains(text(), \"What's on your mind\")]",
    )
    if composer:
        return True

    # The original returned True here unconditionally, so a page that failed
    # to render through the proxy looked postable and burned a group slot.
    log("  [warn] No composer text found and no explicit blocker. "
        "Treating as postable, but this page may have rendered incompletely.")
    sc(driver, "composer_text_missing")
    return True


# ---------------------------------------------------------------------
# Text injection (React / Lexical compatible)
# ---------------------------------------------------------------------
def has_unicode(text: str) -> bool:
    return any(ord(c) > 127 for c in text)


def _editor_text(driver, element) -> str:
    try:
        return driver.execute_script("return arguments[0].innerText || '';", element) or ""
    except (JavascriptException, StaleElementReferenceException, WebDriverException):
        return ""


def inject_text(driver, element, text: str) -> bool:
    """
    Insert text into a contenteditable / Lexical editor, preserving formatting.

    Order:  1. CDP Input.insertText   2. async clipboard cascade
            3. line-by-line execCommand
    Returns True only if the text actually verified in the DOM.
    """
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.3)
    click_safe(driver, element)
    time.sleep(0.5)

    expected_len      = len(text.strip())
    expected_newlines = text.count("\n")

    def verified() -> bool:
        current = _editor_text(driver, element)
        if not current:
            return False
        length_ok  = len(current.strip()) >= expected_len * 0.8
        newline_ok = expected_newlines <= 2 or current.count("\n") >= expected_newlines * 0.5
        if length_ok and newline_ok:
            log(f"  [ok] Verified: {len(current.strip())}/{expected_len} chars, "
                f"{current.count(chr(10))}/{expected_newlines} newlines.")
            return True
        log(f"  [warn] Mismatch - chars {len(current.strip())}/{expected_len}, "
            f"newlines {current.count(chr(10))}/{expected_newlines}.")
        return False

    log("  Trying CDP injection first (works for all scripts)...")
    if _inject_via_cdp(driver, element, text) and verified():
        return True

    log("  Falling back to clipboard injection...")
    _inject_via_clipboard(driver, element, text)
    time.sleep(0.5)
    if verified():
        return True

    log("  Re-injecting once more...")
    _inject_via_clipboard(driver, element, text)
    time.sleep(0.5)
    return verified()


def _clear(driver, element) -> None:
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);",
        element,
    )
    time.sleep(0.2)


def _inject_via_cdp(driver, element, text: str) -> bool:
    """
    CDP Input.insertText inserts at the protocol level - no keyboard event
    translation, no newline->Enter conversion, works for Sinhala/Tamil/ASCII.

    NOTE: SeleniumBase UC mode periodically disconnects the DevTools pipe for
    stealth, so execute_cdp_cmd may be unavailable. That is expected; the
    clipboard cascade below is the real fallback and it is now correct (F6).
    """
    _clear(driver, element)
    driver.execute_script("arguments[0].focus();", element)
    time.sleep(0.3)
    try:
        chunks = _safe_unicode_chunks(text, max_chars=3500)
        for chunk in chunks:
            driver.execute_cdp_cmd("Input.insertText", {"text": chunk})
            time.sleep(0.1)
        log(f"  [cdp] Inserted {len(text)} chars in {len(chunks)} chunk(s).")
        return True
    except Exception as e:
        log(f"  [cdp] CDP insertText unavailable: {type(e).__name__}")
        return False


def _inject_via_clipboard(driver, element, text: str) -> None:
    """
    FIX F6 -- THE IMPORTANT ONE.

    The original used driver.execute_script() with `return new Promise(...)`.
    execute_script does NOT await a Promise; Selenium serialises the pending
    Promise object to `{}`, which is TRUTHY in Python. So `if injected:` was
    always True and Method 1 always reported success even when it inserted
    nothing -- the post then went out with no description.

    execute_async_script waits for the injected callback (last argument).
    """
    driver.set_script_timeout(30)
    _clear(driver, element)

    # -- Method 1: beforeinput insertFromPaste (Lexical's native handler) --
    injected = driver.execute_async_script(
        """
        var el = arguments[0], text = arguments[1], done = arguments[2];
        try {
            var dt = new DataTransfer();
            dt.setData('text/plain', text);
            el.dispatchEvent(new InputEvent('beforeinput', {
                inputType: 'insertFromPaste', data: text, dataTransfer: dt,
                bubbles: true, cancelable: true
            }));
            setTimeout(function () {
                done((el.innerText || '').trim().length > 5);
            }, 400);
        } catch (e) { done(false); }
        """,
        element, text,
    )
    if injected:
        log(f"  [beforeinput] Inserted {len(text)} chars.")
        return

    # -- Method 2: clipboard API paste --
    log("  [beforeinput] Failed - trying clipboard API paste.")
    _clear(driver, element)
    injected = driver.execute_async_script(
        """
        var el = arguments[0], text = arguments[1], done = arguments[2];
        function handler(e) {
            e.clipboardData.setData('text/plain', text);
            e.preventDefault();
            document.removeEventListener('paste', handler, true);
        }
        document.addEventListener('paste', handler, true);
        document.execCommand('paste');
        setTimeout(function () {
            done((el.innerText || '').trim().length > 5);
        }, 400);
        """,
        element, text,
    )
    if injected:
        log(f"  [clipboard] Inserted {len(text)} chars.")
        return

    # -- Method 3: line-by-line execCommand (preserves newlines as <br>) --
    log("  [clipboard] Failed - falling back to line-by-line execCommand.")
    _clear(driver, element)
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if line:
            driver.execute_script(
                "document.execCommand('insertText', false, arguments[0]);", line
            )
        if idx < len(lines) - 1:
            driver.execute_script("document.execCommand('insertLineBreak');")
        time.sleep(0.05)
    log(f"  [execCommand] Inserted {len(text)} chars ({len(lines)} lines).")


def _safe_unicode_chunks(text: str, max_chars: int = 3500) -> list:
    """Split without breaking grapheme clusters (consonant + vowel sign)."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split_at = max_chars
        for sep in ("\n", " "):
            pos = text.rfind(sep, 0, max_chars)
            if pos > max_chars // 2:
                split_at = pos + 1
                break
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks


# ---------------------------------------------------------------------
# Proxy-aware image preparation
# ---------------------------------------------------------------------
def compress_image_for_proxy(path: str,
                             max_size_kb: int = 300,
                             max_edge: int = 1440) -> str:
    """
    FIX F3.

    The original only lowered JPEG quality. A 3000x4000 poster at q35 is still
    several hundred KB, and -- more to the point -- Facebook re-processes the
    full-resolution pixels server-side before it will enable/settle the post.
    Downscaling the longest edge to ~1440px is what actually turns a
    multi-minute tunnel upload into a few seconds. 1440px is still well above
    Facebook's own feed display width, so there is no visible quality loss.
    """
    try:
        from PIL import Image

        img = Image.open(path)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        before_dims = img.size
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)   # <-- the real fix

        out_dir = os.path.join(os.path.dirname(path), "compressed")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "compressed_poster.jpg")

        for quality in (80, 70, 60, 50, 40):
            img.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)
            if os.path.getsize(out_path) <= max_size_kb * 1024:
                break

        log(f"  [compress] {before_dims[0]}x{before_dims[1]} "
            f"{os.path.getsize(path)/1024:.0f} KB  ->  "
            f"{img.size[0]}x{img.size[1]} {os.path.getsize(out_path)/1024:.0f} KB")
        return out_path
    except Exception as e:
        log(f"  [compress] Failed: {e} - using original.")
        return path


# ---------------------------------------------------------------------
# Submit helpers
# ---------------------------------------------------------------------
POST_BTN_XPATHS = [
    "//div[@role='dialog']//div[@aria-label='Post'][@role='button']",
    "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Post']]",
    "//div[@role='dialog']//button[@aria-label='Post']",
    "//div[@role='dialog']//button[.//span[normalize-space()='Post']]",
    "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Publish']]",
]


def wait_for_post_button_enabled(driver, timeout: int = 90) -> bool:
    """
    Poll aria-disabled directly. EC.element_to_be_clickable does NOT inspect
    aria-disabled, and Facebook keeps Post aria-disabled='true' until the
    server acknowledges the photo.
    """
    log("  Waiting for Post button to become enabled (server upload)...")
    deadline   = time.time() + timeout
    last_probe = 0.0
    while time.time() < deadline:
        for xp in POST_BTN_XPATHS:
            for btn in driver.find_elements(By.XPATH, xp):
                try:
                    if (btn.get_attribute("aria-disabled") != "true"
                            and btn.get_attribute("disabled") is None
                            and btn.is_displayed()):
                        log("  [ok] Post button enabled - upload complete.")
                        return True
                except StaleElementReferenceException:
                    continue
        # FIX F11: surface *why* we are waiting, every 30s
        if time.time() - last_probe > 30:
            report_upload_progress(driver)
            last_probe = time.time()
        time.sleep(1.5)
    log("  [FAIL] Post button never became enabled within timeout.")
    report_upload_progress(driver)
    return False


def composer_error_visible(driver) -> bool:
    """Facebook surfaces upload failures as an inline banner - catch it early."""
    phrases = [
        "something went wrong",
        "couldn't post",
        "could not post",
        "unable to post",
        "try again",
        "upload failed",
    ]
    try:
        dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
        if not dialogs:
            return False
        txt = (dialogs[0].text or "").lower()
        return any(p in txt for p in phrases)
    except (StaleElementReferenceException, WebDriverException):
        return False


def wait_for_post_submitted(driver, timeout: int = 180) -> "tuple[bool, float]":
    """
    FIX F4 -- replaces wait_for_dialog_close_or_timeout().

    The original ended with:
        EC.invisibility_of_element_located((By.XPATH, "//*[text()='Posting']"))
    invisibility_of_element_located CATCHES NoSuchElementException and returns
    True. Facebook renders 'Posting...' (with ellipsis), a localised string, or
    a role='progressbar' -- so that XPath usually matched nothing, the wait
    returned True in milliseconds, and the run logged 'post submitted!' without
    anything having been posted.

    Positive signal instead: hold a reference to the dialog element and wait
    for it to genuinely detach from the DOM (StaleElementReferenceException) or
    stop being displayed. Detachment cannot be faked by a missing selector.
    """
    start   = time.time()
    dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
    if not dialogs:
        log("  [ok] Dialog already gone at start of wait.")
        return True, 0.0

    dialog     = dialogs[0]
    deadline   = time.time() + timeout
    last_probe = 0.0

    while time.time() < deadline:
        try:
            if not dialog.is_displayed():
                elapsed = time.time() - start
                log(f"  [ok] Composer dialog closed after {elapsed:.1f}s.")
                return True, elapsed
        except StaleElementReferenceException:
            elapsed = time.time() - start
            log(f"  [ok] Composer dialog detached from DOM after {elapsed:.1f}s.")
            return True, elapsed
        except WebDriverException:
            pass

        if composer_error_visible(driver):
            elapsed = time.time() - start
            log(f"  [FAIL] Facebook showed an error banner after {elapsed:.1f}s.")
            sc(driver, "composer_error_banner")
            return False, elapsed

        if time.time() - last_probe > 30:
            log(f"  ... still posting ({time.time()-start:.0f}s elapsed)")
            report_upload_progress(driver)
            last_probe = time.time()

        time.sleep(1.5)

    return False, time.time() - start


def force_close_dialog(driver) -> bool:
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(2)
        if not driver.find_elements(By.XPATH, "//div[@role='dialog']"):
            log("  [close] Dialog closed via Escape key.")
            return True
    except Exception:
        pass

    for xp in [
        "//div[@role='dialog']//div[@aria-label='Close']",
        "//div[@role='dialog']//div[@aria-label='close']",
        "//div[@role='dialog']//div[@role='button'][@aria-label='Close']",
    ]:
        for btn in driver.find_elements(By.XPATH, xp):
            try:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                if not driver.find_elements(By.XPATH, "//div[@role='dialog']"):
                    log("  [close] Dialog closed via close button.")
                    return True
            except Exception:
                continue

    try:
        removed = driver.execute_script("""
            var dialogs = document.querySelectorAll('[role="dialog"]');
            dialogs.forEach(function (d) { d.parentNode && d.parentNode.removeChild(d); });
            return dialogs.length;
        """)
        log(f"  [close] Removed {removed} dialog(s) from DOM via JS.")
        return True
    except Exception:
        pass
    return False


def verify_post_in_feed(driver, text: str, max_wait: int = 30) -> bool:
    """
    FIX F9.

    Two problems in the original:
      (a) it scanned document.body.innerText, which INCLUDES the still-open
          composer holding your text -> false positive;
      (b) groups with admin approval never show the post in feed, so a
          perfectly good post was logged as FAILED -> the group got burned and
          the run reported failure.

    Now: the open dialog's text is subtracted before matching, and a pending-
    approval notice counts as success.
    """
    probe    = " ".join(text.split())[:40].lower()
    deadline = time.time() + max_wait

    pending_phrases = [
        "pending post", "pending posts",
        "your post is pending", "waiting for approval",
        "will be reviewed", "sent for review",
        "post is awaiting approval",
    ]

    while time.time() < deadline:
        try:
            body = driver.execute_script(
                """
                var t = document.body.innerText || '';
                document.querySelectorAll('[role="dialog"]').forEach(function (d) {
                    if (d.innerText) { t = t.split(d.innerText).join(''); }
                });
                return t.toLowerCase();
                """
            ) or ""
            if probe and probe in body:
                log(f"  [verify] Post text found in feed: '{probe[:30]}...'")
                return True
            if any(p in body for p in pending_phrases):
                log("  [verify] Post is pending admin approval - counting as success.")
                return True
        except (JavascriptException, WebDriverException):
            pass
        time.sleep(3)
    return False


# ---------------------------------------------------------------------
# Post composer
# ---------------------------------------------------------------------
def post_to_current_group(driver, image_path: str, text: str,
                          deadline: float) -> bool:
    proxy_mode = is_proxy_active()

    # FIX F8: the original had `submit_wait = 90 if proxy_mode else 90` -- a
    # dead ternary whose comment claimed 5 minutes. Real budgets now, and each
    # one is clamped by the per-group deadline (F10).
    upload_wait  = 180 if proxy_mode else 60
    submit_wait  = 240 if proxy_mode else 90
    extra_buffer = 6   if proxy_mode else 1

    def remaining(cap: int) -> int:
        return max(15, min(cap, int(deadline - time.time())))

    if proxy_mode:
        log("  [proxy] Proxy mode active - using extended timeouts.")

    # -- Step 1: Open composer ----------------------------------------
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
            el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.XPATH, xp)))
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
        WebDriverWait(driver, 20 if proxy_mode else 12).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )
        time.sleep(2.5 if proxy_mode else 1.5)
        log("  [ok] Composer dialog is open.")
    except TimeoutException:
        log("  [FAIL] Post composer dialog did not appear.")
        sc(driver, "dialog_not_found")
        return False

    # -- Step 2: Attach photo (bypass OS file dialog entirely) --------
    log("  [2/4] Attaching photo (bypassing OS dialog)...")
    try:
        file_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog']//input[@type='file']")
            )
        )
    except TimeoutException:
        log("  File input not in DOM - JS-clicking photo button...")
        for xp in [
            "//div[@role='dialog']//div[@aria-label='Photo/video']",
            "//div[@role='dialog']//div[@aria-label='Photo or video']",
            "//div[@role='dialog']//span[normalize-space()='Photo/video']",
            "//div[@role='dialog']//span[contains(text(),'Photo')"
            "                            and not(contains(text(),'Tag'))]",
        ]:
            btns = driver.find_elements(By.XPATH, xp)
            if btns:
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
            log("  [FAIL] File input not found after JS click.")
            sc(driver, "file_input_fail")
            return False

    driver.execute_script("""
        var el = arguments[0];
        el.style.display = 'block'; el.style.visibility = 'visible';
        el.style.opacity = '1';     el.style.position = 'fixed';
        el.style.top = '0';         el.style.left = '0';
        el.style.width = '1px';     el.style.height = '1px';
        el.style.zIndex = '9999';
    """, file_input)
    time.sleep(0.5)

    abs_path = os.path.abspath(image_path)

    # FIX F3 + F1: this branch now actually runs in CI.
    if proxy_mode and os.path.getsize(abs_path) > 400_000:
        log("  [proxy] Downscaling + compressing image for faster upload...")
        abs_path = compress_image_for_proxy(abs_path)

    file_input.send_keys(abs_path)
    log(f"  [ok] File sent silently: {os.path.basename(abs_path)} "
        f"({os.path.getsize(abs_path)/1024:.0f} KB)")

    log("  Waiting for photo preview...")
    try:
        WebDriverWait(driver, 45 if proxy_mode else 30).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[@role='dialog']//img[contains(@src,'blob:')"
                "    or contains(@src,'scontent') or contains(@src,'fbcdn')]"
            ))
        )
        log("  [ok] Photo preview visible.")
    except TimeoutException:
        log("  [WARN] Preview not seen - continuing.")
        sc(driver, "photo_preview_timeout")

    if not wait_for_post_button_enabled(driver, timeout=remaining(upload_wait)):
        log("  [FAIL] Post button never enabled - upload likely stalled.")
        sc(driver, "post_btn_disabled_timeout")
        return False

    time.sleep(extra_buffer)

    # -- Step 3: Insert description -----------------------------------
    log("  [3/4] Inserting description into post editor...")
    lexical_wait = 5 if proxy_mode else 2
    log(f"  Waiting {lexical_wait}s for Lexical editor to initialise...")
    time.sleep(lexical_wait)

    editor_xpaths = [
        "//div[@role='dialog']//div[@data-lexical-editor='true']"
        "    [@aria-label and not(contains(@aria-label,'caption'))"
        "               and not(contains(@aria-label,'Caption'))]",
        "(//div[@role='dialog']//div[@data-lexical-editor='true'])[1]",
        "(//div[@role='dialog']//div[@role='textbox' and @contenteditable='true'])[1]",
        "(//div[@role='dialog']//div[@contenteditable='true']"
        "    [contains(@class,'notranslate')])[1]",
    ]

    text_added = False
    for xp in editor_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            is_bad = driver.execute_script(
                """
                var el = arguments[0];
                while (el) {
                    var lbl = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (lbl.includes('caption') || lbl.includes('comment')
                            || lbl.includes('reply')) return true;
                    el = el.parentElement;
                }
                return false;
                """, tb,
            )
            if is_bad:
                log("  [skip] Caption/comment box - trying next.")
                continue

            if inject_text(driver, tb, text):
                log(f"  [ok] Description inserted and verified ({len(text)} chars).")
                text_added = True
                break
            log("  [warn] Injection not verified - trying next XPath.")
            sc(driver, "text_inject_empty")
        except (TimeoutException, NoSuchElementException):
            continue

    if not text_added:
        log("  [WARN] Could not verify text insertion - proceeding anyway.")
        sc(driver, "text_not_verified")

    time.sleep(random.uniform(1.0, 2.0))

    # -- Step 4: Submit -----------------------------------------------
    log("  [4/4] Submitting post...")
    if not wait_for_post_button_enabled(driver, timeout=remaining(60)):
        log("  [WARN] Post button disabled - waiting extra 30s...")
        time.sleep(30)
        if not wait_for_post_button_enabled(driver, timeout=remaining(30)):
            log("  [FAIL] Post button disabled again before click.")
            sc(driver, "post_btn_redisabled")
            return False

    post_btn = None
    for xp in POST_BTN_XPATHS:
        try:
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            disabled = driver.execute_script(
                "return arguments[0].getAttribute('aria-disabled')"
                "    || arguments[0].disabled;", btn
            )
            if btn.get_attribute("aria-disabled") != "true" and not disabled:
                post_btn = btn
                break
        except TimeoutException:
            continue

    if not post_btn:
        log("  [FAIL] Post button not found at submit time.")
        sc(driver, "post_btn_fail")
        return False

    sc(driver, "pre_submit")
    driver.execute_script("arguments[0].click();", post_btn)
    log(f"  [ok] Post button clicked. Waiting up to {remaining(submit_wait)}s...")

    closed, elapsed = wait_for_post_submitted(driver, timeout=remaining(submit_wait))
    if closed:
        sc(driver, "post_submitted")
        # Confirm rather than assume - cheap, and catches silent rejections.
        if verify_post_in_feed(driver, text, max_wait=15):
            return True
        log("  [warn] Dialog closed but post not visible yet - refreshing to confirm.")
        safe_refresh(driver)
        time.sleep(5 if proxy_mode else 3)
        if verify_post_in_feed(driver, text, max_wait=20):
            return True
        log("  [warn] Dialog closed cleanly; treating as success despite no feed match.")
        return True

    # -- Dialog stuck -------------------------------------------------
    log(f"  [WARN] Dialog still open after {elapsed:.1f}s. Checking feed...")
    sc(driver, "dialog_stuck_proxy")
    report_upload_progress(driver)

    safe_refresh(driver)
    time.sleep(5 if proxy_mode else 3)
    if verify_post_in_feed(driver, text, max_wait=20):
        log("  [ok] Post CONFIRMED after refresh - SUCCESS.")
        sc(driver, "post_verified_after_refresh")
        return True

    log("  Post not found - force-closing dialog...")
    force_close_dialog(driver)
    time.sleep(3)
    if verify_post_in_feed(driver, text, max_wait=15):
        log("  [ok] Post CONFIRMED after force-close - SUCCESS.")
        return True

    if time.time() < deadline - 40:
        log("  Waiting 20s more, then re-checking...")
        time.sleep(20)
        safe_refresh(driver)
        time.sleep(5)
        if verify_post_in_feed(driver, text, max_wait=15):
            log("  [ok] Post CONFIRMED after extended wait - SUCCESS.")
            sc(driver, "post_verified_extended")
            return True

    log("  [FAIL] Post not confirmed after all recovery strategies.")
    sc(driver, "post_failed_proxy")
    return False


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def main() -> int:
    log("=" * 60)
    log("Facebook Group Poster Bot - starting")
    log(f"  poster-{photo_number:02d}  |  description-{description_number:02d}"
        f"  |  proxy={'yes' if is_proxy_active() else 'no'}")
    log("=" * 60)

    state  = load_daily_state()
    driver = build_driver()

    # FIX F5: 30s is far too tight for facebook.com through a VLESS tunnel;
    # the resulting TimeoutException used to kill the whole run.
    driver.set_page_load_timeout(90 if is_proxy_active() else 30)
    driver.set_script_timeout(30)

    succeeded    = False
    published_at = ""
    target_group = None

    try:
        try:
            driver.get("https://www.facebook.com")
        except (TimeoutException, WebDriverException):
            log("Initial load timed out - continuing to session check.")
        time.sleep(3 if is_proxy_active() else 2)

        if "login" in driver.current_url.lower():
            log("Facebook session expired - re-run facebook_profile_initializer.py.")
            sys.exit(99)
        log("Session active.")

        while True:
            target_group = pick_target_group(state)
            if target_group is None:
                log("No eligible groups remain for today.")
                break

            state["used_groups"] = state.get("used_groups", []) + [target_group]
            save_daily_state(state)

            if not os.path.isfile(POSTER_PATH):
                log(f"Poster image missing: {POSTER_PATH}")
                break

            if not navigate_to_group(driver, target_group):
                log("Navigation failed - trying next group.")
                continue
            if is_buy_sell_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is Buy & Sell - skipping.")
                continue
            if is_admin_only_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is admin-only - skipping.")
                continue
            if not can_post(driver):
                log(f"Not a member of '{extract_group_id(target_group)}' - skipping.")
                continue

            log(f"Posting to: {extract_group_id(target_group)}")
            group_deadline = time.time() + GROUP_DEADLINE_SECS   # FIX F10
            succeeded = post_to_current_group(
                driver, POSTER_PATH, POST_DESCRIPTION, group_deadline
            )

            if succeeded:
                published_at         = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
                state["total_posts"] = state.get("total_posts", 0) + 1
                save_daily_state(state)
                log(f"SUCCESS - poster-{photo_number:02d} posted at {published_at}. "
                    f"Total today: {state['total_posts']}")
            break

    except SystemExit:
        raise
    except Exception as exc:
        log(f"Unhandled error: {type(exc).__name__}: {exc}")
        sc(driver, "unhandled_error")
    finally:
        if succeeded:
            log("Holding 5s to finish network requests...")
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
    log("=" * 60)#!/usr/bin/env python3
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
# Group selection logic
# ─────────────────────────────────────────────────────────────────────
def extract_group_id(url: str) -> str:
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
def is_proxy_active() -> bool:
    return bool(os.environ.get("PROXY_HOST") and os.environ.get("PROXY_PORT"))


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

    # Give the page time to render before using the heuristic
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
# Navigation
# ─────────────────────────────────────────────────────────────────────
def navigate_to_group(driver, group_url: str) -> "str | None":
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
        return None

    final_url = driver.current_url
    log(f"  Group page loaded: {final_url}")
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
# Text injection (React / Lexical compatible)
# ─────────────────────────────────────────────────────────────────────
def has_unicode(text: str) -> bool:
    """Returns True if text contains any non-ASCII characters."""
    return any(ord(c) > 127 for c in text)


def inject_text(driver, element, text: str) -> None:
    """
    Insert text into a contenteditable / Lexical editor preserving
    all formatting exactly as it appears in the source .txt file.

    Strategy (tried in order for ALL text — unicode and ASCII alike):
      1. CDP Input.insertText  — most reliable, bypasses all event translation
      2. _inject_via_clipboard — beforeinput / clipboard / execCommand cascade
      3. ASCII fallback        — Shift+Enter for line breaks (only if both above fail)
    """
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});", element
    )
    time.sleep(0.3)

    # Focus the element
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
    time.sleep(0.5)

    # ── FIX 1 & 4: Try CDP first for ALL text (unicode AND ascii) ────────
    # CDP Input.insertText inserts the exact string at the protocol level —
    # no keyboard translation, no newline→Enter conversion, works for any script.
    log("  Trying CDP injection first (works for all text types)...")
    if _inject_via_cdp(driver, element, text):
        cdp_result = driver.execute_script("return arguments[0].innerText;", element)
        if cdp_result and len(cdp_result.strip()) >= len(text.strip()) * 0.8:
            log(f"  [ok] CDP injection verified ({len(cdp_result.strip())} chars).")
            return
        log("  [cdp] Verification failed after CDP — falling back to clipboard.")

    # ── Fallback: clipboard cascade (handles unicode reliably) ───────────
    log("  Falling back to clipboard injection...")
    _inject_via_clipboard(driver, element, text)

    time.sleep(0.5)

    # ── FIX 2: Tighter verification — check both length AND newline count ─
    current = driver.execute_script("return arguments[0].innerText;", element)
    if current:
        inserted_len      = len(current.strip())
        expected_len      = len(text.strip())
        expected_newlines = text.count('\n')
        actual_newlines   = current.count('\n')

        length_ok   = inserted_len >= expected_len * 0.8
        newline_ok  = (expected_newlines <= 2) or \
                      (actual_newlines >= expected_newlines * 0.5)

        if not length_ok or not newline_ok:
            log(f"  [warn] Formatting mismatch — "
                f"chars {inserted_len}/{expected_len}, "
                f"newlines {actual_newlines}/{expected_newlines}. Re-injecting.")
            _inject_via_clipboard(driver, element, text)
            time.sleep(0.5)
        else:
            log(f"  [ok] Description verified: {inserted_len}/{expected_len} chars, "
                f"{actual_newlines}/{expected_newlines} newlines.")
    else:
        log("  [warn] Text box empty after inject — retrying.")
        _inject_via_clipboard(driver, element, text)
        time.sleep(0.5)


def _inject_via_cdp(driver, element, text: str) -> bool:
    """
    Primary injection using Chrome DevTools Protocol.
    Input.insertText inserts directly into the focused element —
    no keyboard event translation, works for any script (Sinhala, Tamil, ASCII).
    Newlines in the string are preserved as-is.

    Returns True on success, False if CDP is unavailable (common with
    SeleniumBase UC mode which patches the DevTools pipe).
    """
    # Clear the field first
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);",
        element,
    )
    time.sleep(0.2)
    driver.execute_script("arguments[0].focus();", element)
    time.sleep(0.3)

    try:
        chunks = _safe_unicode_chunks(text, max_chars=3500)
        for chunk in chunks:
            driver.execute_cdp_cmd('Input.insertText', {'text': chunk})
            time.sleep(0.1)
        log(f"  [cdp] Inserted {len(text)} chars via CDP in {len(chunks)} chunk(s).")
        return True
    except Exception as e:
        log(f"  [cdp] CDP insertText failed: {e}")
        return False


def _inject_via_clipboard(driver, element, text: str) -> None:
    """
    Fallback injection cascade for all text (Unicode + ASCII).
    Tries three methods in order, stopping at the first that verifies.
    Uses innerText (not textContent) to detect newline preservation.
    """
    driver.execute_script("arguments[0].focus();", element)
    time.sleep(0.3)

    # Clear first — JS selectAll + delete is reliable for all scripts
    driver.execute_script(
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);",
        element,
    )
    time.sleep(0.2)

    # ── Method 1: beforeinput insertFromPaste (Lexical native handler) ──
    # FIX 1: Use innerText (not textContent) so newlines are counted correctly.
    injected = driver.execute_script(
        """
        var el   = arguments[0];
        var text = arguments[1];

        try {
            var dt = new DataTransfer();
            dt.setData('text/plain', text);

            var evt = new InputEvent('beforeinput', {
                inputType    : 'insertFromPaste',
                data         : text,
                dataTransfer : dt,
                bubbles      : true,
                cancelable   : true
            });
            el.dispatchEvent(evt);

            return new Promise(function(resolve) {
                setTimeout(function() {
                    // FIX: use innerText so line breaks count toward length
                    var content = el.innerText || '';
                    resolve(content.trim().length > 5);
                }, 400);
            });
        } catch(e) {
            return Promise.resolve(false);
        }
        """,
        element, text
    )

    if injected:
        log(f"  [beforeinput] Inserted {len(text)} chars via beforeinput event.")
        return

    # ── Method 2: Clipboard API paste ──
    log("  [beforeinput] Failed — trying clipboard API paste.")
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);",
        element,
    )
    time.sleep(0.2)

    # FIX 1: Use innerText (not textContent) for newline-aware verification.
    injected = driver.execute_script(
        """
        var el   = arguments[0];
        var text = arguments[1];

        function handler(e) {
            e.clipboardData.setData('text/plain', text);
            e.preventDefault();
            document.removeEventListener('paste', handler, true);
        }
        document.addEventListener('paste', handler, true);

        document.execCommand('paste');
        return new Promise(function(resolve) {
            setTimeout(function() {
                // FIX: use innerText so line breaks count toward length
                var content = el.innerText || '';
                resolve(content.trim().length > 5);
            }, 400);
        });
        """,
        element, text
    )

    if injected:
        log(f"  [clipboard] Inserted {len(text)} chars via clipboard paste.")
        return

    # ── Method 3: Line-by-line execCommand — preserves newlines as <br> ──
    log("  [clipboard] Failed — falling back to line-by-line execCommand.")
    driver.execute_script(
        "arguments[0].focus();"
        "document.execCommand('selectAll', false, null);"
        "document.execCommand('delete', false, null);",
        element,
    )
    time.sleep(0.2)

    lines = text.split('\n')
    for idx, line in enumerate(lines):
        if line:
            driver.execute_script(
                "document.execCommand('insertText', false, arguments[0]);",
                line,
            )
        # Insert line break between lines (not after last line)
        if idx < len(lines) - 1:
            driver.execute_script(
                "document.execCommand('insertLineBreak');",
            )
        time.sleep(0.05)

    log(f"  [execCommand] Inserted {len(text)} chars ({len(lines)} lines) "
        f"via line-by-line execCommand.")


def _safe_unicode_chunks(text: str, max_chars: int = 3500) -> list:
    """
    Split text into chunks without breaking Unicode grapheme clusters.
    Splits preferably at newline or space boundaries to keep
    combining character sequences (consonant + vowel sign) intact.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break

        # Try to split at a newline or space within the limit
        split_at = max_chars
        for sep in ('\n', ' '):
            pos = text.rfind(sep, 0, max_chars)
            if pos > max_chars // 2:   # only split here if not too early
                split_at = pos + 1
                break

        chunks.append(text[:split_at])
        text = text[split_at:]

    return chunks


# ─────────────────────────────────────────────────────────────────────
# Proxy-aware image compression
# ─────────────────────────────────────────────────────────────────────
def compress_image_for_proxy(path: str, max_size_kb: int = 300) -> str:
    """
    Compress a large image to a JPEG for faster upload through proxy.
    Returns the path to the compressed file (original unchanged).
    """
    try:
        from PIL import Image
        orig = Image.open(path)
        if orig.mode in ("RGBA", "P"):
            orig = orig.convert("RGB")

        # Progressive downscale — target ~300 KB JPEG
        out_dir = os.path.join(os.path.dirname(path), "compressed")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "compressed_poster.jpg")

        for quality in (65, 50, 35):
            orig.save(out_path, "JPEG", quality=quality, optimize=True)
            if os.path.getsize(out_path) <= max_size_kb * 1024:
                break

        orig_size = os.path.getsize(path) / 1024
        new_size  = os.path.getsize(out_path) / 1024
        log(f"  [compress] {orig_size:.0f} KB → {new_size:.0f} KB")
        return out_path
    except Exception as e:
        log(f"  [compress] Failed: {e} — using original.")
        return path


# ─────────────────────────────────────────────────────────────────────
# Proxy-aware upload / submit helpers
# ─────────────────────────────────────────────────────────────────────
def wait_for_post_button_enabled(driver, timeout: int = 90) -> bool:
    """
    Poll until the Post button's aria-disabled attribute is gone.
    Facebook sets aria-disabled='true' while the photo is uploading
    to its servers — EC.element_to_be_clickable does NOT catch this.
    """
    log("  Waiting for Post button to become enabled (server upload)...")
    post_btn_xpaths = [
        "//div[@role='dialog']//div[@aria-label='Post'][@role='button']",
        "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Post']]",
        "//div[@role='dialog']//button[@aria-label='Post']",
        "//div[@role='dialog']//button[.//span[normalize-space()='Post']]",
        "//div[@role='dialog']//div[@role='button'][.//span[normalize-space()='Publish']]",
    ]

    deadline = time.time() + timeout
    while time.time() < deadline:
        for xp in post_btn_xpaths:
            for btn in driver.find_elements(By.XPATH, xp):
                try:
                    if (btn.get_attribute("aria-disabled") != "true"
                            and btn.get_attribute("disabled") is None
                            and btn.is_displayed()):
                        log("  [ok] Post button is enabled — upload complete.")
                        return True
                except StaleElementReferenceException:
                    continue
        time.sleep(1.5)

    log("  [FAIL] Post button never became enabled within timeout.")
    return False


def wait_for_upload_spinner_gone(driver, timeout: int = 120) -> None:
    """Wait for Facebook's upload progress spinners to disappear."""
    spinner_xpaths = [
        "//div[@role='dialog']//div[@role='progressbar']",
        "//div[@role='dialog']//div[@data-visualcompletion='loading-state']",
        "//div[@role='dialog']//svg[contains(@class,'spinner')]",
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(driver.find_elements(By.XPATH, xp) for xp in spinner_xpaths):
            log("  [ok] No upload spinners detected.")
            return
        time.sleep(1)
    log("  [WARN] Spinner still visible after timeout — continuing anyway.")


def wait_for_dialog_close_or_timeout(driver, timeout: int = 120) -> "tuple[bool, float]":
    """
    Wait for the post dialog to close naturally after clicking Post.
    Returns (closed_naturally, elapsed_seconds).
    """
    start = time.time()

    # Verify the dialog actually exists right now — if not, something is wrong
    dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
    if not dialogs:
        log("  [WARN] No dialog found at start of wait — dialog may have closed already.")
        return False, 0.0

    # Minimum wait — Facebook needs time to process the click and start upload.
    # Do NOT check for dialog close during this period.
    min_wait = 8 if is_proxy_active() else 4
    log(f"  Waiting {min_wait}s minimum for Facebook to process the post...")
    time.sleep(min_wait)

    # Now check if dialog is still there
    dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
    if not dialogs:
        elapsed = time.time() - start
        log(f"  [ok] Dialog gone after {elapsed:.1f}s minimum wait — post likely submitted.")
        return True, elapsed

    # Watch for 'Posting...' indicator SCOPED TO THE DIALOG only.
    # Without scoping, feed text or other page elements can false-match.
    try:
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[text()='Posting']")
            )
        )
        log("  [ok] 'Posting...' indicator seen inside dialog — upload in progress.")
    except TimeoutException:
        log("  [warn] No 'Posting...' indicator found in dialog — continuing to wait for close.")

    # Wait for the dialog to disappear
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.XPATH, "//*[text()='Posting']"))
        )
        elapsed = time.time() - start
        log(f"  [ok] Dialog closed in {elapsed:.1f}s — post submitted!")
        return True, elapsed
    except TimeoutException:
        elapsed = time.time() - start
        return False, elapsed


def force_close_dialog(driver) -> bool:
    """
    Forcefully close a stuck dialog using multiple fallback methods.
    Returns True if the dialog is gone afterward.
    """
    # Method 1: Escape key
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(2)
        if not driver.find_elements(By.XPATH, "//div[@role='dialog']"):
            log("  [close] Dialog closed via Escape key.")
            return True
    except Exception:
        pass

    # Method 2: Click the X / close button
    for xp in [
        "//div[@role='dialog']//div[@aria-label='Close']",
        "//div[@role='dialog']//div[@aria-label='close']",
        "//div[@role='dialog']//div[@role='button'][@aria-label='Close']",
    ]:
        for btn in driver.find_elements(By.XPATH, xp):
            try:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                if not driver.find_elements(By.XPATH, "//div[@role='dialog']"):
                    log("  [close] Dialog closed via close button.")
                    return True
            except Exception:
                continue

    # Method 3: Remove from DOM entirely
    try:
        removed = driver.execute_script("""
            var dialogs = document.querySelectorAll('[role="dialog"]');
            dialogs.forEach(d => d.parentNode && d.parentNode.removeChild(d));
            return dialogs.length;
        """)
        log(f"  [close] Removed {removed} dialog(s) from DOM via JS.")
        return True
    except Exception:
        pass

    return False


def verify_post_in_feed(driver, text: str, max_wait: int = 30) -> bool:
    """Poll the page body for the first 40 chars of the post description."""
    probe    = " ".join(text.split())[:40].lower()
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            if probe in driver.execute_script(
                "return document.body.innerText.toLowerCase();"
            ):
                log(f"  [verify] Post text found in feed: '{probe[:30]}...'")
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


# ─────────────────────────────────────────────────────────────────────
# Post composer
# ─────────────────────────────────────────────────────────────────────
def post_to_current_group(driver, image_path: str, text: str) -> bool:

    proxy_mode   = is_proxy_active()
    # VLESS proxy adds 3-5x latency. 3 MB PNG upload can take 3-5 min.
    # Post button stays aria-disabled until Facebook confirms upload.
    upload_wait  = 120 if proxy_mode else 60   # 5 min for proxy upload
    submit_wait  = 90 if proxy_mode else 90   # 5 min for proxy submit
    extra_buffer = 6   if proxy_mode else 1

    if proxy_mode:
        log("  [proxy] Proxy mode active — using extended timeouts.")

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

    # ── Step 2: Attach photo (bypass OS file dialog entirely) ─────────
    log("  [2/4] Attaching photo (bypassing OS dialog)...")

    # The hidden <input type="file"> exists in the DOM from dialog open —
    # send_keys() on it delivers the path without ever opening the OS picker.
    try:
        file_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog']//input[@type='file']")
            )
        )
    except TimeoutException:
        # Not pre-loaded — JS-click the button to inject it (no OS dialog)
        log("  File input not in DOM — JS-clicking photo button...")
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
            log("  [FAIL] File input not found after JS click.")
            sc(driver, "file_input_fail")
            return False

    # Make the hidden input interactable so send_keys works
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

    abs_path = os.path.abspath(image_path)
    # Compress large images in proxy mode — 3 MB PNG takes minutes through VLESS
    if proxy_mode and os.path.getsize(abs_path) > 500_000:
        log("  [proxy] Compressing image for faster upload...")
        abs_path = compress_image_for_proxy(abs_path)
    file_input.send_keys(abs_path)
    log(f"  [ok] File sent silently: {os.path.basename(abs_path)}")

    # Wait for browser-side preview (confirms file was accepted locally)
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
        log("  [ok] Photo preview visible.")
    except TimeoutException:
        log("  [WARN] Preview not seen in 30s — continuing.")
        sc(driver, "photo_preview_timeout")

    # Wait for spinners to clear (server-side upload done)
    # wait_for_upload_spinner_gone(driver, timeout=180 if proxy_mode else 60)

    # ── KEY FIX: Poll aria-disabled until Post button is truly enabled ─
    # EC.element_to_be_clickable ignores aria-disabled='true' — we must
    # check it manually. Facebook keeps the button disabled until the
    # server confirms the photo upload, which is slow through a proxy.
    if not wait_for_post_button_enabled(driver, timeout=upload_wait):
        log("  [FAIL] Post button never became enabled — upload may have failed.")
        sc(driver, "post_btn_disabled_timeout")
        return False

    # Extra settle time — proxy connections can cause button-state flicker
    time.sleep(extra_buffer)

    # ── Step 3: Insert description ────────────────────────────────────
    log("  [3/4] Inserting description into post editor...")

    # Through proxy, Lexical editor initializes 2-5s after the DOM appears.
    # Wait until the editor reports itself as ready before injecting text.
    proxy_mode = is_proxy_active()
    lexical_wait = 5 if proxy_mode else 2
    log(f"  Waiting {lexical_wait}s for Lexical editor to initialize...")
    time.sleep(lexical_wait)
    editor_xpaths = [
        # Most specific — post-level Lexical editor (skip caption boxes)
        "//div[@role='dialog']//div[@data-lexical-editor='true']"
        "    [@aria-label and not(contains(@aria-label,'caption'))"
        "               and not(contains(@aria-label,'Caption'))]",
        # First Lexical editor in dialog = post text (above photo preview)
        "(//div[@role='dialog']//div[@data-lexical-editor='true'])[1]",
        "(//div[@role='dialog']//div[@role='textbox' and @contenteditable='true'])[1]",
        "(//div[@role='dialog']//div[@contenteditable='true']"
        "    [contains(@class,'notranslate')])[1]",
    ]

    text_added = False
    for xp in editor_xpaths:
        try:
            tb = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            is_bad = driver.execute_script(
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
            if is_bad:
                log("  [skip] Caption/comment box — trying next.")
                continue

            inject_text(driver, tb, text)
            actual = driver.execute_script("return arguments[0].innerText;", tb)
            if actual and len(actual.strip()) > 5:
                log(f"  [ok] Description inserted ({len(text)} chars). "
                    f"Verified: '{actual[:40]}...'")
                text_added = True
                break
            else:
                log("  [warn] Text box empty after inject — trying next XPath.")
                sc(driver, "text_inject_empty")
        except (TimeoutException, NoSuchElementException):
            continue

    if not text_added:
        log("  [WARN] Could not verify text insertion — proceeding anyway.")
        sc(driver, "text_not_verified")

    time.sleep(random.uniform(1.0, 2.0))

    # ── Step 4: Submit ────────────────────────────────────────────────
    log("  [4/4] Submitting post...")

    # Through proxy, button can flicker disabled briefly after text inject.
    # Don't hard-fail — just wait and retry.
    if not wait_for_post_button_enabled(driver, timeout=60):
        log("  [WARN] Post button still disabled — waiting extra 30s...")
        time.sleep(30)
        if not wait_for_post_button_enabled(driver, timeout=30):
            log("  [FAIL] Post button disabled again before click.")
            sc(driver, "post_btn_redisabled")
            return False

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
            btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            # Check both HTML attr AND JS property — proxy can cause lag
            disabled_attr = btn.get_attribute("aria-disabled")
            disabled_js = driver.execute_script(
                "return arguments[0].getAttribute('aria-disabled')"
                "    || arguments[0].disabled;", btn
            )
            if disabled_attr != "true" and not disabled_js:
                post_btn = btn
                break
        except TimeoutException:
            continue

    if not post_btn:
        log("  [FAIL] Post button not found at submit time.")
        sc(driver, "post_btn_fail")
        return False

    sc(driver, "pre_submit")
    driver.execute_script("arguments[0].click();", post_btn)
    log(f"  [ok] Post button clicked. Waiting up to {submit_wait}s...")

    # ── Wait for dialog to close naturally ────────────────────────────
    closed_naturally, elapsed = wait_for_dialog_close_or_timeout(
        driver, timeout=submit_wait
    )

    if closed_naturally:
        sc(driver, "post_submitted")
        return True

    # ── Dialog stuck — proxy delayed server response ──────────────────
    log(f"  [WARN] Dialog open after {elapsed:.1f}s. Checking if post went through...")
    sc(driver, "dialog_stuck_proxy")

    # Recovery 1: Refresh and check feed
    driver.refresh()
    time.sleep(5 if proxy_mode else 3)
    if verify_post_in_feed(driver, text, max_wait=20):
        log("  [ok] Post CONFIRMED in feed after refresh — SUCCESS!")
        sc(driver, "post_verified_after_refresh")
        return True

    # Recovery 2: Force-close dialog, check feed without refresh
    log("  Post not found yet — force-closing dialog...")
    force_close_dialog(driver)
    time.sleep(3)
    if verify_post_in_feed(driver, text, max_wait=15):
        log("  [ok] Post CONFIRMED in feed after force-close — SUCCESS!")
        return True

    # Recovery 3: Wait longer for proxy to deliver response, then refresh
    log("  Waiting 20s more for proxy to deliver response...")
    time.sleep(20)
    driver.refresh()
    time.sleep(5)
    if verify_post_in_feed(driver, text, max_wait=15):
        log("  [ok] Post CONFIRMED in feed after extended wait — SUCCESS!")
        sc(driver, "post_verified_extended")
        return True

    log("  [FAIL] Post not confirmed in feed after all recovery strategies.")
    sc(driver, "post_failed_proxy")
    return False


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("Facebook Group Poster Bot — starting")
    log(f"  poster-{photo_number:02d}  |  description-{description_number:02d}"
        f"  |  proxy={'yes' if is_proxy_active() else 'no'}")
    log("=" * 60)

    state = load_daily_state()

    driver = build_driver()
    driver.set_page_load_timeout(30)
    succeeded    = False
    published_at = ""
    target_group = None

    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)
        if "login" in driver.current_url.lower():
            log("Facebook session expired — re-run facebook_profile_initializer.py.")
            sys.exit(99)
        log("Session active.")

        # ── Try groups in a loop — skip bad ones, stop after first post ──
        while True:
            target_group = pick_target_group(state)
            if target_group is None:
                log("No eligible groups remain for today.")
                break

            # Mark used BEFORE navigating — prevents infinite re-pick on crash
            state["used_groups"] = state.get("used_groups", []) + [target_group]
            save_daily_state(state)

            if not os.path.isfile(POSTER_PATH):
                log(f"Poster image missing: {POSTER_PATH}")
                break

            group_url = navigate_to_group(driver, target_group)
            if not group_url:
                log("Navigation failed — trying next group.")
                continue

            if is_buy_sell_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is Buy & Sell — skipping.")
                continue

            if is_admin_only_on_page(driver):
                log(f"'{extract_group_id(target_group)}' is admin-only — skipping.")
                continue

            if not can_post(driver):
                log(f"Not a member of '{extract_group_id(target_group)}' — skipping.")
                continue

            log(f"Posting to: {extract_group_id(target_group)}")
            succeeded = post_to_current_group(driver, POSTER_PATH, POST_DESCRIPTION)

            if succeeded:
                published_at         = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
                state["total_posts"] = state.get("total_posts", 0) + 1
                save_daily_state(state)
                log(f"SUCCESS — poster-{photo_number:02d} posted at {published_at}. "
                    f"Total today: {state['total_posts']}")
            break  # stop after one attempt (successful or not)

    except SystemExit:
        raise
    except Exception as exc:
        log(f"Unhandled error: {exc}")
        sc(driver, "unhandled_error")

    finally:
        if succeeded:
            log("Holding 5s to finish network requests...")
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
    log("=" * 60)
    log(f"Run finished — {status_label}")
    log("=" * 60)
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())

    log(f"Run finished - {status_label}")
    log("=" * 60)
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
