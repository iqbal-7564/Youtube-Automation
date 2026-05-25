import os, requests, base64, time
from dotenv import load_dotenv

load_dotenv()

def upload_to_imgbb(image_path, retries=3):
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()

        for attempt in range(retries):
            try:
                print(f"  imgbb upload attempt {attempt+1}...")
                r = requests.post(
                    "https://api.imgbb.com/1/upload",
                    data={
                        "key":        os.getenv("IMGBB_API_KEY"),
                        "image":      encoded,
                        "expiration": 3600
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Connection": "keep-alive"
                    },
                    timeout=30
                )
                data = r.json()
                if data.get("success"):
                    print(f"  imgbb uploaded: {data['data']['url'][:50]}")
                    return data["data"]["url"]
                print(f"  imgbb failed: {data}")
            except Exception as e:
                print(f"  imgbb attempt {attempt+1} error: {e}")
                time.sleep(3)

        return None
    except Exception as e:
        print(f"  imgbb read error: {e}")
        return None

def post_to_facebook(text, image_path=None):
    FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
    FB_PAGE_ID    = os.getenv("FB_PAGE_ID")

    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("ERROR: Missing FB credentials")
        return None

    print(f"Posting to Facebook page: {FB_PAGE_ID}")

    try:
        # Method 1 — Photo via imgbb URL
        if image_path and os.path.exists(image_path):
            img_url = upload_to_imgbb(image_path)
            if img_url:
                try:
                    r = requests.post(
                        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
                        data={
                            "caption":      text,
                            "url":          img_url,
                            "access_token": FB_PAGE_TOKEN
                        },
                        timeout=30
                    )
                    result = r.json()
                    print(f"  FB photo URL response: {result}")
                    if "id" in result:
                        print(f"  Facebook posted with image: {result['id']}")
                        return True
                except Exception as e:
                    print(f"  FB photo URL error: {e}")

        # Method 2 — Direct file upload
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as img:
                    r = requests.post(
                        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
                        data={
                            "caption":      text,
                            "access_token": FB_PAGE_TOKEN
                        },
                        files={"source": img},
                        timeout=30
                    )
                result = r.json()
                print(f"  FB file upload response: {result}")
                if "id" in result:
                    print(f"  Facebook posted via file: {result['id']}")
                    return True
            except Exception as e:
                print(f"  FB file upload error: {e}")

        # Method 3 — Text only
        print("  Posting text only...")
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
            data={
                "message":      text,
                "access_token": FB_PAGE_TOKEN
            },
            timeout=30
        )
        result = r.json()
        print(f"  FB text response: {result}")

        if "id" in result:
            print(f"  Facebook text posted: {result['id']}")
            return True

        error = result.get("error", {})
        code  = error.get("code", 0)
        if code in {190, 102, 467, 463, 460}:
            print("TOKEN EXPIRED — update FB_PAGE_TOKEN!")
            return None

        print(f"  Facebook failed: {error.get('message')}")
        return False

    except Exception as e:
        print(f"  Facebook exception: {e}")
        return False

def post_to_instagram(text, image_path=None):
    FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
    IG_USER_ID    = os.getenv("IG_USER_ID")

    if not FB_PAGE_TOKEN or not IG_USER_ID:
        print("ERROR: Missing Instagram credentials")
        return False

    print(f"Posting to Instagram: {IG_USER_ID}")

    try:
        img_url = None
        if image_path and os.path.exists(image_path):
            img_url = upload_to_imgbb(image_path)

        if not img_url:
            print("  No image for Instagram — skipping")
            return False

        # Step 1 — Create container
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
            data={
                "image_url":    img_url,
                "caption":      text,
                "access_token": FB_PAGE_TOKEN
            },
            timeout=30
        )
        container = r.json()
        print(f"  IG container: {container}")

        if "id" not in container:
            print(f"  Instagram container failed: {container}")
            return False

        # Step 2 — Publish
        r2 = requests.post(
            f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
            data={
                "creation_id":  container["id"],
                "access_token": FB_PAGE_TOKEN
            },
            timeout=30
        )
        result = r2.json()
        print(f"  IG publish: {result}")

        if "id" in result:
            print(f"  Instagram posted: {result['id']}")
            return True

        print(f"  Instagram failed: {result}")
        return False

    except Exception as e:
        print(f"  Instagram exception: {e}")
        return False