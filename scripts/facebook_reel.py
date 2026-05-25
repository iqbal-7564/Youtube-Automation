import os
import json
import requests
from pathlib import Path

OUTPUT_DIR    = Path("output")
FB_PAGE_ID    = os.environ["FB_PAGE_ID"]
FB_PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]

def post_facebook_video(video_path, metadata):
    print("Posting to Facebook...")
    
    caption = (
        f"🤯 {metadata['title']}\n\n"
        f"Follow MindBlownFacts for daily "
        f"shocking facts!\n\n"
        f"#MindBlownFacts #Facts #DidYouKnow "
        f"#AmazingFacts #Shocking #Viral"
    )

    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/videos"
    
    with open(video_path, "rb") as f:
        r = requests.post(
            url,
            data={
                "access_token": FB_PAGE_TOKEN,
                "description":  caption,
                "title":        metadata["title"],
            },
            files={"source": ("video.mp4", f, "video/mp4")},
            timeout=300,
        )

    if r.status_code == 200:
        video_id = r.json().get("id")
        print(f"✅ Facebook posted! ID: {video_id}")
        return video_id
    else:
        raise Exception(f"Failed: {r.text}")


def main():
    with open(OUTPUT_DIR / "metadata.json") as f:
        metadata = json.load(f)
    
    # Post reel (60 sec) to Facebook
    reel_path  = OUTPUT_DIR / "reel.mp4"
    video_path = OUTPUT_DIR / "final_video.mp4"
    
    # Try short reel first
    if reel_path.exists():
        post_facebook_video(str(reel_path), metadata)
    else:
        post_facebook_video(str(video_path), metadata)
    
    print("🎉 Facebook done!")


if __name__ == "__main__":
    main()