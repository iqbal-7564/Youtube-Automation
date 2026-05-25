import os, json, requests
from pathlib import Path

OUTPUT_DIR            = Path("output")
YOUTUBE_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

def get_access_token():
    print("Getting YouTube token...")
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
    print("Uploading thumbnail...")
    with open(thumb_path,"rb") as f:
        r = requests.post(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
            headers={"Authorization": f"Bearer {token}"},
            files={"file":("thumbnail.jpg", f, "image/jpeg")},
        )
    print("Thumbnail uploaded!" if r.status_code==200 else f"Thumbnail failed: {r.text}")

def upload_to_youtube(video_path, metadata, thumbnail_path=None):
    token      = get_access_token()
    video_size = os.path.getsize(video_path)
    print(f"Starting upload ({video_size//1024//1024} MB)...")

    r = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization":           f"Bearer {token}",
            "Content-Type":            "application/json",
            "X-Upload-Content-Type":   "video/mp4",
            "X-Upload-Content-Length": str(video_size),
        },
        json={
            "snippet": {"title":metadata["title"],"description":metadata["description"],
                        "tags":metadata["tags"],"categoryId":"28"},
            "status":  {"privacyStatus":"public","selfDeclaredMadeForKids":False},
        },
    )
    if r.status_code != 200:
        raise Exception(f"Init failed: {r.text}")

    upload_url = r.headers["Location"]
    with open(video_path,"rb") as f:
        up = requests.put(upload_url,
                          headers={"Content-Type":"video/mp4","Content-Length":str(video_size)},
                          data=f)
    if up.status_code in (200,201):
        video_id = up.json()["id"]
        print(f"✅ Uploaded! https://youtube.com/watch?v={video_id}")
        if thumbnail_path and os.path.exists(thumbnail_path):
            upload_thumbnail(video_id, thumbnail_path, token)
        return video_id
    raise Exception(f"Upload failed: {up.text}")

def main():
    with open(OUTPUT_DIR/"metadata.json") as f:
        metadata = json.load(f)
    upload_to_youtube(
        str(OUTPUT_DIR/"final_video.mp4"),
        metadata,
        str(OUTPUT_DIR/"thumbnail.jpg"),
    )
    print("🎉 YouTube done!")

if __name__ == "__main__":
    main()