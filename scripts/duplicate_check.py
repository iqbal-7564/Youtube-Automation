import os
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta

YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")
UPLOAD_LOG_FILE       = Path("upload_log.json")

def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    return r.json().get("access_token")

def load_upload_log():
    if UPLOAD_LOG_FILE.exists():
        try:
            with open(UPLOAD_LOG_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"uploads": []}

def save_upload_log(log):
    with open(UPLOAD_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

def already_uploaded_today(video_type):
    """Check if this video type already uploaded today"""
    log   = load_upload_log()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for upload in log.get("uploads", []):
        if upload.get("date") == today and upload.get("type") == video_type:
            print(f"⚠️ Already uploaded {video_type} today! Skipping.")
            return True
    return False

def log_upload(video_type, title, video_id):
    """Log successful upload"""
    log = load_upload_log()
    log["uploads"].append({
        "date":     datetime.utcnow().strftime("%Y-%m-%d"),
        "time":     datetime.utcnow().strftime("%H:%M"),
        "type":     video_type,
        "title":    title,
        "video_id": video_id,
    })
    # Keep only last 100 uploads
    log["uploads"] = log["uploads"][-100:]
    save_upload_log(log)
    print(f"✅ Upload logged: {title[:50]}")

def get_recent_titles():
    """Get recently uploaded video titles to avoid duplicates"""
    try:
        token = get_access_token()
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "part":       "snippet",
                "forMine":    "true",
                "type":       "video",
                "maxResults": "20",
                "order":      "date",
            },
            timeout=10
        )
        titles = []
        for item in r.json().get("items", []):
            titles.append(item["snippet"]["title"].lower())
        return titles
    except:
        return []

def is_duplicate_title(new_title, recent_titles):
    """Check if title too similar to recent uploads"""
    new_lower = new_title.lower()
    for old_title in recent_titles:
        # Check if 60% words match
        new_words  = set(new_lower.split())
        old_words  = set(old_title.split())
        if not new_words or not old_words:
            continue
        overlap = len(new_words & old_words) / len(new_words)
        if overlap > 0.6:
            print(f"⚠️ Similar title exists: {old_title[:50]}")
            return True
    return False

if __name__ == "__main__":
    print("Recent uploads:")
    for t in get_recent_titles()[:5]:
        print(f"  - {t}")