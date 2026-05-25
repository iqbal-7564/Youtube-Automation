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
        print(f"✅ Facebook posted! ID: {r.json().get('id')}")
        return r.json()
    else:
        raise Exception(f"Failed: {r.text}")


def main():
    # Find which video file exists
    possible_files = [
        OUTPUT_DIR / "final_video_1.mp4",
        OUTPUT_DIR / "final_video_2.mp4",
        OUTPUT_DIR / "short_final.mp4",
        OUTPUT_DIR / "final_video.mp4",
    ]

    video_path = None
    for f in possible_files:
        if f.exists():
            video_path = f
            print(f"Found video: {f}")
            break

    if not video_path:
        raise FileNotFoundError("No video file found in output folder!")

    # Find metadata
    meta_path = OUTPUT_DIR / "metadata.json"
    if not meta_path.exists():
        meta_path = OUTPUT_DIR / "metadata_short.json"

    with open(meta_path) as f:
        metadata = json.load(f)

    post_facebook_video(str(video_path), metadata)
    print("🎉 Facebook done!")


if __name__ == "__main__":
    main()