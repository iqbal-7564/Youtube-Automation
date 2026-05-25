import os
import json
import requests
from pathlib import Path

OUTPUT_DIR            = Path("output")
YOUTUBE_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

def get_access_token():
    print("🔑 Getting YouTube token...")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    data = r.json()
    if "access_token" not in data:
        raise Exception(f"Token error: {data}")
    return data["access_token"]

def upload_thumbnail(video_id, thumb_path, token):
    print("🖼️  Uploading thumbnail...")
    with open(thumb_path, "rb") as f:
        r = requests.post(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("thumbnail.jpg", f, "image/jpeg")},
        )
    print("✅ Thumbnail done!" if r.status_code == 200 else f"⚠️ Thumbnail: {r.text[:100]}")

def create_playlist(token, title, description):
    """Create or get playlist"""
    print(f"📋 Creating playlist: {title}")
    r = requests.post(
        "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={
            "snippet": {"title": title, "description": description},
            "status":  {"privacyStatus": "public"},
        }
    )
    if r.status_code in (200, 201):
        return r.json()["id"]
    return None

def add_to_playlist(token, video_id, playlist_id):
    """Add video to playlist"""
    requests.post(
        "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id}
            }
        }
    )
    print(f"✅ Added to playlist!")

def upload_video(video_path, metadata, token, is_short=False):
    """Upload video to YouTube"""
    video_size = os.path.getsize(video_path)
    print(f"📤 Uploading ({video_size//1024//1024} MB)...")

    # Category: 28 = Science & Tech, 24 = Entertainment
    category = "24" if is_short else "28"

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
                "title":       metadata["title"],
                "description": metadata["description"],
                "tags":        metadata["tags"][:30],
                "categoryId":  category,
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        },
    )
    if r.status_code != 200:
        raise Exception(f"Init failed: {r.text}")

    upload_url = r.headers["Location"]
    with open(video_path, "rb") as f:
        up = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4",
                     "Content-Length": str(video_size)},
            data=f,
        )

    if up.status_code in (200, 201):
        video_id = up.json()["id"]
        vtype = "#Shorts" if is_short else ""
        print(f"✅ Uploaded! https://youtube.com/watch?v={video_id} {vtype}")
        return video_id
    raise Exception(f"Upload failed: {up.text}")

def main():
    token    = get_access_token()
    is_short = False
    video_path = None
    meta_path  = None

    # Check what type of video to upload
    # Try short first
    short_meta = OUTPUT_DIR / "metadata_short.json"
    video_meta  = OUTPUT_DIR / "metadata.json"

    # Upload Short if exists
    if short_meta.exists() and (OUTPUT_DIR / "short_final.mp4").exists():
        print("\n📱 Uploading YouTube Short...")
        with open(short_meta) as f:
            meta = json.load(f)
        # Add #Shorts to title and description for discoverability
        meta["title"] = meta["title"][:97] + " #Shorts" if len(meta["title"]) < 92 else meta["title"][:91] + " #Shorts"
        vid_id = upload_video(str(OUTPUT_DIR/"short_final.mp4"), meta, token, is_short=True)

        # Add to Shorts playlist
        playlist_id = create_playlist(token, "MindBlownFacts Shorts",
                                      "Daily shocking facts in 60 seconds!")
        if playlist_id:
            add_to_playlist(token, vid_id, playlist_id)

    # Upload Video 1 if exists
    if video_meta.exists():
        # Find which video file exists
        for vnum in [1, 2]:
            vpath = OUTPUT_DIR / f"final_video_{vnum}.mp4"
            if vpath.exists():
                print(f"\n🎬 Uploading Video {vnum}...")
                with open(video_meta) as f:
                    meta = json.load(f)
                vid_id = upload_video(str(vpath), meta, token)

                # Thumbnail
                thumb = OUTPUT_DIR / "thumbnail.jpg"
                if thumb.exists():
                    upload_thumbnail(vid_id, str(thumb), token)

                # Add to playlist
                topic = meta.get("topic", "Facts")
                pl_title = f"{topic} Facts - MindBlownFacts"
                playlist_id = create_playlist(token, pl_title,
                                              f"All videos about {topic}")
                if playlist_id:
                    add_to_playlist(token, vid_id, playlist_id)
                break

    print("\n🎉 YouTube upload complete!")

if __name__ == "__main__":
    main()