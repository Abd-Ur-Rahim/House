from seleniumbase import SB
import time
import os
import random

FB_EMAIL = os.environ.get("FB_EMAIL",'rockingrock2003@gmail.com')
FB_PASSWORD = os.environ.get("FB_PASSWORD",'Abdur@15497')

if not FB_EMAIL or not FB_PASSWORD:
    raise SystemExit(
        "Missing credentials. Set FB_EMAIL and FB_PASSWORD as environment "
        "variables (locally via a .env file that is git-ignored, or as "
        "repo secrets if this ever runs in CI)."
    )

def human_type(sb, selectors, text):
    """Finds the first visible selector from an array and types realistically."""
    target_selector = None
    for selector in selectors:
        if sb.is_element_visible(selector):
            target_selector = selector
            break
            
    if not target_selector:
        raise Exception(f"Failed to map any valid layout target input fields for selectors: {selectors}")
        
    sb.click(target_selector)
    sb.clear(target_selector)
    for char in text:
        sb.press_keys(target_selector, char)
        time.sleep(random.uniform(0.07, 0.22)) # Simulates physical human finger cadence

def run_script():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = os.path.join(base_dir, "profiles", "facebook_stable_session")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    print("🚀 Initializing Stable Facebook Core (Adaptive Input Mapping)...")

    COMPATIBILITY_FLAGS = (
        "--disable-gpu "
        "--disable-software-rasterizer "
        "--window-size=1440,900 "
        "--no-sandbox "
        "--disable-dev-shm-usage "
        "--disable-blink-features=AutomationControlled "
    )

    with SB(
        browser="chrome",
        uc=True,                       # Active anti-detection bypass
        xvfb=True,                     # Creates virtual screen frame for Linux
        user_data_dir=USER_DATA_DIR,
        chromium_arg=COMPATIBILITY_FLAGS
    ) as sb:
        
        try:
            print("🌍 Routing to Facebook Login Portal using advanced connection rules...")
            sb.driver.uc_open_with_reconnect("https://facebook.com", reconnect_time=6)
            time.sleep(5)
            
            # Anti-Detection Property scrubbing via JS context execution
            sb.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # 🛡️ FIX: Universal Multi-Selector Fallback Lists for Desktop Interface Forms
            email_selectors = ["input[name='email']", "#email", "input[type='text']", "input[placeholder*='Email']"]
            password_selectors = ["input[name='pass']", "#pass", "input[type='password']", "input[placeholder*='Password']"]
            
            print("⌨️ Injecting email identity safely...")
            human_type(sb, email_selectors, FB_EMAIL)
            time.sleep(random.uniform(1.0, 2.2))
            
            print("⌨️ Injecting secure password array safely...")
            human_type(sb, password_selectors, FB_PASSWORD)
            time.sleep(random.uniform(1.2, 2.5))
            
            # Submit via standard Enter/Return key tracking bypass instead of zero-velocity clicking
            print("👆 Transmitting native keyboard submit signal...")
            # We map target password wrapper string for the enter tracking hit
            active_pass_field = next(sel for sel in password_selectors if sb.is_element_visible(sel))
            sb.press_keys(active_pass_field, "\n")
            
            print("\n⏳ Monitoring authentication changes (Awaiting Profile Redirect)...")
            print("Open 'facebook_auth.png' in your sidebar to track login progress.")

            logged_in = False
            for attempt in range(60):  # 5 minutes validation window
                time.sleep(5)
                
                cookies = sb.get_cookies()
                has_c_user = any(cookie.get('name') == 'c_user' for cookie in cookies)
                
                if has_c_user:
                    logged_in = True
                    print("\n✅ Facebook Session Token Verified (c_user found) — Login Successful!")
                    if os.path.exists("facebook_auth.png"):
                        os.remove("facebook_auth.png")
                    break
                    
                sb.save_screenshot("facebook_auth.png")
                print(f"[{attempt+1}] State synced to 'facebook_auth.png'. Check for 2FA screens.")

            if not logged_in:
                print("\n⚠️ Profile authentication complete framework exited. Verification missed.")

        except Exception as error_msg:
            print(f"\n❌ Execution Exception triggered: {error_msg}")
        finally:
            print("💾 Cleaning runtime buffers and saving profile state metadata...")

if __name__ == "__main__":
    run_script()
