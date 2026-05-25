import requests, os
from dotenv import load_dotenv
load_dotenv()

# Step 1 — Paste fresh token from Graph API Explorer here
FRESH_USER_TOKEN = "EAAdKjQ5ftosBRtbqGJvxPsSI2PlVsH3ANWVCaQg4tqzl1Wl79FpxIA9wK1OOF8trX8CynoiB1mx4gE6ZAAEOgAnPcmr39IwJHEzj46xj8UiThhX0hgEZBxu3jcLcWI6USxfZCtg4soeiBA6YUGcdFlEbuvJwTih0t6D9QUrLdcfhsGK1e4J4LixbuKuKSmGXb4fCfkeoBFpW4bqQ0ew0cbasoG5dH7H6ZBv6hKu1caaeoufTASZCgmCjuUzZAxDFIGaTZA5aenFf56BYj8mmwqeVbXzXwZDZD"

APP_ID     = os.getenv("FB_APP_ID")
APP_SECRET = os.getenv("FB_APP_SECRET")
PAGE_ID    = os.getenv("FB_PAGE_ID")

print("="*50)
print("Step 1 — Extending to long-lived token...")
r = requests.get(
    "https://graph.facebook.com/oauth/access_token",
    params={
        "grant_type":        "fb_exchange_token",
        "client_id":         APP_ID,
        "client_secret":     APP_SECRET,
        "fb_exchange_token": FRESH_USER_TOKEN
    }
)
data = r.json()
print(f"Response: {data}")
long_token = data.get("access_token")
if not long_token:
    print("Failed to get long-lived token")
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
result = r2.json()
print(f"Response: {result}")
permanent = result.get("access_token")
if not permanent:
    print("Failed to get permanent token")
    exit()

print("\nStep 3 — Verifying token...")
r3 = requests.get(
    "https://graph.facebook.com/debug_token",
    params={
        "input_token":  permanent,
        "access_token": permanent
    }
)
info = r3.json().get("data", {})
print(f"Type:       {info.get('type')}")
print(f"Expires at: {info.get('expires_at')} (0 = never expires)")
print(f"Valid:      {info.get('is_valid')}")

print("\nStep 4 — Testing post...")
r4 = requests.post(
    f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
    data={
        "message":      "token test delete",
        "access_token": permanent
    }
)
test = r4.json()
print(f"Test: {test}")

if "id" in test:
    print(f"\n{'='*50}")
    print("SUCCESS — Copy this to your .env:")
    print(f"\nFB_PAGE_TOKEN={permanent}")
    print(f"{'='*50}")
else:
    print("Token test failed")