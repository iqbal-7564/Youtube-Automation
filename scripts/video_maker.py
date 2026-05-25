import os
import json
import random
import requests
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────
GROQ_API_KEY_1     = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2     = os.environ.get("GROQ_API_KEY_2")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY    = os.environ.get("PIXABAY_API_KEY")

VOICE_ID   = "21m00Tcm4TlvDq8ikWAM"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
FONT_BOLD  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG   = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ─── EDGE TTS ASYNC ───────────────────────────────────────
async def edge_tts_generate(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(
        text,
        "en-US-ChristopherNeural",
        rate="+5%",
        volume="+10%"
    )
    await communicate.save(out_path)

# ─── DETECT VOICE ENGINE ONCE ─────────────────────────────
def detect_voice_engine():
    """Test Edge TTS first - best free natural voice"""
    print("🎙️ Testing voice engine...")

    # Test Edge TTS (best free option)
    try:
        test_path = str(OUTPUT_DIR / "voice_test.mp3")
        asyncio.run(edge_tts_generate("test", test_path))
        if os.path.exists(test_path) and os.path.getsize(test_path) > 500:
            print("✅ Using Edge TTS voice (Natural!)")
            return "edge"
    except Exception as e:
        print(f"Edge TTS failed: {e}")

    # Test ElevenLabs second
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY,
                     "Content-Type": "application/json"},
            json={"text": "test",
                  "model_id": "eleven_monolingual_v1",
                  "voice_settings": {"stability": 0.5,
                                     "similarity_boost": 0.75}},
            timeout=10,
        )
        if len(r.content) > 500:
            print("✅ Using ElevenLabs voice!")
            return "elevenlabs"
    except Exception as e:
        print(f"ElevenLabs failed: {e}")

    print("✅ Using gTTS voice (fallback)")
    return "gtts"

VOICE_ENGINE = detect_voice_engine()

# ─── TOPIC FORMATS ────────────────────────────────────────
VIDEO_FORMATS = [
    ("Top 10 {topic} Facts That Will Shock You!",
     ["Amazon Rainforest","Deep Ocean","Ancient Egypt","Space","Human Body"]),
    ("You Won't Believe These {topic} Facts!",
     ["Wild Animals","Ocean Creatures","Dangerous Plants","Weird Insects"]),
    ("Scientists Are SHOCKED By These {topic} Discoveries!",
     ["Space Universe","Deep Sea","Ancient Civilizations","Human Brain"]),
    ("The Dark Truth About {topic} Nobody Tells You!",
     ["Social Media","Fast Food","Big Companies","Modern Technology"]),
    ("Mind Blowing Facts About {topic} That Changed History!",
     ["Ancient Egypt","Roman Empire","World War","Medieval Times"]),
    ("These {topic} Facts Will Keep You Up At Night!",
     ["Deep Ocean","Space Black Holes","Volcanoes","Earthquakes"]),
    ("Why {topic} Is More Incredible Than You Think!",
     ["Human Body","Animal Kingdom","Planet Earth","Ocean Life"]),
    ("{topic} Secrets That Experts Don't Want You To Know!",
     ["Big Pharma","Tech Giants","Government","Ancient History"]),
    ("The Most Incredible {topic} Facts Ever Discovered!",
     ["Universe","Prehistoric Life","Lost Civilizations","Nature"]),
    ("Unbelievable {topic} Facts That Sound Fake But Are TRUE!",
     ["Animal Facts","Science Facts","History Facts","Nature Facts"]),
]

def get_random_format():
    fmt = random.choice(VIDEO_FORMATS)
    topic = random.choice(fmt[1])
    return topic, fmt[0]

ANIMAL_TOPICS = [
    "Wild Animals","Cute Baby Animals","Ocean Creatures",
    "Dangerous Animals","Extinct Animals","Smallest Animals",
    "Smartest Animals","Fastest Animals","Colorful Animals",
    "Weird Looking Animals",
]

MOTIVATION_TOPICS = [
    "Success Mindset","Life Changing Habits","Millionaire Mindset",
    "Powerful Life Lessons","Secrets of Happy People",
    "Morning Habits of Successful People","How to Be Confident",
]

# ─── DETECT VIDEO TYPE BY TIME ────────────────────────────
def get_video_type():
    hour  = datetime.utcnow().hour
    vtype = os.environ.get("VIDEO_TYPE", "")
    if vtype:
        return vtype
    if hour < 6:
        return "short"
    elif hour < 11:
        return "video1"
    else:
        return "video2"

# ─── GET TRENDING TOPIC ───────────────────────────────────
def get_trending_topic(category="facts"):
    print("🔥 Checking trending topics...")
    try:
        r = requests.get(
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code == 200:
            import re
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            titles = [t for t in titles if len(t) > 3 and 'Trending' not in t]
            if titles:
                trend = random.choice(titles[:10])
                print(f"🔥 Trending: {trend}")
                return f"Facts About {trend}"
    except Exception as e:
        print(f"Trends failed: {e}")

    if category == "animals":
        return random.choice(ANIMAL_TOPICS)
    elif category == "motivation":
        return random.choice(MOTIVATION_TOPICS)
    else:
        topic, _ = get_random_format()
        return topic

# ─── GROQ AI ──────────────────────────────────────────────
def call_groq(prompt):
    keys = [k for k in [GROQ_API_KEY_1, GROQ_API_KEY_2] if k]
    for key in keys:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.9, "max_tokens": 2000},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            print(f"Groq key failed {r.status_code}, trying next...")
        except Exception as e:
            print(f"Groq error: {e}")
    raise Exception("Both Groq keys failed!")

def clean_json(text):
    import re
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return text.strip()

# ─── GENERATE SHORT SCRIPT ────────────────────────────────
def generate_short_script(topic):
    print(f"✍️  Writing SHORT script: {topic}")
    prompt = f"""Write a 60-second YouTube Shorts script about one shocking fact about "{topic}".
Return ONLY valid JSON:
{{
  "title": "Shocking fact title max 60 chars",
  "hook": "First 3 seconds shocking statement",
  "fact": "Main shocking fact 4-5 sentences dramatic and unbelievable",
  "calltoaction": "Follow MindBlownFacts for daily shocking facts!",
  "search_query": "2 word video search term",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"]
}}
Return ONLY JSON"""
    text = call_groq(prompt)
    return json.loads(clean_json(text))

# ─── GENERATE VIDEO SCRIPT ────────────────────────────────
def generate_video_script(topic, video_num=1):
    print(f"✍️  Writing VIDEO script: {topic}")
    categories = {1: "facts/science/countries", 2: "animals/nature/funny"}
    category = categories.get(video_num, "facts")
    prompt = f"""Write a YouTube Top 10 countdown script about "{topic}" for {category} content.
Return ONLY valid JSON:
{{
  "title": "Top 10 Most Shocking Facts About {topic} That Will Blow Your Mind!",
  "hook": "Dramatic opening 2-3 sentences. Mention #1 is most shocking but save for last!",
  "facts": [
    {{"number": 10, "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 9,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 8,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 7,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 6,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 5,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 4,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 3,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 2,  "title": "Short dramatic title", "fact": "2-3 shocking sentences", "search_query": "2 word search"}},
    {{"number": 1,  "title": "Most shocking fact",   "fact": "3-4 sentences most dramatic saved for last!", "search_query": "2 word search"}}
  ],
  "midpoint_tease": "Stay till the end - number 1 will completely shock you!",
  "outro": "Subscribe to MindBlownFacts for daily mind blowing facts! Comment which fact shocked you most!",
  "description": "200 word SEO description about {topic} with keywords",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10","tag11","tag12","tag13","tag14","tag15","tag16","tag17","tag18","tag19","tag20"]
}}
Return ONLY JSON"""
    text = call_groq(prompt)
    return json.loads(clean_json(text))

# ─── VOICE GENERATION (ONE ENGINE WHOLE VIDEO) ────────────
def generate_voice(text, index):
    print(f"🎙️ Voice [{VOICE_ENGINE}]: {index}")
    out_path = str(OUTPUT_DIR / f"voice_{index}.mp3")

    if VOICE_ENGINE == "edge":
        try:
            asyncio.run(edge_tts_generate(text, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
                return out_path
        except Exception as e:
            print(f"Edge TTS error: {e}")

    elif VOICE_ENGINE == "elevenlabs":
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
                headers={"xi-api-key": ELEVENLABS_API_KEY,
                         "Content-Type": "application/json"},
                json={"text": text,
                      "model_id": "eleven_monolingual_v1",
                      "voice_settings": {"stability": 0.5,
                                         "similarity_boost": 0.75}},
                timeout=30,
            )
            if len(r.content) > 1000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path
        except Exception as e:
            print(f"ElevenLabs error: {e}")

    else:  # gtts
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(out_path)
            return out_path
        except Exception as e:
            print(f"gTTS error: {e}")

    # Silent fallback
    print(f"⚠️ Using silence for {index}")
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", "3", "-q:a", "9",
        "-acodec", "libmp3lame", out_path
    ], capture_output=True)
    return out_path

# ─── DURATION ─────────────────────────────────────────────
def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        val = r.stdout.strip()
        return float(val) if val else 3.0
    except:
        return 3.0

# ─── DOWNLOAD VIDEO ───────────────────────────────────────
def download_video(query, index):
    print(f"🎬 Video: {query}")
    out_path = OUTPUT_DIR / f"clip_raw_{index}.mp4"
    url = None

    try:
        r = requests.get(
            f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=landscape",
            headers={"Authorization": PEXELS_API_KEY}, timeout=15
        )
        videos = r.json().get("videos", [])
        if videos:
            files = sorted(random.choice(videos[:3])["video_files"],
                           key=lambda x: x.get("width", 0))
            url = next((f["link"] for f in files if f.get("width", 0) >= 1280),
                       files[-1]["link"])
    except:
        pass

    if not url:
        try:
            r = requests.get(
                f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={query}&per_page=5",
                timeout=15
            )
            hits = r.json().get("hits", [])
            if hits:
                v = random.choice(hits[:3]).get("videos", {})
                chosen = v.get("large") or v.get("medium") or v.get("small")
                if chosen:
                    url = chosen["url"]
        except:
            pass

    if not url:
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search?query=nature&per_page=5",
                headers={"Authorization": PEXELS_API_KEY}, timeout=15
            )
            videos = r.json().get("videos", [])
            if videos:
                files = sorted(videos[0]["video_files"],
                               key=lambda x: x.get("width", 0))
                url = files[-1]["link"]
        except:
            pass

    if url:
        r = requests.get(url, stream=True, timeout=60)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
    return str(out_path)

# ─── BACKGROUND MUSIC ─────────────────────────────────────
def download_music():
    print("🎵 Getting background music...")
    music_path = OUTPUT_DIR / "music.mp3"
    try:
        r = requests.get(
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q=cinematic+background&media_type=music&per_page=5",
            timeout=15
        )
        hits = r.json().get("hits", [])
        if hits:
            music_url = random.choice(hits[:3]).get("audio", {}).get("url")
            if music_url:
                mr = requests.get(music_url, timeout=30)
                with open(music_path, "wb") as f:
                    f.write(mr.content)
                return str(music_path)
    except:
        pass
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "aevalsrc=0.05*sin(330*2*PI*t):s=44100",
        "-t", "600", str(music_path)
    ], capture_output=True)
    return str(music_path)

# ─── BUILD SHORT ──────────────────────────────────────────
def build_short(video_path, voice_path, hook, fact, title):
    print("📱 Building YouTube Short...")
    duration  = get_duration(voice_path) + 0.5
    out_path  = OUTPUT_DIR / "short_final.mp4"
    safe_hook = hook.replace("'","").replace('"',"")[:40]
    words = fact.split()
    lines, current = [], ""
    for word in words:
        if len(current + word) < 30:
            current += word + " "
        else:
            lines.append(current.strip())
            current = word + " "
    if current:
        lines.append(current.strip())
    safe_fact = "\n".join(lines[:4]).replace("'","").replace('"',"")
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-i", voice_path,
        "-filter_complex",
        (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"zoompan=z='min(zoom+0.0005,1.2)':d={int(duration*25)}:s=1080x1920:fps=25,"
            f"drawbox=x=0:y=0:w=iw:h=180:color=black@0.8:t=fill,"
            f"drawbox=x=0:y=ih-300:w=iw:h=300:color=black@0.8:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=yellow:fontsize=45:"
            f"x=(w-text_w)/2:y=20:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_hook}':fontcolor=white:fontsize=40:"
            f"x=(w-text_w)/2:y=90:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=34:"
            f"x=40:y=h-280:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=8,"
            f"drawtext=text='FOLLOW FOR MORE!':fontcolor=yellow:fontsize=38:"
            f"x=(w-text_w)/2:y=h-60:fontfile={FONT_BOLD}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── BUILD FACT CLIP ──────────────────────────────────────
def build_fact_clip(video_path, voice_path, number, title, fact, music_path=None):
    print(f"🎞️  Building fact #{number}")
    duration   = get_duration(voice_path) + 0.5
    words = fact.split()
    lines, current = [], ""
    for word in words:
        if len(current + word) < 38:
            current += word + " "
        else:
            lines.append(current.strip())
            current = word + " "
    if current:
        lines.append(current.strip())
    safe_fact  = "\n".join(lines[:3]).replace("'","").replace('"',"")
    safe_title = title.replace("'","").replace('"',"")[:35]
    out_path   = OUTPUT_DIR / f"clip_{number}.mp4"
    temp_path  = OUTPUT_DIR / f"clip_nomusic_{number}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-i", voice_path,
        "-filter_complex",
        (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='min(zoom+0.0008,1.3)':d={int(duration*25)}:s=1920x1080:fps=25,"
            f"drawbox=x=0:y=0:w=200:h=80:color=red:t=fill,"
            f"drawtext=text='#{number}':fontcolor=white:fontsize=52:"
            f"x=20:y=10:fontfile={FONT_BOLD},"
            f"drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.75:t=fill,"
            f"drawtext=text='{safe_title}':fontcolor=yellow:fontsize=44:"
            f"x=40:y=h*0.64:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=32:"
            f"x=40:y=h*0.72:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=8[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(temp_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if music_path and os.path.exists(music_path):
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(temp_path), "-i", music_path,
            "-filter_complex",
            "[1:a]volume=0.08[music];[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            str(out_path),
        ]
        result = subprocess.run(cmd2, capture_output=True)
        if result.returncode != 0:
            import shutil
            shutil.copy(str(temp_path), str(out_path))
    else:
        import shutil
        shutil.copy(str(temp_path), str(out_path))
    return str(out_path)

# ─── BUILD INTRO (with real video background) ─────────────
def build_intro(title, hook_audio, topic, video_path):
    print("🎬 Building intro with video background...")
    duration   = get_duration(hook_audio) + 0.5
    out_path   = OUTPUT_DIR / "clip_intro.mp4"
    safe_title = title.replace("'","").replace('"',"")[:50]
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-i", hook_audio,
        "-filter_complex",
        (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='min(zoom+0.001,1.3)':d={int(duration*25)}:s=1920x1080:fps=25,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=yellow:fontsize=55:"
            f"x=(w-text_w)/2:y=80:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_title}':fontcolor=white:fontsize=46:"
            f"x=(w-text_w)/2:y=h/2-60:fontfile={FONT_BOLD}:"
            f"shadowcolor=black:shadowx=3:shadowy=3,"
            f"drawtext=text='Number 1 Will SHOCK You!':fontcolor=red:fontsize=42:"
            f"x=(w-text_w)/2:y=h/2+40:fontfile={FONT_BOLD}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(min(duration, 5.0)),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── BUILD TEASE ──────────────────────────────────────────
def build_tease(tease_audio):
    print("🎬 Building midpoint tease...")
    duration = get_duration(tease_audio) + 0.3
    out_path = OUTPUT_DIR / "clip_tease.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x1a0000:s=1920x1080:r=25",
        "-i", tease_audio,
        "-filter_complex",
        (
            f"[0:v]"
            f"drawtext=text='The TOP 5 Are Coming...':fontcolor=red:fontsize=72:"
            f"x=(w-text_w)/2:y=h/3:fontfile={FONT_BOLD},"
            f"drawtext=text='Number 1 Will BLOW Your Mind!':fontcolor=yellow:fontsize=52:"
            f"x=(w-text_w)/2:y=h/2:fontfile={FONT_BOLD}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── BUILD OUTRO ──────────────────────────────────────────
def build_outro(outro_audio):
    print("🎬 Building outro...")
    duration = get_duration(outro_audio) + 0.5
    out_path = OUTPUT_DIR / "clip_outro.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x0a0a0a:s=1920x1080:r=25",
        "-i", outro_audio,
        "-filter_complex",
        (
            f"[0:v]"
            f"drawtext=text='SUBSCRIBE':fontcolor=red:fontsize=110:"
            f"x=(w-text_w)/2:y=h/5:fontfile={FONT_BOLD},"
            f"drawtext=text='@MindBlownFacts':fontcolor=yellow:fontsize=60:"
            f"x=(w-text_w)/2:y=h/2-30:fontfile={FONT_BOLD},"
            f"drawtext=text='New Videos Every Day!':fontcolor=white:fontsize=44:"
            f"x=(w-text_w)/2:y=h/2+60:fontfile={FONT_REG},"
            f"drawtext=text='Comment Your Favorite Fact Below!':fontcolor=orange:fontsize=38:"
            f"x=(w-text_w)/2:y=h*0.75:fontfile={FONT_REG}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── CONCAT CLIPS ─────────────────────────────────────────
def concat_clips(clip_paths, output_name="final_video.mp4"):
    print("🔗 Joining clips...")
    list_file = OUTPUT_DIR / "clips_list.txt"
    with open(list_file, "w") as f:
        for cp in clip_paths:
            f.write(f"file '{os.path.abspath(cp)}'\n")
    out_path = OUTPUT_DIR / output_name
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
        str(out_path)
    ], check=True, capture_output=True)
    return str(out_path)

# ─── THUMBNAIL ────────────────────────────────────────────
def make_thumbnail(title, color="0x1a1a2e"):
    print("🖼️  Making thumbnail...")
    out_path = OUTPUT_DIR / "thumbnail.jpg"
    safe = title.replace("'","").replace('"',"")[:45]
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s=1280x720:r=1",
        "-vf", (
            f"drawtext=text='TOP 10':fontcolor=red:fontsize=130:"
            f"x=(w-text_w)/2:y=30:fontfile={FONT_BOLD},"
            f"drawtext=text='MIND BLOWING':fontcolor=yellow:fontsize=75:"
            f"x=(w-text_w)/2:y=185:fontfile={FONT_BOLD},"
            f"drawtext=text='FACTS':fontcolor=white:fontsize=90:"
            f"x=(w-text_w)/2:y=265:fontfile={FONT_BOLD},"
            f"drawbox=x=0:y=390:w=iw:h=4:color=red:t=fill,"
            f"drawtext=text='{safe}':fontcolor=white:fontsize=36:"
            f"x=(w-text_w)/2:y=410:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='You WONT Believe #1':fontcolor=orange:fontsize=42:"
            f"x=(w-text_w)/2:y=610:fontfile={FONT_BOLD}"
        ),
        "-frames:v", "1", str(out_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── SAVE METADATA ────────────────────────────────────────
def save_metadata(title, description, tags, topic, video_type, is_short=False):
    chapters = ""
    if not is_short:
        chapters = "\n\n📌 CHAPTERS:\n00:00 Introduction\n"
        for i in range(10, 0, -1):
            mins = (11 - i) * 42
            chapters += f"{mins//60:02d}:{mins%60:02d} #{i} - Fact {11-i}\n"
    full_desc = (
        f"🤯 {title}\n\n"
        f"{description}\n"
        f"{chapters}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 SUBSCRIBE for daily mind-blowing facts!\n"
        f"👍 LIKE if this shocked you!\n"
        f"💬 COMMENT which fact surprised you most!\n"
        f"📤 SHARE with someone who needs to see this!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"#MindBlownFacts #Facts #DidYouKnow "
        f"#{topic.replace(' ','')} #Shocking #Viral #Educational"
    )
    metadata = {
        "title":       title,
        "description": full_desc,
        "tags":        tags[:30],
        "topic":       topic,
        "video_type":  video_type,
        "is_short":    is_short,
    }
    fname = "metadata_short.json" if is_short else "metadata.json"
    with open(OUTPUT_DIR / fname, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✅ Metadata saved: {fname}")
    return metadata

# ═══════════════════════════════════════════════════════════
# MAKE SHORT
# ═══════════════════════════════════════════════════════════
def make_short():
    print("\n📱 MAKING YOUTUBE SHORT\n" + "="*50)
    topic  = get_trending_topic("facts")
    script = generate_short_script(topic)
    full_text = f"{script['hook']} {script['fact']} {script['calltoaction']}"
    voice  = generate_voice(full_text, "short")
    video  = download_video(script["search_query"], "short")
    final  = build_short(video, voice, script["hook"], script["fact"], script["title"])
    tags   = script.get("tags", ["facts","mindblownfacts","shorts","viral","didyouknow"])
    tags  += ["Shorts","YouTubeShorts","mindblown","shocking","facts"]
    save_metadata(
        script["title"],
        f"🤯 {script['fact']}\n\nFollow MindBlownFacts for daily shocking facts!",
        tags, topic, "short", is_short=True
    )
    print(f"\n✅ SHORT DONE: {final}")
    return final

# ═══════════════════════════════════════════════════════════
# MAKE VIDEO
# ═══════════════════════════════════════════════════════════
def make_video(video_num=1):
    print(f"\n🎬 MAKING VIDEO {video_num}\n" + "="*50)
    topic, title_template = get_random_format()
    print(f"Format: {title_template}")
    script = generate_video_script(topic, video_num)
    music  = download_music()

    hook_audio  = generate_voice(script["hook"], "hook")
    tease_audio = generate_voice(script["midpoint_tease"], "tease")
    outro_audio = generate_voice(script["outro"], "outro")
    fact_audios = [generate_voice(f["fact"], f["number"]) for f in script["facts"]]
    fact_videos = [download_video(f["search_query"], f["number"]) for f in script["facts"]]

    intro_clip = build_intro(script["title"], hook_audio, topic, fact_videos[0])
    fact_clips = []
    for i, fact in enumerate(script["facts"]):
        clip = build_fact_clip(fact_videos[i], fact_audios[i],
                               fact["number"], fact["title"], fact["fact"], music)
        fact_clips.append(clip)
        if fact["number"] == 5:
            fact_clips.append(build_tease(tease_audio))

    outro_clip = build_outro(outro_audio)
    all_clips  = [intro_clip] + fact_clips + [outro_clip]
    fname      = f"final_video_{video_num}.mp4"
    final      = concat_clips(all_clips, fname)

    colors = {1: "0x1a1a2e", 2: "0x0d1f0d"}
    make_thumbnail(script["title"], colors.get(video_num, "0x1a1a2e"))

    tags = script.get("tags", [])
    tags += ["facts","mindblownfacts","didyouknow","top10",
             "shocking","viral","educational", topic.lower().replace(" ","")]
    save_metadata(
        script["title"],
        script.get("description", f"Top 10 shocking facts about {topic}"),
        tags, topic, f"video{video_num}"
    )
    print(f"\n✅ VIDEO {video_num} DONE: {final}")
    return final

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    vtype = get_video_type()
    print(f"\n🎯 Video Type: {vtype}")
    print(f"🕐 UTC Hour: {datetime.utcnow().hour}")
    if vtype == "short":
        make_short()
    elif vtype == "video2":
        make_video(2)
    else:
        make_video(1)
    print("\n🎉 ALL DONE!")

if __name__ == "__main__":
    main()