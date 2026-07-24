from seleniumbase import SB
import time
import os
import random
FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")
if not FB_EMAIL or not FB_PASSWORD:
    raise SystemExit(
        "Missing credentials. Set FB_EMAIL and FB_PASSWORD as environment "
        "variables prior to execution."
    )


def human_type(sb, selectors, text):
    """Finds the first visible selector from an array and types realistically."""
    target_selector = None
    for selector in selectors:
        if sb.is_element_visible(selector):
            target_selector = selector
            break
    if not target_selector:
        raise Exception(f"Failed to map input fields for selectors: {selectors}")

    sb.click(target_selector)
    sb.clear(target_selector)
    for char in text:
        sb.press_keys(target_selector, char)
        time.sleep(random.uniform(0.08, 0.20))


def handle_captcha_if_present(sb):
    """Detects reCAPTCHA iframe and uses UC auto-click solver."""
    captcha_iframe_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[title*='reCAPTCHA']",
        "iframe[src*='captcha']",
    ]
    for frame_sel in captcha_iframe_selectors:
        if sb.is_element_visible(frame_sel):
            print("⚠️ CAPTCHA Checkpoint detected! Attempting native bypass...")
            try:
                # Native SeleniumBase UC CAPTCHA Solver
                sb.uc_gui_click_captcha()
                time.sleep(5)
                return True
            except Exception as e:
                print(f"⚠️ Auto CAPTCHA solver attempt failed: {e}")
    return False


def run_script():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = os.path.join(base_dir, "profiles", "facebook_stable_session")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    print("🚀 Initializing Stealth Facebook Authenticator...")

    # Stripped out conflicting automation flags that trigger reCAPTCHA
    CLEAN_UC_FLAGS = (
        "--disable-dev-shm-usage "
        "--disable-blink-features=AutomationControlled "
        "--lang=en-US"
    )

    with SB(
        browser="chrome",
        uc=True,                  # Native Undetected ChromeDriver mode
        xvfb=True,                # Virtual frame buffer for headless Linux execution
        user_data_dir=USER_DATA_DIR,
        chromium_arg=CLEAN_UC_FLAGS,
    ) as sb:
        try:
            print("🌍 Routing to Facebook Login Portal...")
            sb.uc_open_with_reconnect("https://www.facebook.com", reconnect_time=6)
            time.sleep(4)

            # Check if Meta CAPTCHA checkpoint is present immediately on page load
            handle_captcha_if_present(sb)

            email_selectors = [
                "input[name='email']",
                "#email",
                "input[type='text']",
                "input[placeholder*='Email']",
            ]
            password_selectors = [
                "input[name='pass']",
                "#pass",
                "input[type='password']",
                "input[placeholder*='Password']",
            ]

            is_standard_login = any(sb.is_element_visible(sel) for sel in email_selectors)

            if not is_standard_login:
                print("🔄 Checking for saved session or alternative login layout...")
                try:
                    sb.click('//*[contains(text(), "Continue") or contains(text(), "Log in as")]')
                except Exception:
                    if sb.is_element_visible('div[role="button"]'):
                        sb.click('div[role="button"]')

                time.sleep(3)
                handle_captcha_if_present(sb)

                if any(sb.is_element_visible(sel) for sel in password_selectors):
                    print("⌨️ Password requested for profile. Injecting...")
                    human_type(sb, password_selectors, FB_PASSWORD)
                    time.sleep(random.uniform(1.0, 2.0))
                    active_pass_field = next(sel for sel in password_selectors if sb.is_element_visible(sel))
                    sb.press_keys(active_pass_field, "\n")
            else:
                print("⌨️ Standard login form detected. Injecting credentials...")
                human_type(sb, email_selectors, FB_EMAIL)
                time.sleep(random.uniform(1.0, 2.0))

                human_type(sb, password_selectors, FB_PASSWORD)
                time.sleep(random.uniform(1.2, 2.2))

                active_pass_field = next(sel for sel in password_selectors if sb.is_element_visible(sel))
                sb.press_keys(active_pass_field, "\n")

            print("\n⏳ Monitoring authentication state...")

            logged_in = False
            for attempt in range(60):  # 5 minute poll
                time.sleep(5)

                # Solve CAPTCHA if it popped up post-login submission
                handle_captcha_if_present(sb)

                cookies = sb.get_cookies()
                has_c_user = any(cookie.get("name") == "c_user" for cookie in cookies)

                if has_c_user:
                    logged_in = True
                    print("\n✅ Session verified (c_user found) — Login Successful!")
                    if os.path.exists("facebook_auth.png"):
                        os.remove("facebook_auth.png")
                    break

                sb.save_screenshot("facebook_auth.png")
                print(f"[{attempt+1}] State saved to 'facebook_auth.png'. Check for 2FA or CAPTCHA.")

            if not logged_in:
                print("\n⚠️ Authentication incomplete. Session token not received.")

        except Exception as error_msg:
            timestamp = int(time.time())
            os.makedirs("screenshots", exist_ok=True)
            error_img_path = f"screenshots/failure_initializer_{timestamp}.png"
            sb.save_screenshot(error_img_path)
            print(f"\n❌ Exception triggered: {error_msg}")
        finally:
            print("💾 Operations finished. Saving profile state...")
if __name__ == "__main__":
    run_script()