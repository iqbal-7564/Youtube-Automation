import os, json, requests
from pathlib import Path

OUTPUT_DIR      = Path("output")
FB_PAGE_ID      = os.environ["FB_PAGE_ID"]
FB_PAGE_TOKEN   = os.environ["FB_PAGE_TOKEN"]

def post_facebook_reel(reel_path, metadata):
    print("Posting Facebook Reel...")
    caption = (f"🤯 {metadata['title']}\n\n"
               f"Follow @MindBlownFacts for daily shocking facts!\n\n"
               f"#MindBlownFacts #Facts #DidYouKnow #AmazingFacts #Shocking #Viral")

    # Init
    init_r = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/video_reels",
        data={"upload_phase":"start","access_token":FB_PAGE_TOKEN},
    )
    if init_r.status_code != 200:
        raise Exception(f"Init failed: {init_r.text}")
    video_id   = init_r.json()["video_id"]
    upload_url = init_r.json()["upload_url"]

    # Upload
    file_size = os.path.getsize(reel_path)
    with open(reel_path,"rb") as f:
        up_r = requests.post(upload_url,
                             headers={"Authorization":f"OAuth {FB_PAGE_TOKEN}",
                                      "offset":"0","file_size":str(file_size),
                                      "Content-Type":"application/octet-stream"},
                             data=f)
    if not up_r.json().get("success"):
        raise Exception(f"Upload failed: {up_r.text}")

    # Publish
    pub_r = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/video_reels",
        data={"access_token":FB_PAGE_TOKEN,"video_id":video_id,
              "upload_phase":"finish","video_state":"PUBLISHED","description":caption},
    )
    if pub_r.status_code == 200:
        print(f"✅ Facebook Reel posted! ID: {video_id}")
        return video_id
    raise Exception(f"Publish failed: {pub_r.text}")

def main():
    with open(OUTPUT_DIR/"metadata.json") as f:
        metadata = json.load(f)
    post_facebook_reel(str(OUTPUT_DIR/"reel.mp4"), metadata)
    print("🎉 Facebook done!")

if __name__ == "__main__":
    main()