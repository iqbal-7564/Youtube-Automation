import os
import json
import random
import requests
import subprocess
import asyncio
import re
import shutil
from pathlib import Path
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────
GROQ_API_KEY_1     = os.environ.get("GROQ_API_KEY_1")
GROQ_API_KEY_2     = os.environ.get("GROQ_API_KEY_2")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY    = os.environ.get("PIXABAY_API_KEY")

VOICE_ID     = "21m00Tcm4TlvDq8ikWAM"
OUTPUT_DIR   = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
FONT_BOLD    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG     = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# PERSISTENT history - stored in repo root not output dir
HISTORY_FILE = Path("format_history.json")
MAX_TITLE    = 95
MAX_VOICE    = 380

# ─── DEFICIENCY FIXES ─────────────────────────────────────
# FIX 1: zoompan removed - too slow, causes timeout
# FIX 2: fade integrated into clip build - not separate pass
# FIX 3: history stored persistently in repo
# FIX 4: teaser montage added - first 15 sec
# FIX 5: no intro logo - content from second 0
# FIX 6: better hook script prompt
# FIX 7: sound effects added
# FIX 8: music fallback improved
# FIX 9: chunk voice text properly
# FIX 10: validate all files before use

# ─── CLEANUP ──────────────────────────────────────────────
def cleanup_temp():
    print("🧹 Cleaning temp files...")
    patterns = [
        "clip_nm_*.mp4","clip_raw_*.mp4","voice_*.mp3",
        "clips_list.txt","voice_test.mp3","thumb_bg.jpg",
        "clip_*.mp4","music.mp3","sfx_*.mp3","teaser_*.mp4",
        "*_chunk_*.mp3","*_list.txt"
    ]
    for p in patterns:
        for f in OUTPUT_DIR.glob(p):
            try: f.unlink()
            except: pass

# ─── HISTORY (persistent in repo) ─────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except: pass
    return {"used_formats":[], "used_topics":[]}

def save_history(h):
    with open(HISTORY_FILE, "w") as f:
        json.dump(h, f, indent=2)

# ─── 20 UNIQUE VIDEO FORMATS ──────────────────────────────
VIDEO_FORMATS = [
    {"id":"shocking_truth",    "title":"{topic} - The Shocking Truth Nobody Talks About",       "color":"0x1a0000","accent":"FF3300","style":"investigative"},
    {"id":"science_explained", "title":"Scientists Finally Explained {topic} And Its Insane",    "color":"0x001a2e","accent":"00CCFF","style":"science"},
    {"id":"dark_history",      "title":"The Dark History of {topic} They Never Taught You",     "color":"0x1a1000","accent":"FF8800","style":"history"},
    {"id":"secrets_exposed",   "title":"{topic} Secrets Experts Kept Hidden For Years",         "color":"0x1a0010","accent":"FF44AA","style":"exposed"},
    {"id":"incredible_story",  "title":"The Incredible True Story of {topic}",                  "color":"0x0a0a00","accent":"FFD700","style":"story"},
    {"id":"record_breakers",   "title":"{topic} Records That Seem Impossible But Are Real",     "color":"0x001010","accent":"00FFCC","style":"records"},
    {"id":"why_nobody_knows",  "title":"Why Nobody Talks About {topic} This Will Shock You",    "color":"0x100010","accent":"CC88FF","style":"mystery"},
    {"id":"future_reveal",     "title":"What {topic} Will Look Like in 2050 Experts Reveal",    "color":"0x000d1a","accent":"4499FF","style":"future"},
    {"id":"biggest_myths",     "title":"Biggest Lies About {topic} That Everyone Believes",     "color":"0x1a0a00","accent":"FFAA00","style":"myths"},
    {"id":"survival_facts",    "title":"{topic} Facts That Could Actually Save Your Life",      "color":"0x001a0a","accent":"88FF44","style":"survival"},
    {"id":"mind_control",      "title":"How {topic} Is Secretly Controlling Your Brain",        "color":"0x0d001a","accent":"9944FF","style":"psychology"},
    {"id":"money_secrets",     "title":"{topic} Money Secrets The Rich Hide From You",          "color":"0x001500","accent":"FFD700","style":"money"},
    {"id":"extreme_events",    "title":"Most Extreme {topic} Events Ever Recorded on Earth",    "color":"0x1a0500","accent":"FF4400","style":"extreme"},
    {"id":"genius_facts",      "title":"{topic} Facts That Only Geniuses Know",                 "color":"0x00101a","accent":"00BBFF","style":"genius"},
    {"id":"real_truth",        "title":"The Real Truth Behind {topic} Finally Revealed",        "color":"0x0f0f0f","accent":"CCCCCC","style":"reveal"},
    {"id":"country_secrets",   "title":"Why {topic} Is The Most Surprising Place on Earth",     "color":"0x001510","accent":"44FF88","style":"country"},
    {"id":"animal_bizarre",    "title":"Most Bizarre {topic} Behaviors That Shock Scientists",  "color":"0x0a1500","accent":"AAFF22","style":"animals"},
    {"id":"ancient_mystery",   "title":"Ancient {topic} Mysteries That Science Cannot Explain", "color":"0x150a00","accent":"FFAA44","style":"ancient"},
    {"id":"what_if",           "title":"What If {topic} Disappeared Tomorrow",                  "color":"0x000a1a","accent":"44AAFF","style":"hypothetical"},
    {"id":"comparison",        "title":"The Shocking Difference Between {topic} and {topic2}",  "color":"0x001a00","accent":"44FF44","style":"comparison"},
]

# ─── TOPICS ───────────────────────────────────────────────
TOPICS = {
    "science":    ["Human Brain","DNA","Black Holes","Quantum Physics","Deep Ocean","Volcanoes","Time","Gravity","Sound","Light"],
    "history":    ["Ancient Egypt","Roman Empire","Vikings","Ancient China","Ottoman Empire","Cold War","Medieval Times","Ancient Greece","Aztec Empire","Mongol Empire"],
    "animals":    ["Sharks","Octopus","Wolves","Eagles","Elephants","Dolphins","Crocodiles","Gorillas","Mantis Shrimp","Komodo Dragons"],
    "countries":  ["Japan","Norway","Iceland","Singapore","Switzerland","New Zealand","Finland","South Korea","Netherlands","Monaco"],
    "technology": ["Artificial Intelligence","Internet","Nuclear Energy","Space Rockets","Electric Cars","Quantum Computers","Solar Power","Robots","5G","Nanotechnology"],
    "nature":     ["Amazon Rainforest","Sahara Desert","Mariana Trench","Mount Everest","Northern Lights","Great Barrier Reef","Grand Canyon","Dead Sea","Antarctica","Bermuda Triangle"],
    "money":      ["Bitcoin","Gold","Real Estate","Stock Market","Oil Industry","Diamond Industry","Luxury Brands","Banks","Federal Reserve","Wall Street"],
    "psychology": ["Dreams","Memory","Fear","Addiction","Love","Anger","Happiness","Intelligence","Creativity","Persuasion"],
    "food":       ["Honey","Coffee","Salt","Sugar","Chocolate","Cheese","Bread","Rice","Spices","Water"],
    "space":      ["Mars","Saturn","Jupiter","Sun","Moon","Asteroids","Galaxies","Dark Matter","Exoplanets","Black Holes"],
}

VS_PAIRS = [
    ("Amazon","Sahara"),("Sun","Moon"),("Einstein","Newton"),
    ("Ancient Egypt","Ancient Rome"),("Sharks","Crocodiles"),
    ("Mars","Venus"),("Tigers","Lions"),("Ocean","Space"),
    ("Ancient Greeks","Vikings"),("Gold","Bitcoin"),
]

# ─── HELPERS ──────────────────────────────────────────────
def safe_text(text, limit=40):
    text = str(text)
    text = text.replace("'","").replace('"',"").replace(":","").replace("&","and")
    text = re.sub(r'[^\w\s\-!?.,]','',text)
    return text[:limit].strip()

def fix_title(title, topic=""):
    title = str(title).replace("'","").replace('"',"")
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE-3].rsplit(" ",1)[0] + "..."
    return title

def chunk_text(text, max_chars=MAX_VOICE):
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, cur = [], ""
    for s in sentences:
        if len(cur)+len(s) < max_chars:
            cur += s + " "
        else:
            if cur: chunks.append(cur.strip())
            cur = s + " "
    if cur: chunks.append(cur.strip())
    return chunks or [text[:max_chars]]

def validate_file(path, min_size=1000):
    try:
        return os.path.exists(str(path)) and os.path.getsize(str(path)) > min_size
    except:
        return False

# ─── TRENDING ─────────────────────────────────────────────
BAD_WORDS = ["killed","dead","murder","war","attack","crash","died",
             "shooting","bomb","terror","arrested","disaster","death"]

def is_safe_topic(text):
    return not any(b in text.lower() for b in BAD_WORDS)

def get_trending_topic():
    print("🔥 Finding trending...")
    trending = []
    try:
        r = requests.get(
            "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
            timeout=10, headers={"User-Agent":"Mozilla/5.0"}
        )
        if r.status_code == 200:
            titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
            safe   = [t for t in titles if len(t)>4 and 'Trending' not in t and is_safe_topic(t)]
            trending.extend(safe[:5])
    except: pass
    if trending:
        t = random.choice(trending)
        print(f"🔥 Trending: {t}")
        return t
    cat   = random.choice(list(TOPICS.keys()))
    topic = random.choice(TOPICS[cat])
    print(f"📌 Fallback: {topic}")
    return topic

# ─── FORMAT & TOPIC PICKER ────────────────────────────────
def pick_format(history):
    used  = history.get("used_formats",[])
    avail = [f for f in VIDEO_FORMATS if f["id"] not in used[-8:]]
    if not avail: avail = VIDEO_FORMATS
    fmt  = random.choice(avail)
    used.append(fmt["id"])
    history["used_formats"] = used[-20:]
    return fmt, history

def pick_topic(fmt, history):
    used = history.get("used_topics",[])
    if fmt["id"] == "comparison":
        pair   = random.choice(VS_PAIRS)
        topic  = pair[0]; topic2 = pair[1]
        title  = fmt["title"].replace("{topic}",topic).replace("{topic2}",topic2)
    else:
        if random.random() < 0.35:
            topic = get_trending_topic()
        else:
            cat   = random.choice(list(TOPICS.keys()))
            avail = [t for t in TOPICS[cat] if t not in used[-15:]]
            topic = random.choice(avail if avail else TOPICS[cat])
        title = fmt["title"].replace("{topic}",topic).replace("{topic2}","")
    title = fix_title(title, topic)
    used.append(topic)
    history["used_topics"] = used[-30:]
    return topic, title, history

# ─── EDGE TTS ─────────────────────────────────────────────
async def edge_tts_generate(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(
        text[:MAX_VOICE],
        "en-US-ChristopherNeural",
        rate="+8%", volume="+10%"
    )
    await communicate.save(out_path)

def detect_voice_engine():
    print("🎙️ Testing voice...")
    try:
        test = str(OUTPUT_DIR/"voice_test.mp3")
        asyncio.run(edge_tts_generate("test", test))
        if validate_file(test, 500):
            print("✅ Edge TTS")
            return "edge"
    except Exception as e:
        print(f"Edge: {e}")
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
            headers={"xi-api-key":ELEVENLABS_API_KEY,"Content-Type":"application/json"},
            json={"text":"test","model_id":"eleven_monolingual_v1",
                  "voice_settings":{"stability":0.5,"similarity_boost":0.75}},
            timeout=10,
        )
        if len(r.content) > 500:
            print("✅ ElevenLabs")
            return "elevenlabs"
    except: pass
    print("✅ gTTS")
    return "gtts"

VOICE_ENGINE = detect_voice_engine()

# ─── GROQ ─────────────────────────────────────────────────
def call_groq(prompt):
    keys = [k for k in [GROQ_API_KEY_1, GROQ_API_KEY_2] if k]
    for key in keys:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"model":"llama-3.3-70b-versatile",
                      "messages":[{"role":"user","content":prompt}],
                      "temperature":0.9,"max_tokens":2500},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Groq: {e}")
    raise Exception("Groq failed!")

def clean_json(text):
    text = text.strip()
    if "```" in text:
        for p in text.split("```"):
            p = p[4:] if p.startswith("json") else p
            if p.strip().startswith("{"):
                text = p.strip(); break
    s = text.find("{"); e = text.rfind("}")+1
    if s >= 0 and e > s: text = text[s:e]
    text = re.sub(r',\s*}','}',text)
    text = re.sub(r',\s*]',']',text)
    text = re.sub(r'[\x00-\x1f\x7f]',' ',text)
    return text.strip()

# ─── SCRIPTS ──────────────────────────────────────────────
def generate_script(topic, title, fmt):
    print(f"✍️  Script: {title[:55]}...")

    # FIX: Better hook prompt - no welcome, immediate shock
    prompt = f"""Write YouTube video script titled "{title}" about "{topic}".
Style: {fmt['style']}

CRITICAL RULES:
- Hook must start with SHOCKING statement immediately - NO welcome, NO intro
- Hook must make viewer NEED to watch till end
- Each fact title max 30 chars
- Each fact text max 120 chars
- All facts TRUE and verifiable

Return ONLY valid JSON:
{{
  "title": "{title}",
  "hook": "START WITH SHOCK: One sentence that makes viewer freeze. Then: This is just fact 8. Wait till you hear fact 1.",
  "facts": [
    {{"number":1,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":2,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":3,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":4,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":5,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":6,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":7,"title":"30 char title","fact":"Shocking fact 2-3 sentences 120 chars max","search_query":"2 words"}},
    {{"number":8,"title":"Most shocking","fact":"Most shocking fact 3 sentences 150 chars max","search_query":"2 words"}}
  ],
  "midpoint_tease": "ONE sentence: The next fact will completely change how you see {topic} forever.",
  "outro": "Subscribe MindBlownFacts for daily shocking facts! Which fact shocked you most?",
  "description": "120 word SEO description about {topic}",
  "seo_keywords": ["keyword1","keyword2","keyword3","keyword4","keyword5"],
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10","tag11","tag12","tag13","tag14","tag15"]
}}
Return ONLY JSON"""

    for attempt in range(3):
        try:
            result = json.loads(clean_json(call_groq(prompt)))
            if "facts" in result and len(result["facts"]) >= 6:
                return result
        except Exception as e:
            print(f"Script attempt {attempt+1}: {e}")

    # Fallback
    return {
        "title": title,
        "hook": f"This {topic} fact will completely change how you see the world. And fact number 1 is even more shocking.",
        "facts": [{"number":i+1,"title":f"Fact {i+1}","fact":f"Scientists discovered that {topic} has properties that completely defy human understanding and change everything we know.","search_query":topic.split()[0].lower()} for i in range(8)],
        "midpoint_tease": f"The next fact about {topic} will completely change how you see the world.",
        "outro": "Subscribe MindBlownFacts for daily shocking facts!",
        "description": f"Shocking facts about {topic} that will blow your mind.",
        "seo_keywords": [topic,"facts","shocking","mindblown","viral"],
        "tags": ["facts","mindblownfacts","shocking","viral","educational",topic.lower().replace(" ","")]
    }

def generate_short_script(topic):
    print(f"✍️  Short: {topic}")
    prompt = f"""Write viral 60-second YouTube Shorts script about "{topic}".
CRITICAL: First sentence must be the most shocking thing ever heard about {topic}.
Return ONLY valid JSON:
{{
  "title": "Max 60 char shocking title",
  "hook": "MOST SHOCKING 1 sentence about {topic} - no intro just shock",
  "fact": "Shocking fact 4 sentences max 300 chars",
  "calltoaction": "Follow MindBlownFacts for daily shocking facts!",
  "search_query": "2 words",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"]
}}
Return ONLY JSON"""
    for attempt in range(3):
        try:
            result = json.loads(clean_json(call_groq(prompt)))
            if "hook" in result:
                result["title"] = fix_title(result.get("title",f"Shocking {topic} Facts"))
                return result
        except Exception as e:
            print(f"Short {attempt+1}: {e}")
    return {
        "title": fix_title(f"Shocking {topic} Facts"),
        "hook":  f"Scientists just discovered something about {topic} that changes everything!",
        "fact":  f"Recent research revealed that {topic} has properties nobody expected. This discovery shocked the entire scientific community.",
        "calltoaction": "Follow MindBlownFacts for daily shocking facts!",
        "search_query": topic.split()[0].lower(),
        "tags": ["facts","shorts","mindblownfacts","shocking","viral"]
    }

# ─── VOICE ────────────────────────────────────────────────
def generate_voice_single(text, out_path):
    text = text[:MAX_VOICE]
    if VOICE_ENGINE == "edge":
        try:
            asyncio.run(edge_tts_generate(text, out_path))
            if validate_file(out_path, 500): return True
        except: pass
    if VOICE_ENGINE in ("edge","elevenlabs"):
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
                headers={"xi-api-key":ELEVENLABS_API_KEY,"Content-Type":"application/json"},
                json={"text":text,"model_id":"eleven_monolingual_v1",
                      "voice_settings":{"stability":0.5,"similarity_boost":0.75}},
                timeout=30,
            )
            if len(r.content) > 1000:
                with open(out_path,"wb") as f: f.write(r.content)
                return True
        except: pass
    try:
        from gtts import gTTS
        gTTS(text=text, lang='en', slow=False).save(out_path)
        return True
    except: pass
    # Silent fallback
    subprocess.run(["ffmpeg","-y","-f","lavfi",
                   "-i","anullsrc=r=44100:cl=mono",
                   "-t","3","-q:a","9","-acodec","libmp3lame",out_path],
                   capture_output=True)
    return False

def generate_voice(text, index):
    print(f"🎙️ Voice: {index}")
    out_path = str(OUTPUT_DIR / f"voice_{index}.mp3")
    chunks   = chunk_text(text, MAX_VOICE)
    if len(chunks) == 1:
        generate_voice_single(chunks[0], out_path)
        return out_path

    chunk_files = []
    for i, chunk in enumerate(chunks):
        cp = str(OUTPUT_DIR / f"voice_{index}_c{i}.mp3")
        generate_voice_single(chunk, cp)
        chunk_files.append(cp)

    lf = str(OUTPUT_DIR / f"voice_{index}_list.txt")
    with open(lf,"w") as f:
        for cf in chunk_files:
            f.write(f"file '{os.path.abspath(cf)}'\n")
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0",
                   "-i",lf,"-c","copy",out_path], capture_output=True)
    for cf in chunk_files + [lf]:
        try: os.unlink(cf)
        except: pass
    return out_path

# ─── DURATION ─────────────────────────────────────────────
def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(path)],
            capture_output=True, text=True,
        )
        val = r.stdout.strip()
        return float(val) if val else 3.0
    except:
        return 3.0

# ─── SOUND EFFECTS ────────────────────────────────────────
def make_whoosh():
    """Generate whoosh sound effect with ffmpeg"""
    out = str(OUTPUT_DIR / "sfx_whoosh.mp3")
    subprocess.run([
        "ffmpeg","-y","-f","lavfi",
        "-i","aevalsrc=0.4*exp(-t*3)*sin(2*PI*(400+t*(-300))*t):s=44100",
        "-t","0.5",out
    ], capture_output=True)
    return out if validate_file(out) else None

def make_impact():
    """Generate impact sound effect"""
    out = str(OUTPUT_DIR / "sfx_impact.mp3")
    subprocess.run([
        "ffmpeg","-y","-f","lavfi",
        "-i","aevalsrc=0.5*exp(-t*8)*sin(2*PI*80*t):s=44100",
        "-t","0.3",out
    ], capture_output=True)
    return out if validate_file(out) else None

# ─── VIDEO DOWNLOAD ───────────────────────────────────────
def download_video(query, index, retries=3):
    print(f"🎬 Video: {query}")
    out_path = OUTPUT_DIR / f"clip_raw_{index}.mp4"
    queries  = [query, query.split()[0] if " " in query else query, "nature", "landscape"]

    for q in queries[:retries+1]:
        url = None
        try:
            r = requests.get(
                f"https://api.pexels.com/videos/search?query={q}&per_page=15&orientation=landscape",
                headers={"Authorization":PEXELS_API_KEY}, timeout=15
            )
            videos = r.json().get("videos",[])
            if videos:
                video = random.choice(videos[:8])
                files = sorted(video["video_files"], key=lambda x:x.get("width",0))
                url   = next((f["link"] for f in files if f.get("width",0)>=1280),
                             files[-1]["link"] if files else None)
        except: pass

        if not url:
            try:
                r = requests.get(
                    f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={q}&per_page=10",
                    timeout=15
                )
                hits = r.json().get("hits",[])
                if hits:
                    v = random.choice(hits[:5]).get("videos",{})
                    c = v.get("large") or v.get("medium") or v.get("small")
                    if c: url = c["url"]
            except: pass

        if url:
            try:
                r = requests.get(url, stream=True, timeout=60)
                with open(out_path,"wb") as f:
                    for chunk in r.iter_content(8192): f.write(chunk)
                if validate_file(str(out_path), 10000):
                    return str(out_path)
            except: pass

    # Black fallback
    subprocess.run([
        "ffmpeg","-y","-f","lavfi","-i","color=c=black:s=1920x1080:r=25",
        "-t","15","-c:v","libx264",str(out_path)
    ], capture_output=True)
    return str(out_path)

# ─── THUMBNAIL IMAGE ──────────────────────────────────────
def download_thumb_image(topic):
    out_path = OUTPUT_DIR / "thumb_bg.jpg"
    for q in [topic, topic.split()[0], "dramatic nature landscape"]:
        try:
            r = requests.get(
                f"https://api.pexels.com/v1/search?query={q}&per_page=15&orientation=landscape",
                headers={"Authorization":PEXELS_API_KEY}, timeout=15
            )
            photos = r.json().get("photos",[])
            if photos:
                photo = random.choice(photos[:8])
                ir    = requests.get(photo["src"]["large"], timeout=30)
                with open(out_path,"wb") as f: f.write(ir.content)
                if validate_file(str(out_path), 5000):
                    return str(out_path)
        except: pass
    return None

# ─── MUSIC ────────────────────────────────────────────────
def download_music():
    print("🎵 Music...")
    music_path = OUTPUT_DIR / "music.mp3"
    moods = ["cinematic","inspiring","dramatic","epic","mysterious","ambient","tension"]
    mood  = random.choice(moods)

    # Try Pixabay music API
    try:
        r = requests.get(
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={mood}&media_type=music&per_page=15",
            timeout=15
        )
        hits = r.json().get("hits",[])
        random.shuffle(hits)
        for hit in hits[:8]:
            for field in ["audio","audioUrl","previewURL","pageURL"]:
                audio_url = hit.get(field)
                if isinstance(audio_url, dict):
                    audio_url = audio_url.get("url") or audio_url.get("mp3")
                if audio_url and audio_url.startswith("http"):
                    try:
                        mr = requests.get(audio_url, timeout=30)
                        if len(mr.content) > 10000:
                            with open(music_path,"wb") as f: f.write(mr.content)
                            print(f"✅ Music: {mood}")
                            return str(music_path)
                    except: pass
    except Exception as e:
        print(f"Music API: {e}")

    # Generate ambient music with ffmpeg
    # Soft cinematic tone
    subprocess.run([
        "ffmpeg","-y","-f","lavfi",
        "-i","aevalsrc=0.03*sin(220*2*PI*t)+0.02*sin(330*2*PI*t)+0.01*sin(440*2*PI*t):s=44100",
        "-t","600",str(music_path)
    ], capture_output=True)
    return str(music_path)

# ─────────────────────────────────────────────────────────
# BUILD VIDEO CLIPS (NO zoompan - FAST!)
# FIX: Removed zoompan - was causing 60+ min timeouts!
# Using scale+crop for slight zoom effect (instant processing)
# ─────────────────────────────────────────────────────────

def build_scale_filter(width=1920, height=1080, zoom=1.05):
    """Fast zoom alternative to zoompan"""
    w = int(width * zoom)
    h = int(height * zoom)
    x = (w - width) // 2
    y = (h - height) // 2
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={width}:{height}:{x}:{y}"

# ─── TEASER MONTAGE (FIX: no boring intro!) ───────────────
def build_teaser(fact_videos, hook_audio, title, fmt):
    """
    FIX: First 15 seconds = quick preview of ALL facts
    People see exciting content immediately!
    No more logo - content from second ZERO!
    """
    print("🎬 Building teaser montage...")
    color_hex  = fmt.get("accent","FFD700")
    safe_title = safe_text(title, 48)
    hook_dur   = get_duration(hook_audio)
    clip_dur   = max(1.5, hook_dur / max(len(fact_videos), 1))
    clip_dur   = min(clip_dur, 2.5)  # Max 2.5 sec per preview clip

    # Build each preview clip
    preview_clips = []
    for i, vpath in enumerate(fact_videos[:6]):  # Use first 6 videos
        pc = OUTPUT_DIR / f"teaser_{i}.mp4"
        # Fast cut from random point in video
        skip = random.uniform(2, 8)
        cmd = [
            "ffmpeg","-y",
            "-ss",str(skip),"-i",vpath,
            "-vf",(
                f"{build_scale_filter()},"
                f"drawbox=x=0:y=ih*0.75:w=iw:h=ih*0.25:color=black@0.7:t=fill,"
                f"drawtext=text='Fact {i+1}':fontcolor=#{color_hex}:fontsize=52:"
                f"x=(w-text_w)/2:y=h*0.77:fontfile={FONT_BOLD}:"
                f"shadowcolor=black:shadowx=2:shadowy=2"
            ),
            "-t",str(clip_dur),
            "-r","25","-c:v","libx264","-preset","ultrafast",
            "-an",str(pc)
        ]
        subprocess.run(cmd, capture_output=True)
        if validate_file(str(pc), 1000):
            preview_clips.append(str(pc))

    if not preview_clips:
        # Fallback - use first video
        preview_clips = [fact_videos[0]] if fact_videos else []

    # Concat preview clips
    teaser_video = OUTPUT_DIR / "teaser_video.mp4"
    if len(preview_clips) > 1:
        lf = OUTPUT_DIR / "teaser_list.txt"
        with open(lf,"w") as f:
            for pc in preview_clips:
                f.write(f"file '{os.path.abspath(pc)}'\n")
        subprocess.run([
            "ffmpeg","-y","-f","concat","-safe","0",
            "-i",str(lf),"-c:v","libx264","-preset","fast",
            "-an",str(teaser_video)
        ], capture_output=True)
    else:
        shutil.copy(preview_clips[0], str(teaser_video))

    # Add hook audio + title overlay on teaser
    out_path = OUTPUT_DIR / "clip_intro.mp4"
    total_dur = get_duration(str(teaser_video))
    hook_dur  = min(get_duration(hook_audio), total_dur)

    cmd = [
        "ffmpeg","-y",
        "-stream_loop","-1","-i",str(teaser_video),
        "-i",hook_audio,
        "-filter_complex",
        (
            f"[0:v]"
            f"drawbox=x=0:y=0:w=iw:h=120:color=black@0.85:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=48:"
            f"x=(w-text_w)/2:y=15:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_title}':fontcolor=white:fontsize=40:"
            f"x=(w-text_w)/2:y=68:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2"
            f"[v]"
        ),
        "-map","[v]","-map","1:a",
        "-t",str(hook_dur + 0.3),
        "-c:v","libx264","-preset","fast",
        "-c:a","aac","-shortest",
        str(out_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Cleanup teaser temp files
    for pc in preview_clips:
        try: Path(pc).unlink()
        except: pass
    try: Path(str(teaser_video)).unlink()
    except: pass

    return str(out_path)

# ─── BUILD FACT CLIP (FAST - no zoompan) ──────────────────
def build_fact_clip(video_path, voice_path, number, title, fact, fmt, music_path=None, whoosh=None):
    print(f"🎞️  Clip #{number}")
    duration   = get_duration(voice_path) + 0.3
    color_hex  = fmt.get("accent","FFD700")
    safe_title = safe_text(title, 34)

    words = fact.split()
    lines, cur = [], ""
    for word in words:
        if len(cur+word) < 43: cur += word+" "
        else: lines.append(cur.strip()); cur = word+" "
    if cur: lines.append(cur.strip())
    safe_fact = "\n".join(lines[:3]).replace("'","").replace('"',"")

    # Alternate: some clips zoom in, some zoom out (visual variety)
    if number % 3 == 0:
        scale_f = build_scale_filter(zoom=1.08)
    elif number % 3 == 1:
        scale_f = build_scale_filter(zoom=1.0)
    else:
        scale_f = build_scale_filter(zoom=1.05)

    temp_path = OUTPUT_DIR / f"clip_nm_{number}.mp4"
    out_path  = OUTPUT_DIR / f"clip_{number}.mp4"

    # FIX: Fade integrated into one pass (not separate)
    fade_out  = max(0, duration - 0.4)
    vf = (
        f"[0:v]{scale_f},"
        f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out:.2f}:d=0.3,"
        f"drawbox=x=0:y=0:w=200:h=78:color=#{color_hex}:t=fill,"
        f"drawtext=text='#{number}':fontcolor=black:fontsize=52:"
        f"x=14:y=8:fontfile={FONT_BOLD},"
        f"drawbox=x=0:y=ih*0.60:w=iw:h=ih*0.40:color=black@0.82:t=fill,"
        f"drawtext=text='{safe_title}':fontcolor=#{color_hex}:fontsize=38:"
        f"x=38:y=h*0.62:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
        f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=28:"
        f"x=38:y=h*0.70:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=8"
        f"[v]"
    )
    af = (
        f"[1:a]afade=t=in:st=0:d=0.3,afade=t=out:st={fade_out:.2f}:d=0.3[a]"
    )

    # Add whoosh sound effect at start
    if whoosh and validate_file(whoosh):
        cmd = [
            "ffmpeg","-y",
            "-stream_loop","-1","-i",video_path,
            "-i",voice_path,
            "-i",whoosh,
            "-filter_complex",
            f"{vf};{af};"
            f"[2:a]volume=0.3[sfx];"
            f"[a][sfx]amix=inputs=2:duration=first[aout]",
            "-map","[v]","-map","[aout]",
            "-t",str(duration),
            "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
            str(temp_path)
        ]
    else:
        cmd = [
            "ffmpeg","-y",
            "-stream_loop","-1","-i",video_path,
            "-i",voice_path,
            "-filter_complex",
            f"{vf};{af}",
            "-map","[v]","-map","[a]",
            "-t",str(duration),
            "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
            str(temp_path)
        ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Simplified fallback without effects
        subprocess.run([
            "ffmpeg","-y",
            "-stream_loop","-1","-i",video_path,
            "-i",voice_path,
            "-vf",f"{scale_f}",
            "-map","0:v","-map","1:a",
            "-t",str(duration),
            "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
            str(temp_path)
        ], capture_output=True)

    # Add background music
    if music_path and validate_file(music_path, 1000):
        cmd2 = [
            "ffmpeg","-y",
            "-i",str(temp_path),"-i",music_path,
            "-filter_complex",
            "[1:a]volume=0.06[music];[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map","0:v","-map","[aout]",
            "-c:v","copy","-c:a","aac",str(out_path),
        ]
        r = subprocess.run(cmd2, capture_output=True)
        if r.returncode != 0:
            shutil.copy(str(temp_path), str(out_path))
    else:
        shutil.copy(str(temp_path), str(out_path))

    return str(out_path)

# ─── BUILD TEASE ──────────────────────────────────────────
def build_tease(tease_audio, fmt, video_path=None):
    print("🎬 Tease...")
    duration  = get_duration(tease_audio) + 0.2
    out_path  = OUTPUT_DIR / "clip_tease.mp4"
    color_hex = fmt.get("accent","FFD700")

    if video_path and validate_file(video_path):
        cmd = [
            "ffmpeg","-y",
            "-stream_loop","-1","-i",video_path,
            "-i",tease_audio,
            "-filter_complex",
            (
                f"[0:v]{build_scale_filter()},"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.70:t=fill,"
                f"drawtext=text='The Best Is Still Coming...':fontcolor=white:fontsize=65:"
                f"x=(w-text_w)/2:y=h/3:fontfile={FONT_BOLD},"
                f"drawtext=text='Wait For Fact Number 1!':fontcolor=#{color_hex}:fontsize=50:"
                f"x=(w-text_w)/2:y=h/2:fontfile={FONT_BOLD}[v]"
            ),
            "-map","[v]","-map","1:a",
            "-t",str(duration),
            "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
            str(out_path)
        ]
    else:
        bg  = fmt.get("color","0x1a0000")
        cmd = [
            "ffmpeg","-y",
            "-f","lavfi","-i",f"color=c={bg}:s=1920x1080:r=25",
            "-i",tease_audio,
            "-filter_complex",
            (
                f"[0:v]"
                f"drawtext=text='The Best Is Still Coming...':fontcolor=white:fontsize=68:"
                f"x=(w-text_w)/2:y=h/3:fontfile={FONT_BOLD},"
                f"drawtext=text='Wait For Fact Number 1!':fontcolor=#{color_hex}:fontsize=52:"
                f"x=(w-text_w)/2:y=h/2:fontfile={FONT_BOLD}[v]"
            ),
            "-map","[v]","-map","1:a",
            "-t",str(duration),
            "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
            str(out_path)
        ]
    subprocess.run(cmd, capture_output=True)
    return str(out_path)

# ─── BUILD OUTRO ──────────────────────────────────────────
def build_outro(outro_audio, fmt):
    print("🎬 Outro...")
    duration  = get_duration(outro_audio) + 0.5
    out_path  = OUTPUT_DIR / "clip_outro.mp4"
    color_hex = fmt.get("accent","FFD700")
    cmd = [
        "ffmpeg","-y",
        "-f","lavfi","-i","color=c=0x0a0a0a:s=1920x1080:r=25",
        "-i",outro_audio,
        "-filter_complex",
        (
            f"[0:v]"
            f"drawtext=text='SUBSCRIBE':fontcolor=red:fontsize=110:"
            f"x=(w-text_w)/2:y=h/5:fontfile={FONT_BOLD},"
            f"drawtext=text='@MindBlownFacts':fontcolor=#{color_hex}:fontsize=62:"
            f"x=(w-text_w)/2:y=h/2-28:fontfile={FONT_BOLD},"
            f"drawtext=text='New Videos Every Day!':fontcolor=white:fontsize=44:"
            f"x=(w-text_w)/2:y=h/2+60:fontfile={FONT_REG},"
            f"drawtext=text='Comment Which Fact Shocked You Most!':fontcolor=orange:fontsize=36:"
            f"x=(w-text_w)/2:y=h*0.75:fontfile={FONT_REG}[v]"
        ),
        "-map","[v]","-map","1:a",
        "-t",str(duration),
        "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
        str(out_path)
    ]
    subprocess.run(cmd, capture_output=True)
    return str(out_path)

# ─── BUILD SHORT ──────────────────────────────────────────
def build_short(video_path, voice_path, hook, fact, title):
    print("📱 Building Short...")
    duration  = get_duration(voice_path) + 0.4
    out_path  = OUTPUT_DIR / "short_final.mp4"
    safe_hook = safe_text(hook, 36)
    words = fact.split()
    lines, cur = [], ""
    for word in words:
        if len(cur+word) < 32: cur += word+" "
        else: lines.append(cur.strip()); cur = word+" "
    if cur: lines.append(cur.strip())
    safe_fact = "\n".join(lines[:4]).replace("'","").replace('"',"")
    fade_out  = max(0, duration - 0.4)

    cmd = [
        "ffmpeg","-y",
        "-stream_loop","-1","-i",video_path,
        "-i",voice_path,
        "-filter_complex",
        (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out:.2f}:d=0.3,"
            f"drawbox=x=0:y=0:w=iw:h=200:color=black@0.88:t=fill,"
            f"drawbox=x=0:y=ih-340:w=iw:h=340:color=black@0.88:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=yellow:fontsize=50:"
            f"x=(w-text_w)/2:y=15:fontfile={FONT_BOLD},"
            f"drawtext=text='{safe_hook}':fontcolor=white:fontsize=37:"
            f"x=(w-text_w)/2:y=88:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_fact}':fontcolor=white:fontsize=32:"
            f"x=36:y=h-318:fontfile={FONT_REG}:shadowcolor=black:shadowx=2:shadowy=2:line_spacing=10,"
            f"drawtext=text='FOLLOW FOR MORE':fontcolor=yellow:fontsize=44:"
            f"x=(w-text_w)/2:y=h-50:fontfile={FONT_BOLD}[v]"
        ),
        "-map","[v]","-map","1:a",
        "-t",str(duration),
        "-c:v","libx264","-preset","fast","-c:a","aac","-shortest",
        str(out_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)

# ─── CONCAT ───────────────────────────────────────────────
def concat_clips(clip_paths, output_name="final_video.mp4"):
    print("🔗 Joining clips...")
    valid = [c for c in clip_paths if validate_file(c, 1000)]
    if not valid:
        raise Exception("No valid clips!")

    lf = OUTPUT_DIR / "clips_list.txt"
    with open(lf,"w") as f:
        for c in valid:
            f.write(f"file '{os.path.abspath(c)}'\n")

    out_path = OUTPUT_DIR / output_name
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0",
        "-i",str(lf),
        "-c:v","libx264","-preset","fast","-c:a","aac",
        str(out_path)
    ], check=True, capture_output=True)

    if not validate_file(str(out_path), 100000):
        raise Exception(f"Output invalid: {out_path}")

    print(f"✅ Final: {os.path.getsize(str(out_path))//1024//1024}MB")
    return str(out_path)

# ─── THUMBNAIL ────────────────────────────────────────────
def make_thumbnail(title, topic, fmt):
    print("🖼️  Thumbnail...")
    out_path  = OUTPUT_DIR / "thumbnail.jpg"
    thumb_bg  = download_thumb_image(topic)
    color_hex = fmt.get("accent","FFD700")
    words     = safe_text(title).split()
    mid       = max(1, len(words)//2)
    line1     = safe_text(" ".join(words[:mid]), 32)
    line2     = safe_text(" ".join(words[mid:]), 32)

    if thumb_bg and validate_file(thumb_bg, 5000):
        vf = (
            f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.52:t=fill,"
            f"drawbox=x=0:y=0:w=iw:h=12:color=#{color_hex}:t=fill,"
            f"drawbox=x=0:y=ih-12:w=iw:h=12:color=#{color_hex}:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=32:"
            f"x=(w-text_w)/2:y=20:fontfile={FONT_BOLD},"
            f"drawtext=text='{line1}':fontcolor=white:fontsize=74:"
            f"x=(w-text_w)/2:y=190:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=5:shadowy=5,"
            f"drawtext=text='{line2}':fontcolor=#{color_hex}:fontsize=74:"
            f"x=(w-text_w)/2:y=290:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=5:shadowy=5,"
            f"drawtext=text='Watch Till End!':fontcolor=white:fontsize=42:"
            f"x=(w-text_w)/2:y=628:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=2:shadowy=2"
        )
        cmd = ["ffmpeg","-y","-i",thumb_bg,"-vf",vf,"-frames:v","1",str(out_path)]
    else:
        bg  = fmt.get("color","0x1a1a2e")
        vf  = (
            f"drawbox=x=0:y=0:w=iw:h=12:color=#{color_hex}:t=fill,"
            f"drawbox=x=0:y=ih-12:w=iw:h=12:color=#{color_hex}:t=fill,"
            f"drawtext=text='MindBlownFacts':fontcolor=#{color_hex}:fontsize=32:"
            f"x=(w-text_w)/2:y=20:fontfile={FONT_BOLD},"
            f"drawtext=text='{line1}':fontcolor=white:fontsize=74:"
            f"x=(w-text_w)/2:y=190:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=5:shadowy=5,"
            f"drawtext=text='{line2}':fontcolor=#{color_hex}:fontsize=74:"
            f"x=(w-text_w)/2:y=290:fontfile={FONT_BOLD}:shadowcolor=black:shadowx=5:shadowy=5,"
            f"drawtext=text='Watch Till End!':fontcolor=white:fontsize=42:"
            f"x=(w-text_w)/2:y=628:fontfile={FONT_BOLD}"
        )
        cmd = ["ffmpeg","-y","-f","lavfi","-i",
               f"color=c={bg}:s=1280x720:r=1","-vf",vf,"-frames:v","1",str(out_path)]

    subprocess.run(cmd, capture_output=True)
    return str(out_path)

# ─── SEO METADATA ─────────────────────────────────────────
def save_metadata(title, script, topic, fmt, video_type, is_short=False):
    title    = fix_title(title, topic)
    keywords = script.get("seo_keywords",[topic,"facts","shocking"])
    kw_str   = ", ".join(keywords)

    chapters = ""
    if not is_short:
        chapters = "\n\n📌 CHAPTERS:\n00:00 Introduction\n"
        for i,fact in enumerate(script.get("facts",[]),1):
            mins = i*48
            ft   = safe_text(fact.get("title",f"Fact {i}"), 38)
            chapters += f"{mins//60:02d}:{mins%60:02d} - {ft}\n"

    desc      = script.get("description",f"Shocking facts about {topic}")
    full_desc = (
        f"🤯 {title}\n\n{desc}\n\nKeywords: {kw_str}\n"
        f"{chapters}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 SUBSCRIBE for daily mind-blowing content!\n"
        f"👍 LIKE if this shocked you!\n"
        f"💬 COMMENT which fact surprised you most!\n"
        f"📤 SHARE with friends!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"#MindBlownFacts #Facts #DidYouKnow #{topic.replace(' ','')} #Shocking #Viral"
    )[:4900]

    tags = list(dict.fromkeys(
        script.get("tags",[]) +
        ["mindblownfacts","facts","didyouknow","shocking","viral",
         "educational",fmt["style"],topic.lower().replace(" ","")]
    ))[:30]

    metadata = {
        "title":title,"description":full_desc,"tags":tags,
        "topic":topic,"format":fmt["id"],
        "video_type":video_type,"is_short":is_short,
    }
    fname = "metadata_short.json" if is_short else "metadata.json"
    with open(OUTPUT_DIR/fname,"w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✅ SEO metadata saved!")
    return metadata

# ─── VIDEO TYPE ───────────────────────────────────────────
def get_video_type():
    hour  = datetime.utcnow().hour
    vtype = os.environ.get("VIDEO_TYPE","")
    if vtype: return vtype
    if hour < 6:  return "short"
    if hour < 11: return "video1"
    return "video2"

# ═══════════════════════════════════════════════════════════
# MAKE SHORT
# ═══════════════════════════════════════════════════════════
def make_short():
    print("\n📱 SHORT\n"+"="*50)
    cleanup_temp()
    history = load_history()
    topic   = get_trending_topic()
    script  = generate_short_script(topic)
    fmt     = random.choice(VIDEO_FORMATS)

    full_text = f"{script['hook']} {script['fact']} {script['calltoaction']}"
    voice = generate_voice(full_text, "short")
    video = download_video(script["search_query"], "short")
    final = build_short(video, voice, script["hook"], script["fact"], script["title"])

    save_metadata(script["title"], script, topic, fmt, "short", is_short=True)
    save_history(history)
    print(f"\n✅ SHORT DONE!")
    return final

# ═══════════════════════════════════════════════════════════
# MAKE VIDEO
# ═══════════════════════════════════════════════════════════
def make_video(video_num=1):
    print(f"\n🎬 VIDEO {video_num}\n"+"="*50)
    cleanup_temp()
    history              = load_history()
    fmt, history         = pick_format(history)
    topic, title, history = pick_topic(fmt, history)

    print(f"📌 Format: {fmt['id']}")
    print(f"📌 Topic : {topic}")
    print(f"📌 Title : {title}")

    script      = generate_script(topic, title, fmt)
    music       = download_music()
    whoosh      = make_whoosh()

    # Generate voices
    hook_audio  = generate_voice(script["hook"],           "hook")
    tease_audio = generate_voice(script["midpoint_tease"], "tease")
    outro_audio = generate_voice(script["outro"],          "outro")
    fact_audios = [generate_voice(f["fact"], f["number"]) for f in script["facts"]]

    # Download videos
    fact_videos = [download_video(f["search_query"], f["number"]) for f in script["facts"]]

    # FIX: Teaser montage instead of logo intro!
    intro_clip  = build_teaser(fact_videos, hook_audio, title, fmt)

    # Build fact clips
    fact_clips  = []
    mid         = len(script["facts"]) // 2
    for i, fact in enumerate(script["facts"]):
        clip = build_fact_clip(
            fact_videos[i], fact_audios[i],
            fact["number"], fact["title"], fact["fact"],
            fmt, music, whoosh
        )
        fact_clips.append(clip)
        if i == mid:
            # Use midpoint video as tease background
            tease = build_tease(tease_audio, fmt,
                               fact_videos[mid] if mid < len(fact_videos) else None)
            fact_clips.append(tease)

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
    try:
        if vtype == "short":
            make_short()
        elif vtype == "video2":
            make_video(2)
        else:
            make_video(1)
        print("\n🎉 ALL DONE!")
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    main()