from seleniumbase import SB
import time
import os

def run_script():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = os.path.join(base_dir, "profiles", "whatsapp_stable_session")
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    print("🚀 Initializing Stable WhatsApp Core (Bypassing Renderer Crashes)...")

    # Critical Flags: --disable-gpu and --disable-software-rasterizer fix the blank page issue
    COMPATIBILITY_FLAGS = (
        "--disable-gpu "
        "--disable-software-rasterizer "
        "--window-size=1280,1024 "
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
            print("🌍 Routing to WhatsApp Web...")
            sb.open("https://web.whatsapp.com/")
            
            # Allow time for the heavy framework scripts to settle without acceleration
            print("⏳ Awaiting initialization context (15 seconds)...")
            time.sleep(15)
            
            print("\n📸 QR CODE STREAM CHANNELS SECURED")
            print("Look at your VS Code sidebar, open 'whatsapp_qr.png' and scan it!")

            logged_in = False
            for attempt in range(60):  # 5 minutes validation duration
                time.sleep(5)
                
                # Check for the primary post-login interface element
                main_pane = sb.find_elements('//div[@id="side"]')
                if main_pane:
                    logged_in = True
                    print("\n✅ Target Layout Detected — Login Successful!")
                    if os.path.exists("whatsapp_qr.png"):
                        os.remove("whatsapp_qr.png")
                    break
                    
                # Save visual canvas directly to workspace file tree
                sb.save_screenshot("whatsapp_qr.png")
                print(f"[{attempt+1}] Captured rendering instance state inside 'whatsapp_qr.png'...")

            if not logged_in:
                print("\n⚠️ Authentication window completed without verification registration.")

        except Exception as error_msg:
            print(f"\n❌ Execution Exception triggered: {error_msg}")
        finally:
            print("💾 Cleaning runtime buffers and saving profile state metadata...")

# Multi-process execution guard is strictly required by UC drivers on Linux systems
if __name__ == "__main__":
    run_script()
