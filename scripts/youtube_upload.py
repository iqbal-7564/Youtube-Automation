import os
import json
import requests
from pathlib import Path
from datetime import datetime

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
            print(f"Token attempt {attempt+1}: {e}")
            if attempt == 2:
                raise

def validate_video(video_path):
    """Check video is valid before uploading"""
    import subprocess
    path = str(video_path)
    if not os.path.exists(path):
        raise Exception(f"Video not found: {path}")
    size = os.path.getsize(path)
    if size < 100000:
        raise Exception(f"Video too small ({size} bytes) - likely corrupted!")
    # Check duration
    result = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1",path],
        capture_output=True, text=True
    )
    try:
        duration = float(result.stdout.strip())
        if duration < 10:
            raise Exception(f"Video too short ({duration}s) - likely corrupted!")
        print(f"✅ Video valid: {size//1024//1024}MB, {duration:.0f}s")
    except ValueError:
        raise Exception("Could not read video duration - corrupted!")

def upload_thumbnail(video_id, thumb_path, token):
    if not os.path.exists(str(thumb_path)):
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
        print(f"⚠️ Thumbnail failed: {r.status_code}")

def create_playlist(token, title, description):
    """Create playlist for this topic"""
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
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
        print(f"Playlist: {e}")
    return None

def add_to_playlist(token, video_id, playlist_id):
    try:
        requests.post(
            "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id}
                }
            },
            timeout=15
        )
        print(f"✅ Added to playlist!")
    except Exception as e:
        print(f"Add to playlist: {e}")

def add_pinned_comment(token, video_id):
    """Add pinned comment for engagement"""
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": "💬 Which fact shocked you the most? Comment below! 👇\n🔔 Subscribe for daily mind-blowing facts!"
                        }
                    }
                }
            },
            timeout=15
        )
        if r.status_code in (200, 201):
            comment_id = r.json()["id"]
            # Pin the comment
            requests.post(
                "https://www.googleapis.com/youtube/v3/comments?part=snippet",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"id": comment_id, "snippet": {"moderationStatus": "published"}},
                timeout=15
            )
            print("✅ Pinned comment added!")
    except Exception as e:
        print(f"Comment: {e}")

def upload_video(video_path, metadata, token, is_short=False):
    """Upload video with retry logic"""
    video_path = str(video_path)
    video_size = os.path.getsize(video_path)
    print(f"📤 Uploading ({video_size//1024//1024}MB)...")

    title    = metadata["title"]
    if is_short and "#Shorts" not in title:
        title = (title[:88] + " #Shorts") if len(title) > 88 else title + " #Shorts"

    category = "24" if is_short else "28"

    for attempt in range(3):
        try:
            # Initialize resumable upload
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

            # Upload file
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
            print(f"Upload attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise

def main():
    token = get_access_token()

    # Import duplicate checker
    try:
        from duplicate_check import (
            already_uploaded_today,
            log_upload,
            get_recent_titles,
            is_duplicate_title
        )
        recent_titles = get_recent_titles()
        check_dupes   = True
    except:
        check_dupes   = False
        recent_titles = []

    video_type = os.environ.get("VIDEO_TYPE", "video1")

    # Check duplicate
    if check_dupes and already_uploaded_today(video_type):
        print(f"⚠️ Already uploaded {video_type} today! Stopping.")
        return

    # Upload Short
    short_meta = OUTPUT_DIR / "metadata_short.json"
    short_path = OUTPUT_DIR / "short_final.mp4"
    if short_meta.exists() and short_path.exists():
        print("\n📱 Uploading Short...")
        with open(short_meta) as f:
            meta = json.load(f)

        validate_video(short_path)

        if check_dupes and is_duplicate_title(meta["title"], recent_titles):
            print("⚠️ Duplicate short title! Skipping.")
        else:
            vid_id, final_title = upload_video(str(short_path), meta, token, is_short=True)
            upload_thumbnail(vid_id, str(OUTPUT_DIR/"thumbnail.jpg"), token)
            add_pinned_comment(token, vid_id)

            pl = create_playlist(token, "MindBlownFacts Shorts",
                                "Daily shocking facts in 60 seconds!")
            if pl:
                add_to_playlist(token, vid_id, pl)

            if check_dupes:
                log_upload("short", final_title, vid_id)

    # Upload Long Video
    video_meta = OUTPUT_DIR / "metadata.json"
    if video_meta.exists():
        with open(video_meta) as f:
            meta = json.load(f)

        for vnum in [1, 2]:
            vpath = OUTPUT_DIR / f"final_video_{vnum}.mp4"
            if vpath.exists():
                print(f"\n🎬 Uploading Video {vnum}...")

                validate_video(vpath)

                if check_dupes and is_duplicate_title(meta["title"], recent_titles):
                    print("⚠️ Duplicate title! Skipping.")
                    break

                vid_id, final_title = upload_video(str(vpath), meta, token)
                upload_thumbnail(vid_id, str(OUTPUT_DIR/"thumbnail.jpg"), token)
                add_pinned_comment(token, vid_id)

                topic    = meta.get("topic", "Facts")
                pl_title = f"{topic} Facts - MindBlownFacts"
                pl = create_playlist(token, pl_title, f"All videos about {topic}")
                if pl:
                    add_to_playlist(token, vid_id, pl)

                if check_dupes:
                    log_upload(f"video{vnum}", final_title, vid_id)
                break

    print("\n🎉 YouTube upload complete!")

if __name__ == "__main__":
    main()