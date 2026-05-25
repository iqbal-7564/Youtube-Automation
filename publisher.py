import os, requests, base64
from dotenv import load_dotenv

load_dotenv()

def upload_to_imgbb(image_path):
    try:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={
                "key":        os.getenv("IMGBB_API_KEY"),
                "image":      encoded,
                "expiration": 3600
            },
            timeout=20
        )
        data = r.json()
        if data.get("success"):
            print(f"Image uploaded: {data['data']['url'][:50]}")
            return data["data"]["url"]
        return None
    except Exception as e:
        print(f"imgbb error: {e}")
        return None

def post_to_facebook(text, image_path=None):
    FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
    FB_PAGE_ID    = os.getenv("FB_PAGE_ID")

    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("ERROR: Missing FB credentials")
        return None

    print(f"Posting to page: {FB_PAGE_ID}")

    # Try 1 — Photo post via imgbb URL
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
                print(f"Photo post response: {result}")
                if "id" in result:
                    print(f"Posted with image successfully: {result['id']}")
                    return True
                print("Photo post failed — trying file upload...")
            except Exception as e:
                print(f"Photo URL post error: {e}")

    # Try 2 — Photo post via file upload
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
            print(f"File upload response: {result}")
            if "id" in result:
                print(f"Posted with file upload: {result['id']}")
                return True
            print("File upload failed — trying text only...")
        except Exception as e:
            print(f"File upload error: {e}")

    # Try 3 — Text only post
    try:
        print("Posting text only...")
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
            data={
                "message":      text,
                "access_token": FB_PAGE_TOKEN
            },
            timeout=30
        )
        result = r.json()
        print(f"Text post response: {result}")

        if "id" in result:
            print(f"Text post successful: {result['id']}")
            return True

        error = result.get("error", {})
        code  = error.get("code", 0)

        # Only stop pipeline for token errors
        if code in {190, 102, 467, 463, 460}:
            print(f"\n{'!'*50}")
            print("TOKEN EXPIRED — update FB_PAGE_TOKEN immediately!")
            print(f"{'!'*50}\n")
            return None

        print(f"Text post failed: {error.get('message')}")
        return False

    except Exception as e:
        print(f"Text post exception: {e}")
        return False