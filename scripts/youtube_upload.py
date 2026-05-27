import os
import json
import requests
from pathlib import Path

OUTPUT_DIR            = Path("output")
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")


def get_access_token():
    print("🔑 Getting YouTube token...")
    for attempt in range(3):
        try:
            r = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id":     YOUTUBE_CLIENT_ID,
                    "client_secret": YOUTUBE_CLIENT_SECRET,
                    "refresh_token": YOUTUBE_REFRESH_TOKEN,
                    "grant_type":    "refresh_token",
                },
                timeout=15
            )
            data = r.json()
            if "access_token" in data:
                print("✅ Token obtained!")
                return data["access_token"]
            raise Exception(f"Token error: {data.get('error_description', data)}")
        except Exception as e:
            print(f"Token attempt {attempt + 1}: {e}")
            if attempt == 2:
                raise


def validate_video(video_path):
    """Check video is valid before uploading."""
    import subprocess
    path = str(video_path)
    if not os.path.exists(path):
        raise Exception(f"Video not found: {path}")
    size = os.path.getsize(path)
    if size < 100_000:
        raise Exception(f"Video too small ({size} bytes) - likely corrupted!")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    try:
        duration = float(result.stdout.strip())
        if duration < 10:
            raise Exception(f"Video too short ({duration}s) - likely corrupted!")
        print(f"✅ Video valid: {size // 1024 // 1024}MB, {duration:.0f}s")
    except ValueError:
        raise Exception("Could not read video duration - corrupted!")


def upload_thumbnail(video_id, thumb_path, token):
    if not os.path.exists(str(thumb_path)):
        print("⚠️ Thumbnail file not found, skipping.")
        return
    print("🖼️  Uploading thumbnail...")
    with open(str(thumb_path), "rb") as f:
        r = requests.post(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("thumbnail.jpg", f, "image/jpeg")},
            timeout=60
        )
    if r.status_code == 200:
        print("✅ Thumbnail uploaded!")
    else:
        print(f"⚠️ Thumbnail failed: {r.status_code} {r.text[:200]}")


def create_playlist(token, title, description):
    """Create a playlist and return its ID, or None on failure."""
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {"title": title[:100], "description": description},
                "status":  {"privacyStatus": "public"},
            },
            timeout=15
        )
        if r.status_code in (200, 201):
            pid = r.json()["id"]
            print(f"✅ Playlist created: {pid}")
            return pid
    except Exception as e:
        print(f"Playlist error: {e}")
    return None


def add_to_playlist(token, video_id, playlist_id):
    try:
        requests.post(
            "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id}
                }
            },
            timeout=15
        )
        print("✅ Added to playlist!")
    except Exception as e:
        print(f"Add to playlist error: {e}")


def add_pinned_comment(token, video_id):
    """Post and pin an engagement comment."""
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": (
                                "💬 Which fact shocked you the most? Comment below! 👇\n"
                                "🔔 Subscribe for daily mind-blowing facts!"
                            )
                        }
                    }
                }
            },
            timeout=15
        )
        if r.status_code in (200, 201):
            comment_id = r.json()["id"]
            requests.post(
                "https://www.googleapis.com/youtube/v3/comments?part=snippet",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
                json={"id": comment_id, "snippet": {"moderationStatus": "published"}},
                timeout=15
            )
            print("✅ Pinned comment added!")
    except Exception as e:
        print(f"Comment error: {e}")


def upload_video(video_path, metadata, token, is_short=False):
    """Upload video via resumable upload with 3 retries. Returns (video_id, final_title)."""
    video_path = str(video_path)
    video_size = os.path.getsize(video_path)
    print(f"📤 Uploading ({video_size // 1024 // 1024}MB)...")

    title = metadata["title"]
    if is_short and "#Shorts" not in title:
        title = (title[:88] + " #Shorts") if len(title) > 88 else title + " #Shorts"

    # 22 = People & Blogs, 24 = Entertainment, 28 = Science & Technology
    category = "24" if is_short else "28"

    for attempt in range(3):
        try:
            # ── Step 1: Initialize resumable upload session ──
            r = requests.post(
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status",
                headers={
                    "Authorization":           f"Bearer {token}",
                    "Content-Type":            "application/json",
                    "X-Upload-Content-Type":   "video/mp4",
                    "X-Upload-Content-Length": str(video_size),
                },
                json={
                    "snippet": {
                        "title":       title[:100],
                        "description": metadata["description"][:4900],
                        "tags":        metadata["tags"][:30],
                        "categoryId":  category,
                    },
                    "status": {
                        "privacyStatus":           "public",
                        "selfDeclaredMadeForKids": False,
                    },
                },
                timeout=30
            )

            if r.status_code != 200:
                raise Exception(f"Init failed: {r.status_code} {r.text[:200]}")

            upload_url = r.headers["Location"]

            # ── Step 2: Stream the file to the resumable URL ──
            with open(video_path, "rb") as f:
                up = requests.put(
                    upload_url,
                    headers={
                        "Content-Type":   "video/mp4",
                        "Content-Length": str(video_size),
                    },
                    data=f,
                    timeout=600
                )

            if up.status_code in (200, 201):
                video_id = up.json()["id"]
                suffix   = " #Shorts" if is_short else ""
                print(f"✅ Uploaded! https://youtube.com/watch?v={video_id}{suffix}")
                return video_id, title
            else:
                raise Exception(f"Upload failed: {up.status_code} {up.text[:200]}")

        except Exception as e:
            print(f"Upload attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                raise


def main():
    token = get_access_token()

    # ── FIX: `or` handles both None AND empty string from GitHub Actions ──
    video_type = os.environ.get("VIDEO_TYPE") or "video1"
    print(f"📌 VIDEO_TYPE resolved to: '{video_type}'")

    # ── Load duplicate checker if available ──
    try:
        from duplicate_check import (
            already_uploaded_today,
            log_upload,
            get_recent_titles,
            is_duplicate_title
        )
        recent_titles = get_recent_titles()
        check_dupes   = True
    except ImportError:
        print("⚠️ duplicate_check module not found — skipping dupe checks.")
        check_dupes   = False
        recent_titles = []

    # ── Guard: skip if this type was already uploaded today ──
    if check_dupes and already_uploaded_today(video_type):
        print(f"⚠️ Already uploaded '{video_type}' today! Stopping.")
        return

    # ════════════════════════════════════════════
    # SHORT upload path
    # ════════════════════════════════════════════
    short_meta_path  = OUTPUT_DIR / "metadata_short.json"
    short_video_path = OUTPUT_DIR / "short_final.mp4"

    if video_type == "short":
        if not short_meta_path.exists() or not short_video_path.exists():
            print("❌ Short metadata or video file missing. Aborting.")
            return

        print("\n📱 Uploading Short...")
        with open(short_meta_path) as f:
            meta = json.load(f)

        validate_video(short_video_path)

        if check_dupes and is_duplicate_title(meta["title"], recent_titles):
            print("⚠️ Duplicate short title! Skipping.")
            return

        vid_id, final_title = upload_video(short_video_path, meta, token, is_short=True)
        upload_thumbnail(vid_id, OUTPUT_DIR / "thumbnail.jpg", token)
        add_pinned_comment(token, vid_id)

        pl = create_playlist(token, "MindBlownFacts Shorts", "Daily shocking facts in 60 seconds!")
        if pl:
            add_to_playlist(token, vid_id, pl)

        if check_dupes:
            log_upload("short", final_title, vid_id)

    # ════════════════════════════════════════════
    # LONG VIDEO upload path (video1 / video2)
    # ════════════════════════════════════════════
    elif video_type in ("video1", "video2"):
        # Map video_type to the actual file number
        vnum      = 1 if video_type == "video1" else 2
        vpath     = OUTPUT_DIR / f"final_video_{vnum}.mp4"
        meta_path = OUTPUT_DIR / "metadata.json"

        if not meta_path.exists():
            print("❌ metadata.json missing. Aborting.")
            return

        if not vpath.exists():
            print(f"❌ Video file not found: {vpath}. Aborting.")
            return

        print(f"\n🎬 Uploading Video {vnum} ({video_type})...")
        with open(meta_path) as f:
            meta = json.load(f)

        validate_video(vpath)

        if check_dupes and is_duplicate_title(meta["title"], recent_titles):
            print("⚠️ Duplicate title! Skipping.")
            return

        vid_id, final_title = upload_video(vpath, meta, token)
        upload_thumbnail(vid_id, OUTPUT_DIR / "thumbnail.jpg", token)
        add_pinned_comment(token, vid_id)

        topic    = meta.get("topic", "Facts")
        pl_title = f"{topic} Facts - MindBlownFacts"
        pl = create_playlist(token, pl_title, f"All videos about {topic}")
        if pl:
            add_to_playlist(token, vid_id, pl)

        if check_dupes:
            log_upload(video_type, final_title, vid_id)

    else:
        print(f"❌ Unknown VIDEO_TYPE: '{video_type}'. Expected: short, video1, video2.")
        return

    print("\n🎉 YouTube upload complete!")


if __name__ == "__main__":
    main()