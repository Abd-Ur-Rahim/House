from seleniumbase import SB
import time
import os
import random

# Removed hardcoded fallback credentials for security
FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")

if not FB_EMAIL or not FB_PASSWORD:
    raise SystemExit(
        "Missing credentials. Set FB_EMAIL and FB_PASSWORD as environment variables."
    )

def human_type(sb, selectors, text):
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
        time.sleep(random.uniform(0.07, 0.22))

def run_script():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = os.path.join(base_dir, "profiles", "facebook_stable_session")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    print("🚀 Initializing Stable Facebook Core (Adaptive Input Mapping)...")

    # FIX: Remove custom chromium_arg. SeleniumBase handles required CI flags natively.
    # We use headless=True here, which is often more stable than xvfb in modern CI for UC mode.
    with SB(
        browser="chrome",
        uc=True,
        headless=True,  
        user_data_dir=USER_DATA_DIR
    ) as sb:
        
        try:
            print("🌍 Routing to Facebook Login Portal...")
            sb.driver.uc_open_with_reconnect("https://facebook.com", reconnect_time=6)
            time.sleep(5)
            
            email_selectors = ["input[name='email']", "#email", "input[type='text']", "input[placeholder*='Email']"]
            password_selectors = ["input[name='pass']", "#pass", "input[type='password']", "input[placeholder*='Password']"]
            
            print("⌨️ Injecting email identity safely...")
            human_type(sb, email_selectors, FB_EMAIL)
            time.sleep(random.uniform(1.0, 2.2))
            
            print("⌨️ Injecting secure password array safely...")
            human_type(sb, password_selectors, FB_PASSWORD)
            time.sleep(random.uniform(1.2, 2.5))
            
            print("👆 Transmitting native keyboard submit signal...")
            active_pass_field = next(sel for sel in password_selectors if sb.is_element_visible(sel))
            sb.press_keys(active_pass_field, "\n")
            
            print("\n⏳ Monitoring authentication changes...")
            
            logged_in = False
            for attempt in range(60):
                time.sleep(5)
                cookies = sb.get_cookies()
                has_c_user = any(cookie.get('name') == 'c_user' for cookie in cookies)
                
                if has_c_user:
                    logged_in = True
                    print("\n✅ Facebook Session Token Verified (c_user found) — Login Successful!")
                    break
                    
                sb.save_screenshot("screenshots/facebook_auth.png")
                print(f"[{attempt+1}] State synced to 'facebook_auth.png'. Check for 2FA screens.")

        except Exception as error_msg:
            timestamp = int(time.time())
            os.makedirs("screenshots", exist_ok=True)
            error_img_path = f"screenshots/failure_initializer_{timestamp}.png"
            sb.driver.save_screenshot(error_img_path)
            print(f"\n❌ Execution Exception triggered: {error_msg}")
        finally:
            print("💾 Cleaning runtime buffers and saving profile state metadata...")

if __name__ == "__main__":
    run_script()