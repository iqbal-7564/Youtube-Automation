import requests, os
from dotenv import load_dotenv
load_dotenv()

# Paste fresh token from Graph API Explorer here
FRESH_USER_TOKEN = "EAAdKjQ5ftosBRg7hyMxCyv4jKZAEuqkb0UvutMBNjFhJPMg0vKByIo69YJ52NIsSVvt0G9SPkRH9Bdz30pXKTXECMEgXtefFQKnTo3GNBZABxN2zYY4mTBLA8mbhQeLu3F5Qr3WvdYX1GZCQURKLW1oH6lV0DhDNV3kd4xaoZBiDYZCZBzaWZBPbDsvXXPwFYooG0OlZBpq1"

APP_ID     = os.getenv("FB_APP_ID")
APP_SECRET = os.getenv("FB_APP_SECRET")
PAGE_ID    = os.getenv("FB_PAGE_ID")

print("="*50)
print("Step 1 — Getting long-lived token...")
r = requests.get(
    "https://graph.facebook.com/oauth/access_token",
    params={
        "grant_type":        "fb_exchange_token",
        "client_id":         APP_ID,
        "client_secret":     APP_SECRET,
        "fb_exchange_token": FRESH_USER_TOKEN
    }
)
long_token = r.json().get("access_token")
if not long_token:
    print(f"Failed: {r.json()}")
    exit()
print(f"Long-lived token: {long_token[:25]}...")

print("\nStep 2 — Getting permanent page token...")
r2 = requests.get(
    f"https://graph.facebook.com/v19.0/{PAGE_ID}",
    params={
        "fields":       "access_token,name",
        "access_token": long_token
    }
)
page_token = r2.json().get("access_token")
if not page_token:
    print(f"Failed: {r2.json()}")
    exit()

print("\nStep 3 — Verifying...")
r3 = requests.get(
    "https://graph.facebook.com/debug_token",
    params={
        "input_token":  page_token,
        "access_token": page_token
    }
)
info = r3.json().get("data", {})
print(f"Type:       {info.get('type')}")
print(f"Expires at: {info.get('expires_at')} (0 = never)")
print(f"Valid:      {info.get('is_valid')}")
print(f"Scopes:     {info.get('scopes')}")

print("\nStep 4 — Testing...")
r4 = requests.post(
    f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
    data={"message": "token test delete", "access_token": page_token}
)
result = r4.json()
print(f"Test: {result}")

if "id" in result:
    print(f"\n{'='*50}")
    print("SUCCESS — Copy to .env AND GitHub Secret:")
    print(f"\nFB_PAGE_TOKEN={page_token}")
    print(f"{'='*50}")
else:
    print("Token test failed")