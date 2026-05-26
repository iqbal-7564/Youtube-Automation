import os
import requests
import json
from datetime import datetime
from notify import send_telegram

FB_PAGE_TOKEN         = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID            = os.environ.get("FB_PAGE_ID")
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

def check_facebook_token():
    """Check Facebook token validity and expiry"""
    print("🔍 Checking Facebook token...")
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/debug_token",
            params={
                "input_token":  FB_PAGE_TOKEN,
                "access_token": FB_PAGE_TOKEN,
            },
            timeout=10
        )
        data = r.json().get("data", {})
        if not data.get("is_valid"):
            send_telegram("❌ <b>Facebook token INVALID!</b>\nPlease refresh immediately!")
            return False

        expires = data.get("expires_at", 0)
        if expires:
            days_left = (expires - datetime.utcnow().timestamp()) / 86400
            if days_left < 10:
                send_telegram(f"⚠️ Facebook token expires in {int(days_left)} days! Refresh soon!")
            else:
                print(f"✅ Facebook token valid ({int(days_left)} days left)")
        else:
            print("✅ Facebook token valid (never expires)")
        return True
    except Exception as e:
        print(f"Facebook check failed: {e}")
        return False

def check_youtube_token():
    """Check YouTube refresh token validity"""
    print("🔍 Checking YouTube token...")
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":     YOUTUBE_CLIENT_ID,
                "client_secret": YOUTUBE_CLIENT_SECRET,
                "refresh_token": YOUTUBE_REFRESH_TOKEN,
                "grant_type":    "refresh_token",
            },
            timeout=10
        )
        data = r.json()
        if "access_token" in data:
            print("✅ YouTube token valid!")
            return True
        else:
            error = data.get("error_description", "Unknown error")
            send_telegram(f"❌ <b>YouTube token INVALID!</b>\n{error}\nRun get_token.py immediately!")
            return False
    except Exception as e:
        print(f"YouTube check failed: {e}")
        return False

def check_quota():
    """Estimate GitHub Actions minutes used"""
    print("🔍 Checking estimated usage...")
    now  = datetime.utcnow()
    days = now.day
    # 2 videos/day × 20 min each = 40 min/day
    estimated = days * 40
    print(f"📊 Estimated minutes used: ~{estimated}/2000")
    if estimated > 1500:
        send_telegram(f"⚠️ <b>GitHub Actions Warning!</b>\nEstimated {estimated}/2000 minutes used this month!\nConsider optimizing.")

def main():
    print("\n🔍 TOKEN & QUOTA CHECK\n" + "="*40)
    fb_ok = check_facebook_token()
    yt_ok = check_youtube_token()
    check_quota()

    if fb_ok and yt_ok:
        print("\n✅ All tokens valid!")
    else:
        print("\n⚠️ Some tokens need attention!")

if __name__ == "__main__":
    main()