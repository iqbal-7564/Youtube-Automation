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
                    headers={"User-Agent": "Mozilla/5.0", "Connection": "keep-alive"},
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

# ─── FACEBOOK (ACTIVE) ────────────────────────────────────

def post_to_facebook(text, image_path=None):
    FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
    FB_PAGE_ID    = os.getenv("FB_PAGE_ID")

    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("ERROR: Missing FB credentials")
        return None

    print(f"Posting to Facebook: {FB_PAGE_ID}")

    try:
        # Method 1 — Photo via imgbb URL
        if image_path and os.path.exists(image_path):
            img_url = upload_to_imgbb(image_path)
            if img_url:
                try:
                    r      = requests.post(
                        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
                        data={"caption": text, "url": img_url, "access_token": FB_PAGE_TOKEN},
                        timeout=30
                    )
                    result = r.json()
                    print(f"  FB photo URL: {result}")
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
                        data={"caption": text, "access_token": FB_PAGE_TOKEN},
                        files={"source": img},
                        timeout=30
                    )
                result = r.json()
                print(f"  FB file upload: {result}")
                if "id" in result:
                    print(f"  Facebook posted via file: {result['id']}")
                    return True
            except Exception as e:
                print(f"  FB file error: {e}")

        # Method 3 — Text only
        print("  Posting text only...")
        r      = requests.post(
            f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
            data={"message": text, "access_token": FB_PAGE_TOKEN},
            timeout=30
        )
        result = r.json()
        print(f"  FB text: {result}")

        if "id" in result:
            print(f"  Facebook text posted: {result['id']}")
            return True

        error = result.get("error", {})
        code  = error.get("code", 0)
        if code in {190, 102, 200, 467, 463, 460}:
            print(f"FATAL Facebook error (code {code}) — update FB_PAGE_TOKEN")
            return None

        print(f"  Facebook failed: {error.get('message')}")
        return False

    except Exception as e:
        print(f"  Facebook exception: {e}")
        return False

# ─── INSTAGRAM (UNCOMMENT WHEN READY) ────────────────────

# def post_to_instagram(text, image_path=None):
#     FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
#     IG_USER_ID    = os.getenv("IG_USER_ID")
#     if not FB_PAGE_TOKEN or not IG_USER_ID:
#         print("ERROR: Missing Instagram credentials")
#         return False
#     print(f"Posting to Instagram: {IG_USER_ID}")
#     try:
#         img_url = None
#         if image_path and os.path.exists(image_path):
#             img_url = upload_to_imgbb(image_path)
#         if not img_url:
#             print("  No image for Instagram — skipping")
#             return False
#         r = requests.post(
#             f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
#             data={"image_url": img_url, "caption": text, "access_token": FB_PAGE_TOKEN},
#             timeout=30
#         )
#         container = r.json()
#         if "id" not in container:
#             print(f"  Instagram container failed: {container}")
#             return False
#         r2     = requests.post(
#             f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
#             data={"creation_id": container["id"], "access_token": FB_PAGE_TOKEN},
#             timeout=30
#         )
#         result = r2.json()
#         if "id" in result:
#             print(f"  Instagram posted: {result['id']}")
#             return True
#         print(f"  Instagram failed: {result}")
#         return False
#     except Exception as e:
#         print(f"  Instagram exception: {e}")
#         return False

# ─── TWITTER (UNCOMMENT WHEN READY) ──────────────────────

# def post_to_twitter(text, image_path=None):
#     import tweepy
#     API_KEY             = os.getenv("TWITTER_API_KEY")
#     API_SECRET          = os.getenv("TWITTER_API_SECRET")
#     ACCESS_TOKEN        = os.getenv("TWITTER_ACCESS_TOKEN")
#     ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
#     if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
#         print("  Twitter credentials missing")
#         return False
#     try:
#         client     = tweepy.Client(
#             consumer_key=API_KEY, consumer_secret=API_SECRET,
#             access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET
#         )
#         tweet_text = text[:277] + "..." if len(text) > 280 else text
#         if image_path and os.path.exists(image_path):
#             auth  = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
#             api   = tweepy.API(auth)
#             media = api.media_upload(filename=image_path)
#             r     = client.create_tweet(text=tweet_text, media_ids=[media.media_id])
#         else:
#             r = client.create_tweet(text=tweet_text)
#         print(f"  Twitter posted: {r.data['id']}")
#         return True
#     except Exception as e:
#         print(f"  Twitter error: {e}")
#         return False

# ─── TELEGRAM (UNCOMMENT WHEN READY) ─────────────────────

# def post_to_telegram(text, image_path=None):
#     BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
#     CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
#     if not BOT_TOKEN or not CHANNEL_ID:
#         print("  Telegram credentials missing")
#         return False
#     try:
#         if image_path and os.path.exists(image_path):
#             with open(image_path, "rb") as img:
#                 r = requests.post(
#                     f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
#                     data={"chat_id": CHANNEL_ID, "caption": text[:1024]},
#                     files={"photo": img},
#                     timeout=30
#                 )
#         else:
#             r = requests.post(
#                 f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
#                 data={"chat_id": CHANNEL_ID, "text": text[:4096]},
#                 timeout=30
#             )
#         result = r.json()
#         if result.get("ok"):
#             print("  Telegram posted successfully")
#             return True
#         print(f"  Telegram failed: {result}")
#         return False
#     except Exception as e:
#         print(f"  Telegram error: {e}")
#         return False