import os
import sys
from seleniumbase import Driver

class SocialBotSuite:
    def __init__(self):
        # 1. Anchor all paths relative to the script location
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 2. Map distinct paths for both Facebook and WhatsApp
        # NOTE: these must match the folder names used by facebook_poster_bot.py,
        # facebook_profile_initializer.py, and whatsapp_profile_initializer.py —
        # otherwise this class logs into a *different* session than the one
        # the actual posting bot reads from.
        self.fb_profile = os.path.join(self.base_dir, "profiles", "facebook_stable_session")
        self.wa_profile = os.path.join(self.base_dir, "profiles", "whatsapp_stable_session")

    def initialize_profile_environment(self, profile_path: str, platform_name: str, target_url: str):
        """
        Validates if a platform profile exists. If missing, forces a 
        visual UI frame for the user to execute manual login authentication.
        """
        if not os.path.exists(profile_path):
            os.makedirs(profile_path)
            print(f"\n{'='*70}")
            print(f"🚨 INITIAL SETUP DETECTED FOR: {platform_name.upper()}")
            print(f"Creating storage folder tree at: {profile_path}")
            print(f"Action Required: Please log in to your {platform_name} account now.")
            print(f"{'='*70}\n")
            
            # Spin up a temporary VISIBLE browser window to authenticate
            driver = Driver(
                browser='Chrome', 
                uc=True, 
                headless2=False, # Must be visible to enter passwords / scan QR codes
                user_data_dir=profile_path
            )
            driver.get(target_url)
            
            # Pause execution to allow manual login actions
            input(f"--> Log in/Scan QR code on screen. Once fully logged in, press ENTER here...")
            driver.quit()
            print(f"✅ {platform_name} session state successfully locked down locally!\n")

    def setup_all(self):
        """Ensures all profile paths are configured before bot execution."""
        self.initialize_profile_environment(
            profile_path=self.fb_profile, 
            platform_name="Facebook", 
            target_url="https://facebook.com"
        )
        self.initialize_profile_environment(
            profile_path=self.wa_profile, 
            platform_name="WhatsApp Web", 
            target_url="https://whatsapp.com"
        )

    def run_whatsapp_task(self, phone_number: str, message: str):
        """Runs the actual WhatsApp bot task in stealthy headless mode."""
        print("Launching Headless WhatsApp Worker...")
        driver = Driver(browser='Chrome', uc=True, headless2=True, user_data_dir=self.wa_profile)
        try:
            # Re-use your existing API URL logic here
            import urllib.parse
            clean_phone = "".join(filter(str.isdigit, str(phone_number)))
            encoded_msg = urllib.parse.quote(message)
            
            driver.get(f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}")
            driver.wait_for_element_visible('//span[contains(@data-testid, "send")]', timeout=45)
            driver.click('//span[contains(@data-testid, "send")]')
            driver.wait_for_element_absent('(//div[contains(@aria-label, "progress")])[last()]', timeout=10)
            print("WhatsApp automation task finished.")
        finally:
            driver.quit()

    def run_facebook_task(self):
        """Runs your Facebook poster bot logic using its respective isolated profile."""
        print("Launching Headless Facebook Worker...")
        driver = Driver(browser='Chrome', uc=True, headless2=True, user_data_dir=self.fb_profile)
        try:
            driver.get("https://facebook.com")
            # Insert your custom facebook posting commands/XPaths here
            print("Facebook automation task finished.")
        finally:
            driver.quit()

# =====================================================================
# Main Harness
# =====================================================================
if __name__ == "__main__":
    suite = SocialBotSuite()
    
    # Run the setup first. If profiles exist, this completes instantly.
    # If a new user pulls this from GitHub, it will prompt them to log in sequentially.
    suite.setup_all()
