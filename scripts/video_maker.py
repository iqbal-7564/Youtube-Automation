import os
import json
import random
import requests
import subprocess
import asyncio
import re
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
HISTORY_FILE = OUTPUT_DIR / "format_history.json"

# ─── FORMAT HISTORY (avoid repeating) ────────────────────
def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"used_formats": [], "used_topics": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def pick_unique(items, used_list, max_history=10):
    """Pick item not used recently"""
    available = [i for i in items if i not in used_list[-max_history:]]
    if not available:
        available = items
    choice = random.choice(available)
    used_list.append(choice)
    if len(used_list) > 20:
        used_list = used_list[-20:]
    return choice, used_list

# ─── 20+ DIFFERENT VIDEO FORMATS ─────────────────────────
VIDEO_FORMATS = [
    {
        "id": "shocking_truth",
        "title_template": "The Shocking Truth About {topic} Nobody Talks About",
        "style": "investigative",
        "color": "0x1a0000",
        "accent": "red",
        "count": 8,
        "prompt_style": "investigative shocking revelations"
    },
    {
        "id": "science_explained",
        "title_template": "Scientists Finally Explained {topic} And Its Mind Blowing",
        "style": "science",
        "color": "0x001a2e",
        "accent": "cyan",
        "count": 8,
        "prompt_style": "scientific explanations and discoveries"
    },
    {
        "id": "what_if",
        "title_template": "What If {topic} Happened Tomorrow",
        "style": "hypothetical",
        "color": "0x0d0d1a",
        "accent": "purple",
        "count": 6,
        "prompt_style": "hypothetical scenarios what would happen if"
    },
    {
        "id": "history_dark",
        "title_template": "The Dark History of {topic} They Never Taught You",
        "style": "history",
        "color": "0x1a1000",
        "accent": "orange",
        "count": 8,
        "prompt_style": "dark historical facts hidden from public"
    },
    {
        "id": "vs_comparison",
        "title_template": "{topic} vs {topic2} - The Truth Will Surprise You",
        "style": "comparison",
        "color": "0x001a00",
        "accent": "green",
        "count": 6,
        "prompt_style": "detailed comparison between two things"
    },
    {
        "id": "secrets_exposed",
        "title_template": "{topic} Secrets That Experts Kept Hidden For Years",
        "style": "exposed",
        "color": "0x1a0010",
        "accent": "pink",
        "count": 8,
        "prompt_style": "hidden secrets and exposed information"
    },
    {
        "id": "incredible_story",
        "title_template": "The Incredible True Story of {topic}",
        "style": "story",
        "color": "0x0a0a00",
        "accent": "yellow",
        "count": 1,
        "prompt_style": "compelling narrative story format"
    },
    {
        "id": "record_breakers",
        "title_template": "{topic} Records That Seem Impossible But Are Real",
        "style": "records",
        "color": "0x001010",
        "accent": "teal",
        "count": 8,
        "prompt_style": "world records and extreme achievements"
    },
    {
        "id": "why_nobody_knows",
        "title_template": "Why Nobody Talks About {topic} - This Will Shock You",
        "style": "mystery",
        "color": "0x100010",
        "accent": "violet",
        "count": 8,
        "prompt_style": "mysterious overlooked information"
    },
    {
        "id": "future_prediction",
        "title_template": "What {topic} Will Look Like in 2050 - Experts Reveal",
        "style": "future",
        "color": "0x000d1a",
        "accent": "blue",
        "count": 8,
        "prompt_style": "expert predictions about the future"
    },
    {
        "id": "biggest_mistakes",
        "title_template": "Biggest Mistakes About {topic} That Everyone Believes",
        "style": "myths",
        "color": "0x1a0a00",
        "accent": "amber",
        "count": 8,
        "prompt_style": "common myths and misconceptions debunked"
    },
    {
        "id": "survival_facts",
        "title_template": "{topic} Facts That Could Actually Save Your Life",
        "style": "survival",
        "color": "0x001a0a",
        "accent": "lime",
        "count": 8,
        "prompt_style": "life saving survival information and facts"
    },
    {
        "id": "mind_tricks",
        "title_template": "How {topic} Is Secretly Controlling Your Brain",
        "style": "psychology",
        "color": "0x0d001a",
        "accent": "indigo",
        "count": 8,
        "prompt_style": "psychological effects and mind control facts"
    },
    {
        "id": "money_secrets",
        "title_template": "{topic} Money Secrets The Rich Don't Want You To Know",
        "style": "money",
        "color": "0x001a00",
        "accent": "gold",
        "count": 8,
        "prompt_style": "financial secrets and money making facts"
    },
    {
        "id": "nature_extreme",
        "title_template": "Most Extreme {topic} Events Ever Recorded on Earth",
        "style": "extreme",
        "color": "0x1a0500",
        "accent": "firebrick",
        "count": 8,
        "prompt_style": "extreme natural events and phenomena"
    },
    {
        "id": "genius_facts",
        "title_template": "Facts About {topic} That Only Geniuses Know",
        "style": "genius",
        "color": "0x00101a",
        "accent": "sky",
        "count": 8,
        "prompt_style": "advanced little known genius level facts"
    },
    {
        "id": "conspiracy_truth",
        "title_template": "The Real Truth Behind {topic} Finally Revealed",
        "style": "reveal",
        "color": "0x0f0f0f",
        "accent": "silver",
        "count": 8,
        "prompt_style": "officially revealed previously unknown truths"
    },
    {
        "id": "country_facts",
        "title_template": "Why {topic} Is The Most Surprising Country in The World",
        "style": "country",
        "color": "0x001510",
        "accent": "emerald",
        "count": 8,
        "prompt_style": "surprising country facts culture and history"
    },
    {
        "id": "animal_bizarre",
        "title_template": "Most Bizarre Things {topic} Animals Do That Shock Scientists",
        "style": "animals",
        "color": "0x0a1500",
        "accent": "forest",
        "count": 8,
        "prompt_style": "bizarre animal behaviors and shocking facts"
    },
    {
        "id": "ancient_mystery",
        "title_template": "Ancient {topic} Mysteries That Science Cannot Explain",
        "style": "ancient",
        "color": "0x150a00",
        "accent": "bronze",
        "count": 8,
        "prompt_style": "ancient unsolved mysteries and archaeological wonders"
    },
]

# ─── TOPIC POOLS ──────────────────────────────────────────
TOPICS = {
    "science":    ["Human Brain","DNA","Black Holes","Quantum Physics","Deep Ocean","Volcanoes","Bacteria","Time","Light Speed","Gravity"],
    "history":    ["Ancient Egypt","Roman Empire","World War 2","Vikings","Ancient China","Ottoman Empire","Cold War","Medieval Times","Ancient Greece","Aztec Empire"],
    "animals":    ["Great White Sharks","Octopus","Wolves","Eagles","Cheetahs","Elephants","Dolphins","Crocodiles","Gorillas","Mantis Shrimp"],
    "countries":  ["Japan","Norway","Iceland","Singapore","Switzerland","New Zealand","Finland","Canada","South Korea","Netherlands"],
    "technology": ["Artificial Intelligence","Internet","Smartphones","Nuclear Energy","Space Rockets","Electric Cars","Quantum Computers","Bitcoin","Solar Power","Robots"],
    "nature":     ["Amazon Rainforest","Sahara Desert","Mariana Trench","Mount Everest","Northern Lights","Great Barrier Reef","Niagara Falls","Grand Canyon","Dead Sea","Antarctica"],
    "money":      ["Bitcoin","Gold","Real Estate","Stock Market","Warren Buffett","Jeff Bezos","Oil Industry","Diamond Industry","Luxury Brands","Banks"],
    "psychology": ["Dreams","Memory","Fear","Addiction","Love","Anger","Happiness","Intelligence","Creativity","Persuasion"],
    "food":       ["Honey","Coffee","Salt","Sugar","Spices","Chocolate","Cheese","Bread","Rice","Meat"],
    "space":      ["Mars","Saturn","Jupiter","Sun","Moon","Asteroids","Galaxies","Nebulas","Dark Matter","Exoplanets"],
}

VS_PAIRS = [
    ("Amazon", "Sahara"), ("Sun", "Moon"), ("Einstein", "Newton"),
    ("Ancient Egypt", "Ancient Rome"), ("Sharks", "Crocodiles"),
    ("Mars", "Venus"), ("Tigers", "Lions"), ("USA", "China"),
    ("Ocean", "Space"), ("Ancient Greeks", "Ancient Vikings"),
]

# ─── TRENDING FROM MULTIPLE SOURCES ───────────────────────
def get_trending_topic():
    print("🔥 Finding trending topic...")
    trending = []

    # Source 1: Google Trends RSS
    try:
        r = requests.get(
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code == 200:
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            titles = [t for t in titles if len(t) > 4 and 'Trending' not in t]
            trending.extend(titles[:5])
            print(f"✅ Google Trends: {titles[:3]}")
    except Exception as e:
        print(f"Google Trends failed: {e}")

    # Source 2: BBC News RSS
    try:
        r = requests.get(
            "http://feeds.bbci.co.uk/news/rss.xml",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code == 200:
            titles = re.findall(r'<title>(.*?)</title>', r.text)
            titles = [t for t in titles if len(t) > 10 and 'BBC' not in t][:5]
            trending.extend(titles)
            print(f"✅ BBC News: {titles[:2]}")
    except Exception as e:
        print(f"BBC News failed: {e}")

    # Source 3: Reuters RSS
    try:
        r = requests.get(
            "https://feeds.reuters.com/reuters/topNews",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code == 200:
            titles = re.findall(r'<title>(.*?)</title>', r.text)
            titles = [t for t in titles if len(t) > 10][:5]
            trending.extend(titles)
            print(f"✅ Reuters: {titles[:2]}")
    except Exception as e:
        print(f"Reuters failed: {e}")

    if trending:
        topic = random.choice(trending[:10])
        print(f"🔥 Using trending: {topic}")
        return topic

    # Fallback: Pick from topic pools
    category = random.choice(list(TOPICS.keys()))
    topic = random.choice(TOPICS[category])
    print(f"📌 Using fallback: {topic}")
    return topic

# ─── PICK FORMAT (no repetition) ─────────────────────────
def pick_format(history):
    used = history.get("used_formats", [])
    available = [f for f in VIDEO_FORMATS if f["id"] not in used[-8:]]
    if not available:
        available = VIDEO_FORMATS
    fmt = random.choice(available)
    used.append(fmt["id"])
    history["used_formats"] = used[-20:]
    return fmt, history

# ─── PICK TOPIC (no repetition) ──────────────────────────
def pick_topic(fmt, history):
    used = history.get("used_topics", [])

    if fmt["id"] == "vs_comparison":
        pair = random.choice(VS_PAIRS)
        topic = pair[0]
        topic2 = pair[1]
        title = fmt["title_template"].replace("{topic}", topic).replace("{topic2}", topic2)
    else:
        # 40% chance use trending
        if random.random() < 0.4:
            topic = get_trending_topic()
        else:
            category = random.choice(list(TOPICS.keys()))
            available = [t for t in TOPICS[category] if t not in used[-15:]]
            if not available:
                available = TOPICS[category]
            topic = random.choice(available)

        title = fmt["title_template"].replace("{topic}", topic)
        topic2 = None

    used.append(topic)
    history["used_topics"] = used[-30:]
    return topic, title, history

# ─── EDGE TTS ─────────────────────────────────────────────
async def edge_tts_generate(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(
        text,
        "en-US-ChristopherNeural",
        rate="+5%",
        volume="+10%"
    )
    await communicate.save(out_path)

def detect_voice_engine():
    print("🎙️ Testing voice engine...")
    try:
        test_path = str(OUTPUT_DIR / "voice_test.mp3")
        asyncio.run(edge_tts_generate("test", test_path))
        if os.path.exists(test_path) and os.path.getsize(test_path) > 500:
            print("✅ Edge TTS (Natural voice!)")
            return "edge"
    except Exception as e:
        print(f"Edge TTS failed: {e}")
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={"text": "test", "model_id": "eleven_monolingual_v1",
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            timeout=10,
        )
        if len(r.content) > 500:
            print("✅ ElevenLabs voice!")
            return "elevenlabs"
    except:
        pass
    print("✅ gTTS fallback")
    return "gtts"

VOICE_ENGINE = detect_voice_engine()

# ─── GROQ AI ──────────────────────────────────────────────
def call_groq(prompt):
    keys = [k for k in [GROQ_API_KEY_1, GROQ_API_KEY_2] if k]
    for key in keys:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.9, "max_tokens": 2500},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            print(f"Groq failed {r.status_code}, trying next...")
        except Exception as e:
            print(f"Groq error: {e}")
    raise Exception("Both Groq keys failed!")

def clean_json(text):
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    return text.strip()

# ─── GENERATE SCRIPT ──────────────────────────────────────
def generate_script(topic, title, fmt):
    print(f"✍️  Writing script: {title}")
    count = fmt["count"]
    style = fmt["prompt_style"]

    prompt = f"""Write a YouTube video script titled "{title}" about "{topic}".
Style: {style}
Number of facts/points: {count}

Return ONLY valid JSON:
{{
  "title": "{title}",
  "hook": "Dramatic opening 2-3 sentences that immediately grabs attention. Tease most shocking point at end!",
  "facts": [
    {{"number": 1, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 2, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 3, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 4, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 5, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 6, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 7, "title": "Dramatic point title", "fact": "2-3 shocking sentences", "search_query": "2 words"}},
    {{"number": 8, "title": "Most shocking point", "fact": "3-4 sentences most dramatic saved for last!", "search_query": "2 words"}}
  ],
  "midpoint_tease": "Short sentence teasing the best point coming up!",
  "outro": "Subscribe for more shocking content! Comment which fact shocked you most!",
  "seo_keywords": ["keyword1","keyword2","keyword3","keyword4","keyword5"],
  "description": "150 word SEO rich description with keywords naturally included",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10","tag11","tag12","tag13","tag14","tag15","tag16","tag17","tag18","tag19","tag20"]
}}
Return ONLY JSON no other text."""

    text = call_groq(prompt)
    return json.loads(clean_json(text))

# ─── GENERATE SHORT SCRIPT ────────────────────────────────
def generate_short_script(topic):
    print(f"✍️  Writing SHORT: {topic}")
    prompt = f"""Write a viral 60-second YouTube Shorts script about "{topic}".
Return ONLY valid JSON:
{{
  "title": "Shocking title max 60 chars",
  "hook": "Most shocking statement in 1 sentence - grabs attention immediately",
  "fact": "Shocking fact explained in 4-5 dramatic sentences",
  "calltoaction": "Follow MindBlownFacts for daily shocking facts!",
  "search_query": "2 word video search",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"]
}}
Return ONLY JSON"""
    text = call_groq(prompt)
    return json.loads(clean_json(text))

# ─── VOICE ────────────────────────────────────────────────
def generate_voice(text, index):
    print(f"🎙️ [{VOICE_ENGINE}] voice: {index}")
    out_path = str(OUTPUT_DIR / f"voice_{index}.mp3")

    if VOICE_ENGINE == "edge":
        try:
            asyncio.run(edge_tts_generate(text, out_path))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
                return out_path
        except Exception as e:
            print(f"Edge error: {e}")

    elif VOICE_ENGINE == "elevenlabs":
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
                headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_monolingual_v1",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
                timeout=30,
            )
            if len(r.content) > 1000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path
        except Exception as e:
            print(f"ElevenLabs error: {e}")

    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(out_path)
        return out_path
    except Exception as e:
        print(f"gTTS error: {e}")

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
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        val = r.stdout.strip()
        return float(val) if val else 3.0
    except:
        return 3.0

# ─── DOWNLOAD VIDEO ───────────────────────────────────────
def download_video(query, index):
    print(f"🎬 Downloading: {query}")
    out_path = OUTPUT_DIR / f"clip_raw_{index}.mp4"
    url = None

    try:
        r = requests.get(
            f"https://api.pexels.com/videos/search?query={query}&per_page=10&orientation=landscape",
            headers={"Authorization": PEXELS_API_KEY}, timeout=15
        )
        videos = r.json().get("videos", [])
        if videos:
            # Pick random from top 5 for variety
            video = random.choice(videos[:5])
            files = sorted(video["video_files"], key=lambda x: x.get("width", 0))
            url = next((f["link"] for f in files if f.get("width", 0) >= 1280),
                       files[-1]["link"])
    except:
        pass

    if not url:
        try:
            r = requests.get(
                f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={query}&per_page=10",
                timeout=15
            )
            hits = r.json().get("hits", [])
            if hits:
                v = random.choice(hits[:5]).get("videos", {})
                chosen = v.get("large") or v.get("medium") or v.get("small")
                if chosen:
                    url = chosen["url"]
        except:
            pass

    if not url:
        fallbacks = ["nature", "sky", "ocean", "forest", "city"]
        fb = random.choice(fallbacks)
        try:
            r = requests.get(
                f"https://api.pexels.com/videos/search?query={fb}&per_page=5",
                headers={"Authorization": PEXELS_API_KEY}, timeout=15
            )
            videos = r.json().get("videos", [])
            if videos:
                files = sorted(random.choice(videos)["video_files"],
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

# ─── DOWNLOAD THUMBNAIL IMAGE ─────────────────────────────
def download_thumb_image(topic):
    """Download actual image for thumbnail background"""
    print(f"🖼️  Getting thumbnail image: {topic}")
    out_path = OUTPUT_DIR / "thumb_bg.jpg"
    try:
        r = requests.get(
            f"https://api.pexels.com/v1/search?query={topic}&per_page=10&orientation=landscape",
            headers={"Authorization": PEXELS_API_KEY}, timeout=15
        )
        photos = r.json().get("photos", [])
        if photos:
            photo = random.choice(photos[:5])
            img_url = photo["src"]["large"]
            ir = requests.get(img_url, timeout=30)
            with open(out_path, "wb") as f:
                f.write(ir.content)
            return str(out_path)
    except Exception as e:
        print(f"Thumb image failed: {e}")
    return None

# ─── BACKGROUND MUSIC ─────────────────────────────────────
def download_music():
    print("🎵 Getting music...")
    music_path = OUTPUT_DIR / "music.mp3"
    moods = ["cinematic", "inspiring", "dramatic", "epic", "mysterious"]
    mood  = random.choice(moods)
    try:
        r = requests.get(
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={mood}&media_type=music&per_page=10",
            timeout=15
        )
        hits = r.json().get("hits", [])
        if hits:
            music_url = random.choice(hits[:5]).get("audio", {}).get("url")
            if music_url:
                mr = requests.get(music_url, timeout=30)
                with open(music_path, "wb") as f:
                    f.write(mr.content)
                print(f"✅ Music: {mood}")
                return str(music_path)
    except:
        pass
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "aevalsrc=0.05*sin(330*2*PI*t):s=44100",
        "-t", "600", str(music_path)
    ], capture_output=True)
    return str(music_path)

# ─── BUILD THUMBNAIL (with real image!) ───────────────────
def make_thumbnail(title, topic, fmt):
    print("🖼️  Making eye-catching thumbnail...")
    out_path   = OUTPUT_DIR / "thumbnail.jpg"
    thumb_bg   = download_thumb_image(topic)
    safe_title = title.replace("'","").replace('"',"").replace(":","")
    # Split title into 2 lines
    words      = safe_title.split()
    mid        = len(words) // 2
    line1      = " ".join(words[:mid])[:35]
    line2      = " ".join(words[mid:])[:35]
    accent     = fmt.get("accent", "yellow")

    # Color map
    accent_colors = {
        "red": "red", "cyan": "00FFFF", "purple": "CC00FF",
        "orange": "FF6600", "green": "00FF00", "gold": "FFD700",
        "yellow": "FFD700", "blue": "0088FF", "amber": "FFBF00",
        "teal": "00CCBB", "pink": "FF69B4", "lime": "AAFF00",
    }
    color_hex = accent_colors.get(accent, "FFD700")

    if thumb_bg and os.path.exists(thumb_bg):
        # Use real photo as background!
        cmd = [
            "ffmpeg", "-y", "-i", thumb_bg,
            "-vf", (
                f"scale=1280:720:force_original_aspect_ratio=increase,"
                f"crop=1280:720,"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.55:t=fill,"
                f"drawbox=x=0:y=0:w=iw:h=8:color=#{color_hex}:t=fill,"
                f"drawbox=x=0:y=ih-8:w=iw:h=8:color=#{color_hex}:t=fill,"
                f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=36:"
                f"x=(w-text_w)/2:y=20:fontfile={FONT_BOLD},"
                f"drawtext=text='{line1}':fontcolor=white:fontsize=68:"
                f"x=(w-text_w)/2:y=200:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=4:shadowy=4,"
                f"drawtext=text='{line2}':fontcolor=#{color_hex}:fontsize=68:"
                f"x=(w-text_w)/2:y=300:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=4:shadowy=4,"
                f"drawtext=text='Watch Till End!':fontcolor=white:fontsize=42:"
                f"x=(w-text_w)/2:y=620:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=2:shadowy=2"
            ),
            "-frames:v", "1", str(out_path)
        ]
    else:
        # Fallback colored background
        bg_color = fmt.get("color", "0x1a1a2e")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={bg_color}:s=1280x720:r=1",
            "-vf", (
                f"drawbox=x=0:y=0:w=iw:h=8:color=#{color_hex}:t=fill,"
                f"drawbox=x=0:y=ih-8:w=iw:h=8:color=#{color_hex}:t=fill,"
                f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=36:"
                f"x=(w-text_w)/2:y=20:fontfile={FONT_BOLD},"
                f"drawtext=text='{line1}':fontcolor=white:fontsize=68:"
                f"x=(w-text_w)/2:y=200:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=4:shadowy=4,"
                f"drawtext=text='{line2}':fontcolor=#{color_hex}:fontsize=68:"
                f"x=(w-text_w)/2:y=300:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=4:shadowy=4,"
                f"drawtext=text='Watch Till End!':fontcolor=white:fontsize=42:"
                f"x=(w-text_w)/2:y=620:fontfile={FONT_BOLD}"
            ),
            "-frames:v", "1", str(out_path)
        ]

    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── BUILD INTRO (real video bg, max 5 sec) ───────────────
def build_intro(title, hook_audio, video_path, fmt):
    print("🎬 Building intro...")
    duration   = min(get_duration(hook_audio) + 0.5, 5.0)
    out_path   = OUTPUT_DIR / "clip_intro.mp4"
    safe_title = title.replace("'","").replace('"',"").replace(":","")[:50]
    accent     = fmt.get("accent", "yellow")
    accent_colors = {
        "red": "FF0000", "cyan": "00FFFF", "purple": "CC00FF",
        "orange": "FF6600", "green": "00FF00", "gold": "FFD700",
        "yellow": "FFD700", "blue": "0088FF", "amber": "FFBF00",
    }
    color_hex = accent_colors.get(accent, "FFD700")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-i", hook_audio,
        "-filter_complex",
        (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='min(zoom+0.001,1.3)':d={int(duration*25)}:s=1920x1080:fps=25,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.6:t=fill,"
            f"drawbox=x=0:y=0:w=iw:h=6:color=#{color_hex}:t=fill,"
            f"drawbox=x=0:y=ih-6:w=iw:h=6:color=#{color_hex}:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=52:"
            f"x=(w-text_w)/2:y=60:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_title}':fontcolor=white:fontsize=46:"
            f"x=(w-text_w)/2:y=h/2-40:fontfile={FONT_BOLD}:"
            f"shadowcolor=black:shadowx=3:shadowy=3,"
            f"drawtext=text='Stay Till The End!':fontcolor=#{color_hex}:fontsize=40:"
            f"x=(w-text_w)/2:y=h/2+60:fontfile={FONT_BOLD}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── BUILD FACT CLIP (varied layouts) ─────────────────────
def build_fact_clip(video_path, voice_path, number, title, fact, fmt, music_path=None):
    print(f"🎞️  Clip #{number}")
    duration   = get_duration(voice_path) + 0.5
    words = fact.split()
    lines, current = [], ""
    for word in words:
        if len(current + word) < 40:
            current += word + " "
        else:
            lines.append(current.strip())
            current = word + " "
    if current:
        lines.append(current.strip())
    safe_fact  = "\n".join(lines[:3]).replace("'","").replace('"',"")
    safe_title = title.replace("'","").replace('"',"")[:38]
    out_path   = OUTPUT_DIR / f"clip_{number}.mp4"
    temp_path  = OUTPUT_DIR / f"clip_nm_{number}.mp4"

    accent = fmt.get("accent", "yellow")
    accent_colors = {
        "red": "FF0000", "cyan": "00FFFF", "purple": "CC00FF",
        "orange": "FF6600", "green": "00FF00", "gold": "FFD700",
        "yellow": "FFD700", "blue": "0088FF", "amber": "FFBF00",
        "teal": "00CCBB", "pink": "FF69B4", "lime": "AAFF00",
    }
    color_hex = accent_colors.get(accent, "FFD700")

    # Alternate zoom direction for variety
    zoom_expr = "min(zoom+0.0008,1.3)" if number % 2 == 0 else "max(zoom-0.0005,1.0)"

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-i", voice_path,
        "-filter_complex",
        (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,"
            f"zoompan=z='{zoom_expr}':d={int(duration*25)}:s=1920x1080:fps=25,"
            f"drawbox=x=0:y=0:w=220:h=85:color=#{color_hex}:t=fill,"
            f"drawtext=text='#{number}':fontcolor=black:fontsize=56:"
            f"x=15:y=10:fontfile={FONT_BOLD},"
            f"drawbox=x=0:y=ih*0.60:w=iw:h=ih*0.40:color=black@0.80:t=fill,"
            f"drawtext=text='{safe_title}':fontcolor=#{color_hex}:fontsize=42:"
            f"x=40:y=h*0.62:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=30:"
            f"x=40:y=h*0.71:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=8[v]"
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
            "[1:a]volume=0.07[music];[0:a][music]amix=inputs=2:duration=first[aout]",
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

# ─── BUILD TEASE ──────────────────────────────────────────
def build_tease(tease_audio, fmt):
    print("🎬 Building tease...")
    duration  = get_duration(tease_audio) + 0.3
    out_path  = OUTPUT_DIR / "clip_tease.mp4"
    bg_color  = fmt.get("color", "0x1a0000")

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={bg_color}:s=1920x1080:r=25",
        "-i", tease_audio,
        "-filter_complex",
        (
            f"[0:v]"
            f"drawtext=text='The Best Is Coming...':fontcolor=white:fontsize=72:"
            f"x=(w-text_w)/2:y=h/3:fontfile={FONT_BOLD},"
            f"drawtext=text='You Won t Believe The Last One!':fontcolor=yellow:fontsize=52:"
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
def build_outro(outro_audio, fmt):
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
            f"drawtext=text='Comment Which Fact Shocked You Most!':fontcolor=orange:fontsize=36:"
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

# ─── BUILD SHORT ──────────────────────────────────────────
def build_short(video_path, voice_path, hook, fact, title):
    print("📱 Building Short...")
    duration  = get_duration(voice_path) + 0.5
    out_path  = OUTPUT_DIR / "short_final.mp4"
    safe_hook = hook.replace("'","").replace('"',"")[:40]
    words = fact.split()
    lines, current = [], ""
    for word in words:
        if len(current + word) < 32:
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
            f"drawbox=x=0:y=0:w=iw:h=190:color=black@0.85:t=fill,"
            f"drawbox=x=0:y=ih-320:w=iw:h=320:color=black@0.85:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=yellow:fontsize=48:"
            f"x=(w-text_w)/2:y=18:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_hook}':fontcolor=white:fontsize=40:"
            f"x=(w-text_w)/2:y=90:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=34:"
            f"x=40:y=h-300:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=10,"
            f"drawtext=text='FOLLOW FOR MORE! 👆':fontcolor=yellow:fontsize=40:"
            f"x=(w-text_w)/2:y=h-55:fontfile={FONT_BOLD}[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── CONCAT ───────────────────────────────────────────────
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

# ─── SEO METADATA ─────────────────────────────────────────
def save_metadata(title, script, topic, fmt, video_type, is_short=False):
    keywords = script.get("seo_keywords", [topic, "facts", "shocking"])
    kw_str   = ", ".join(keywords)

    chapters = ""
    if not is_short:
        chapters = "\n\n📌 CHAPTERS:\n00:00 Introduction\n"
        for i, fact in enumerate(script.get("facts", []), 1):
            mins = i * 45
            chapters += f"{mins//60:02d}:{mins%60:02d} - {fact.get('title','Fact '+str(i))}\n"

    description = script.get("description", f"Shocking facts about {topic}")
    full_desc = (
        f"🤯 {title}\n\n"
        f"{description}\n\n"
        f"Keywords: {kw_str}\n"
        f"{chapters}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 SUBSCRIBE for daily mind-blowing content!\n"
        f"👍 LIKE if this shocked you!\n"
        f"💬 COMMENT which fact surprised you most!\n"
        f"📤 SHARE with someone who needs to see this!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"#MindBlownFacts #Facts #DidYouKnow "
        f"#{topic.replace(' ','')} #Shocking #Viral #Educational"
    )

    tags = script.get("tags", [])
    tags += ["mindblownfacts","facts","didyouknow","shocking","viral",
             "educational", topic.lower().replace(" ",""),
             fmt["style"], "mindblown","unbelievable"]
    tags = list(dict.fromkeys(tags))[:30]  # Remove duplicates

    metadata = {
        "title":       title,
        "description": full_desc,
        "tags":        tags,
        "topic":       topic,
        "format":      fmt["id"],
        "video_type":  video_type,
        "is_short":    is_short,
    }
    fname = "metadata_short.json" if is_short else "metadata.json"
    with open(OUTPUT_DIR / fname, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✅ SEO Metadata saved!")
    return metadata

# ─── GET VIDEO TYPE ───────────────────────────────────────
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

# ═══════════════════════════════════════════════════════════
# MAKE SHORT
# ═══════════════════════════════════════════════════════════
def make_short():
    print("\n📱 MAKING SHORT\n" + "="*50)
    history = load_history()
    topic   = get_trending_topic()
    script  = generate_short_script(topic)
    fmt     = random.choice(VIDEO_FORMATS)

    full_text = f"{script['hook']} {script['fact']} {script['calltoaction']}"
    voice     = generate_voice(full_text, "short")
    video     = download_video(script["search_query"], "short")
    final     = build_short(video, voice, script["hook"],
                            script["fact"], script["title"])

    tags = script.get("tags", []) + ["Shorts","YouTubeShorts","mindblown"]
    save_metadata(script["title"], script, topic, fmt, "short", is_short=True)
    save_history(history)
    print(f"\n✅ SHORT DONE!")
    return final

# ═══════════════════════════════════════════════════════════
# MAKE VIDEO
# ═══════════════════════════════════════════════════════════
def make_video(video_num=1):
    print(f"\n🎬 MAKING VIDEO {video_num}\n" + "="*50)
    history       = load_history()
    fmt, history  = pick_format(history)
    topic, title, history = pick_topic(fmt, history)

    print(f"📌 Format : {fmt['id']}")
    print(f"📌 Topic  : {topic}")
    print(f"📌 Title  : {title}")

    script      = generate_script(topic, title, fmt)
    music       = download_music()
    hook_audio  = generate_voice(script["hook"], "hook")
    tease_audio = generate_voice(script["midpoint_tease"], "tease")
    outro_audio = generate_voice(script["outro"], "outro")
    fact_audios = [generate_voice(f["fact"], f["number"]) for f in script["facts"]]
    fact_videos = [download_video(f["search_query"], f["number"]) for f in script["facts"]]

    intro_clip = build_intro(title, hook_audio, fact_videos[0], fmt)
    fact_clips = []
    for i, fact in enumerate(script["facts"]):
        clip = build_fact_clip(fact_videos[i], fact_audios[i],
                               fact["number"], fact["title"],
                               fact["fact"], fmt, music)
        fact_clips.append(clip)
        if i == len(script["facts"]) // 2:
            fact_clips.append(build_tease(tease_audio, fmt))

    outro_clip = build_outro(outro_audio, fmt)
    all_clips  = [intro_clip] + fact_clips + [outro_clip]
    fname      = f"final_video_{video_num}.mp4"
    final      = concat_clips(all_clips, fname)

    make_thumbnail(title, topic, fmt)
    save_metadata(title, script, topic, fmt, f"video{video_num}")
    save_history(history)

    print(f"\n✅ VIDEO {video_num} DONE!")
    return final

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    vtype = get_video_type()
    print(f"\n🎯 Type: {vtype} | UTC: {datetime.utcnow().hour}:00")
    if vtype == "short":
        make_short()
    elif vtype == "video2":
        make_video(2)
    else:
        make_video(1)
    print("\n🎉 ALL DONE!")

if __name__ == "__main__":
    main()