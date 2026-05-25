import os
import json
import random
import requests
import subprocess
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────
GROQ_API_KEY_1     = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2     = os.environ.get("GROQ_API_KEY_2")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY    = os.environ.get("PIXABAY_API_KEY")

VOICE_ID   = "21m00Tcm4TlvDq8ikWAM"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

TOPICS = [
    "Amazon Rainforest","Deep Ocean","Ancient Egypt",
    "Space and Universe","Human Body","Wild Animals",
    "World Records","Strange Countries","Incredible Technologies",
    "Historical Mysteries","Dangerous Places on Earth",
    "Richest People in History","Bizarre Natural Phenomena",
    "Unbelievable Animal Facts","Mind Blowing Science Facts",
    "Strangest Laws in the World","Most Expensive Things Ever",
    "Secrets of the Ancient World","Unsolved Mysteries of Earth",
    "Incredible Human Achievements",
]

# ─── GROQ AI (FREE) dual key ──────────────────────────────
def call_groq(prompt):
    keys = [k for k in [GROQ_API_KEY_1, GROQ_API_KEY_2] if k]
    for key in keys:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":prompt}],"temperature":0.8,"max_tokens":1500},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            print(f"Groq key failed {r.status_code}, trying next...")
        except Exception as e:
            print(f"Groq error: {e}")
    raise Exception("Both Groq keys failed!")

# ─── STEP 1: SCRIPT ───────────────────────────────────────
def generate_script(topic):
    print(f"Writing script: {topic}")
    prompt = f"""Write 8 shocking facts about "{topic}". 
Return ONLY this JSON format:
{{
  "title": "10 MIND BLOWING Facts About {topic}!",
  "intro": "Hook sentence here",
  "facts": [
    {{"number": 1, "fact": "fact here", "search_query": "nature"}},
    {{"number": 2, "fact": "fact here", "search_query": "ocean"}},
    {{"number": 3, "fact": "fact here", "search_query": "forest"}},
    {{"number": 4, "fact": "fact here", "search_query": "sky"}},
    {{"number": 5, "fact": "fact here", "search_query": "city"}},
    {{"number": 6, "fact": "fact here", "search_query": "mountain"}},
    {{"number": 7, "fact": "fact here", "search_query": "river"}},
    {{"number": 8, "fact": "fact here", "search_query": "wildlife"}}
  ],
  "outro": "Follow MindBlownFacts for more!"
}}"""

    text = call_groq(prompt).strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    import re
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return json.loads(text.strip())

# ─── STEP 2: VIDEOS ───────────────────────────────────────
def download_video(query, index):
    print(f"Downloading video: {query}")
    out_path = OUTPUT_DIR / f"clip_raw_{index}.mp4"
    url = None

    # Try Pexels
    try:
        r = requests.get(f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=landscape",
                         headers={"Authorization": PEXELS_API_KEY})
        videos = r.json().get("videos", [])
        if videos:
            files = sorted(random.choice(videos[:3])["video_files"], key=lambda x: x.get("width",0))
            url = next((f["link"] for f in files if f.get("width",0)>=1280), files[-1]["link"])
    except: pass

    # Try Pixabay
    if not url:
        try:
            r = requests.get(f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={query}&per_page=5")
            hits = r.json().get("hits", [])
            if hits:
                v = random.choice(hits[:3]).get("videos",{})
                chosen = v.get("large") or v.get("medium") or v.get("small")
                if chosen: url = chosen["url"]
        except: pass

    # Fallback
    if not url:
        r = requests.get("https://api.pexels.com/videos/search?query=nature&per_page=5",
                         headers={"Authorization": PEXELS_API_KEY})
        videos = r.json().get("videos",[])
        if videos:
            files = sorted(videos[0]["video_files"], key=lambda x: x.get("width",0))
            url = files[-1]["link"]

    r = requests.get(url, stream=True, timeout=60)
    with open(out_path,"wb") as f:
        for chunk in r.iter_content(8192): f.write(chunk)
    return str(out_path)

# ─── STEP 3: VOICE ────────────────────────────────────────
def generate_voice(text, index):
    print(f"Generating voice: {index}")
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text":text,"model_id":"eleven_monolingual_v1","voice_settings":{"stability":0.5,"similarity_boost":0.75}},
    )
    out_path = OUTPUT_DIR / f"voice_{index}.mp3"
    with open(out_path,"wb") as f: f.write(r.content)
    return str(out_path)

# ─── STEP 4: DURATION ─────────────────────────────────────
def get_duration(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","default=noprint_wrappers=1:nokey=1",path],capture_output=True,text=True)
    return float(r.stdout.strip())

# ─── STEP 5: BUILD CLIP ───────────────────────────────────
def build_clip(video_path, voice_path, text, index):
    print(f"Building clip {index}")
    duration = get_duration(voice_path) + 0.5
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current+word) < 35: current += word+" "
        else: lines.append(current.strip()); current = word+" "
    if current: lines.append(current.strip())
    safe_text = "\n".join(lines[:3]).replace("'","").replace('"',"").replace(":"," -")
    out_path = OUTPUT_DIR / f"clip_{index}.mp4"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_r = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    cmd = ["ffmpeg","-y","-stream_loop","-1","-i",video_path,"-i",voice_path,
           "-filter_complex",(
               f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
               f"zoompan=z='min(zoom+0.0008,1.3)':d={int(duration*25)}:s=1920x1080:fps=25,"
               f"drawbox=x=0:y=ih*0.65:w=iw:h=ih*0.35:color=black@0.7:t=fill,"
               f"drawtext=text='FACT {index}':fontcolor=yellow:fontsize=48:x=60:y=h*0.67:fontfile={font}:shadowcolor=black:shadowx=2:shadowy=2,"
               f"drawtext=text='{safe_text}':fontcolor=white:fontsize=34:x=60:y=h*0.74:fontfile={font_r}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=10[v]"),
           "-map","[v]","-map","1:a","-t",str(duration),"-c:v","libx264","-preset","fast","-c:a","aac","-shortest",str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── STEP 6: INTRO ────────────────────────────────────────
def build_intro(title, voice_path):
    print("Building intro...")
    duration = get_duration(voice_path) + 1.0
    out_path = OUTPUT_DIR / "clip_intro.mp4"
    safe = title.replace("'","").replace('"',"")[:55]
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    cmd = ["ffmpeg","-y","-f","lavfi","-i","color=c=0x0d0d0d:s=1920x1080:r=25","-i",voice_path,
           "-filter_complex",(f"[0:v]drawtext=text='MindBlownFacts':fontcolor=yellow:fontsize=72:x=(w-text_w)/2:y=h/5:fontfile={font},"
               f"drawtext=text='{safe}':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=h/2:fontfile={font}:shadowcolor=black:shadowx=2:shadowy=2,"
               f"drawtext=text='Prepare To Be SHOCKED':fontcolor=orange:fontsize=38:x=(w-text_w)/2:y=h*0.72:fontfile={font}[v]"),
           "-map","[v]","-map","1:a","-t",str(duration),"-c:v","libx264","-preset","fast","-c:a","aac","-shortest",str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── STEP 7: OUTRO ────────────────────────────────────────
def build_outro(voice_path):
    print("Building outro...")
    duration = get_duration(voice_path) + 1.0
    out_path = OUTPUT_DIR / "clip_outro.mp4"
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    cmd = ["ffmpeg","-y","-f","lavfi","-i","color=c=0x0d0d0d:s=1920x1080:r=25","-i",voice_path,
           "-filter_complex",(f"[0:v]drawtext=text='SUBSCRIBE':fontcolor=red:fontsize=100:x=(w-text_w)/2:y=h/4:fontfile={font},"
               f"drawtext=text='For Daily Mind Blowing Facts':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=h/2:fontfile={font},"
               f"drawtext=text='@MindBlownFacts':fontcolor=yellow:fontsize=44:x=(w-text_w)/2:y=h*0.7:fontfile={font}[v]"),
           "-map","[v]","-map","1:a","-t",str(duration),"-c:v","libx264","-preset","fast","-c:a","aac","-shortest",str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── STEP 8: CONCAT ───────────────────────────────────────
def concat_clips(clip_paths):
    print("Joining all clips...")
    list_file = OUTPUT_DIR / "clips_list.txt"
    with open(list_file,"w") as f:
        for cp in clip_paths: f.write(f"file '{os.path.abspath(cp)}'\n")
    out_path = OUTPUT_DIR / "final_video.mp4"
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(list_file),
                    "-c:v","libx264","-preset","fast","-c:a","aac",str(out_path)],check=True,capture_output=True)
    return str(out_path)

# ─── STEP 9: REEL ─────────────────────────────────────────
def extract_reel(video_path):
    print("Extracting 60-second Reel...")
    out_path = OUTPUT_DIR / "reel.mp4"
    subprocess.run(["ffmpeg","-y","-ss","10","-i",video_path,"-t","60",
                    "-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                    "-c:v","libx264","-preset","fast","-c:a","aac",str(out_path)],check=True,capture_output=True)
    return str(out_path)

# ─── STEP 10: THUMBNAIL ───────────────────────────────────
def generate_thumbnail(title):
    print("Generating thumbnail...")
    out_path = OUTPUT_DIR / "thumbnail.jpg"
    safe = title.replace("'","").replace('"',"")[:50]
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=c=0x1a1a2e:s=1280x720:r=1",
                    "-vf",(f"drawtext=text='MIND BLOWN':fontcolor=yellow:fontsize=100:x=(w-text_w)/2:y=80:fontfile={font},"
                           f"drawtext=text='FACTS':fontcolor=red:fontsize=120:x=(w-text_w)/2:y=190:fontfile={font},"
                           f"drawtext=text='{safe}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=390:fontfile={font},"
                           f"drawtext=text='You WONT Believe These':fontcolor=orange:fontsize=40:x=(w-text_w)/2:y=590:fontfile={font}"),
                    "-frames:v","1",str(out_path)],check=True,capture_output=True)
    return str(out_path)

# ─── METADATA ─────────────────────────────────────────────
def save_metadata(script_data, topic):
    desc = f"🤯 {script_data['title']}\n\nWelcome to MindBlownFacts!\n\n📌 FACTS:\n"
    for i,f in enumerate(script_data["facts"],1):
        desc += f"✅ Fact {i}: {f['fact'][:80]}...\n"
    desc += f"\n🔔 SUBSCRIBE!\n👍 LIKE!\n💬 COMMENT!\n\n#MindBlownFacts #Facts #DidYouKnow #{topic.replace(' ','')}"
    metadata = {"title":script_data["title"],"description":desc,
                "tags":["facts","mindblownfacts","didyouknow","amazingfacts",topic.lower().replace(" ",""),"shocking","viral"],
                "topic":topic}
    with open(OUTPUT_DIR/"metadata.json","w") as f: json.dump(metadata,f,indent=2)
    print("Metadata saved!")
    return metadata

# ─── MAIN ─────────────────────────────────────────────────
def main():
    topic = random.choice(TOPICS)
    print(f"\n🎯 Topic: {topic}\n{'='*50}")
    script = generate_script(topic)
    print(f"✅ Script: {script['title']}")
    intro_audio = generate_voice(script["intro"], "intro")
    outro_audio = generate_voice(script["outro"], "outro")
    fact_audios = [generate_voice(f["fact"], i+1) for i,f in enumerate(script["facts"])]
    fact_videos = [download_video(f["search_query"], i+1) for i,f in enumerate(script["facts"])]
    intro_clip  = build_intro(script["title"], intro_audio)
    fact_clips  = [build_clip(fact_videos[i],fact_audios[i],script["facts"][i]["fact"],i+1) for i in range(len(script["facts"]))]
    outro_clip  = build_outro(outro_audio)
    final_video = concat_clips([intro_clip]+fact_clips+[outro_clip])
    reel        = extract_reel(final_video)
    thumbnail   = generate_thumbnail(script["title"])
    save_metadata(script, topic)
    print(f"\n🎉 DONE!\n📹 Video: {final_video}\n📱 Reel: {reel}\n🖼️ Thumb: {thumbnail}\n")

if __name__ == "__main__":
    main()