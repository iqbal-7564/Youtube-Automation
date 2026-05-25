import os, requests

token   = os.environ.get("FB_PAGE_TOKEN", "MISSING")
page_id = os.environ.get("FB_PAGE_ID", "MISSING")

print("Token starts: " + token[:15] + "...")
print("Page ID: " + page_id)

r = requests.post(
    "https://graph.facebook.com/v19.0/" + page_id + "/feed",
    data={"message": "debug test delete", "access_token": token}
)
print("Response: " + str(r.json()))