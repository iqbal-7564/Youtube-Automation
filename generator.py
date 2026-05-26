import os, json, time, requests, random, tempfile, textwrap
from groq       import Groq
from langdetect import detect
from dotenv     import load_dotenv
from PIL        import Image, ImageDraw, ImageFont

load_dotenv()

# Create Groq clients ONCE at module level
_client_1 = Groq(api_key=os.getenv("GROQ_API_KEY"))   if os.getenv("GROQ_API_KEY")   else None
_client_2 = Groq(api_key=os.getenv("GROQ_API_KEY_2")) if os.getenv("GROQ_API_KEY_2") else None

_FONT_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf", "arial.ttf",
]
_FONT_REGULAR = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "arial.ttf",
]

def _load_font(size, bold=False):
    for path in (_FONT_BOLD if bold else _FONT_REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

def _text_width(draw, text, font):
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0]
    except AttributeError:
        return draw.textsize(text, font=font)[0]

def _draw_rounded_rect(draw, bbox, radius, fill):
    """Compatible with ALL Pillow versions"""
    try:
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)
    except AttributeError:
        draw.rectangle(bbox, fill=fill)

def _shadow_text(draw, pos, text, font, fill="white", shadow=(0, 0, 0)):
    x, y = pos
    for dx, dy in [(-1,-1),(1,-1),(-1,1),(1,1),(0,2),(2,0)]:
        draw.text((x+dx, y+dy), text, fill=shadow, font=font)
    draw.text((x, y), text, fill=fill, font=font)

def detect_language(article):
    try:
        return detect(article["title"] + " " + article["summary"])
    except:
        return "en"

def get_post_length(score, level):
    if level == 1 and score >= 100:
        return "8-10 sentences — major breaking story"
    elif level == 1 and score >= 80:
        return "6-8 sentences — important breaking news"
    elif level <= 2 and score >= 60:
        return "4-6 sentences — important news"
    else:
        return "3-4 sentences — brief and punchy"

def add_text_overlay(image_path, headline, source_type="world", is_breaking=False):
    tmp_path = None
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((1200, 630), Image.LANCZOS)
        w, h = img.size

        if source_type == "pakistan":
            accent   = (0, 160, 72)
            tag_text = "🇵🇰  PAKISTAN NEWS"
        else:
            accent   = (210, 30, 30)
            tag_text = "🌍  WORLD NEWS"

        font_tag      = _load_font(22, bold=True)
        font_breaking = _load_font(22, bold=True)
        font_headline = _load_font(46, bold=True)
        font_brand_b  = _load_font(20, bold=True)
        font_brand    = _load_font(20)

        # Dark gradient bottom 60%
        overlay    = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ov         = ImageDraw.Draw(overlay)
        grad_start = int(h * 0.35)
        for i in range(h - grad_start):
            t     = i / (h - grad_start)
            alpha = int((t ** 0.5) * 230)
            ov.rectangle(
                [(0, grad_start + i), (w, grad_start + i + 1)],
                fill=(0, 0, 0, alpha)
            )

        # Vignette top
        for i in range(120):
            alpha = int((1 - i / 120) * 80)
            ov.rectangle([(0, i), (w, i+1)], fill=(0, 0, 0, alpha))

        img  = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Top bar
        bar_h = 48
        draw.rectangle([(0, 0), (w, bar_h)], fill=(0, 0, 0))

        # Tag pill — compatible all Pillow versions
        tag_w = _text_width(draw, tag_text, font_tag) + 32
        _draw_rounded_rect(draw, [(16, 8), (16 + tag_w, bar_h - 8)],
                           radius=6, fill=accent)
        draw.text((32, 14), tag_text, fill="white", font=font_tag)

        # Breaking badge
        if is_breaking:
            bx     = 16 + tag_w + 12
            br_txt = "⚡ BREAKING"
            br_w   = _text_width(draw, br_txt, font_breaking) + 24
            _draw_rounded_rect(draw, [(bx, 8), (bx + br_w, bar_h - 8)],
                               radius=6, fill=(220, 0, 0))
            draw.text((bx + 12, 14), br_txt, fill="white", font=font_breaking)

        # Accent line
        line_y = h - 230
        draw.rectangle([(16, line_y), (80, line_y + 5)], fill=accent)
        draw.rectangle([(85, line_y + 2), (w - 16, line_y + 3)],
                        fill=(200, 200, 200))

        # Headline
        wrapped = textwrap.wrap(headline, width=42)[:3]
        y_text  = line_y + 16
        for line in wrapped:
            _shadow_text(draw, (16, y_text), line, font_headline)
            y_text += 60

        # Branding bar
        bar_y = h - 52
        draw.rectangle([(0, bar_y), (w, h)], fill=(10, 10, 10))
        draw.text((20, bar_y + 14), "VISIONARY MINDS",
                  fill=accent, font=font_brand_b)
        sep_x = 20 + _text_width(draw, "VISIONARY MINDS", font_brand_b) + 12
        draw.text((sep_x, bar_y + 14),
                  "|  Authentic News, Every Hour",
                  fill=(180, 180, 180), font=font_brand)

        out      = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp_path = out.name
        img.save(tmp_path, "JPEG", quality=97, optimize=True)
        out.close()
        print(f"  Image overlay applied successfully")
        return tmp_path

    except Exception as e:
        print(f"  Overlay error: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except:
                pass
        return image_path

# ─── AI Providers ─────────────────────────────────────────

def _call_groq(client, prompt):
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=600,
    )
    return r.choices[0].message.content

def generate_post(article):
    lang       = detect_language(article)
    lang_names = {"ur": "Urdu", "ar": "Arabic", "hi": "Hindi", "fa": "Persian"}
    instruction = (
        f"Article is in {lang_names.get(lang, 'another language')}. Translate fully to English."
        if lang != "en" else "Article is in English."
    )

    source_label = "🇵🇰 Pakistan" if article["source_type"] == "pakistan" else "🌍 World"
    score        = article.get("score", 50)
    level        = article.get("level", 3)
    post_length  = get_post_length(score, level)

    prompt = f"""Professional news social media writer. Write an engaging post.

Title: {article['title']}
Details: {article['summary'][:600]}
Region: {source_label}
{instruction}

RULES:
- English only
- Open with single most important fact — no filler
- Factual, clear, authoritative
- {post_length}
- End with sharp closing line
- 5-7 specific hashtags on last line
- #Pakistan for Pakistan news
- ZERO sexual or inappropriate content

Return ONLY valid JSON:
{{"post_text":"full post with hashtags on last line","image_keywords":"3-4 SPECIFIC words describing actual scene/location. Example: 'pakistan army mountains operation', 'gaza city destroyed rubble', 'islamabad court protest crowd'. NEVER use: news breaking media photorealistic","image_headline":"7-9 word factual punchy headline for image"}}"""

    providers = [("Groq-1", _client_1), ("Groq-2", _client_2)]

    for name, client in providers:
        if not client:
            continue
        for attempt in range(3):
            try:
                print(f"  {name} attempt {attempt+1}...")
                text = _call_groq(client, prompt)
                if not text or not text.strip():
                    time.sleep(3)
                    continue
                text   = text.replace("```json","").replace("```","").strip()
                result = json.loads(text)
                if not result.get("post_text") or not result.get("image_keywords"):
                    time.sleep(2)
                    continue
                print(f"  Keywords: {result['image_keywords']}")
                print(f"  Headline: {result.get('image_headline','')}")
                return result
            except json.JSONDecodeError as e:
                print(f"  JSON error: {e}")
                time.sleep(3)
            except Exception as e:
                msg = str(e)
                if "429" in msg or "rate_limit" in msg.lower():
                    print(f"  {name} rate limit — switching")
                    break
                print(f"  {name} error: {e}")
                time.sleep(5)
    return None

# ─── Generate Image ───────────────────────────────────────

def generate_image(keywords, headline, source_type="world", is_breaking=False):
    clean = keywords.lower()
    for w in ["news","breaking","media","photorealistic","powerful",
              "scene","photo","image","a ","an ","the "]:
        clean = clean.replace(w, " ").strip()
    clean = " ".join(clean.split())

    parts        = [p.strip() for p in clean.replace(",", " ").split() if p.strip()]
    search_terms = []
    if len(parts) >= 3:
        search_terms.append(" ".join(parts[:3]))
    if len(parts) >= 2:
        search_terms.append(" ".join(parts[:2]))
    if parts:
        search_terms.append(parts[0])
    search_terms.append(
        "pakistan protest crowd" if source_type == "pakistan"
        else "war crisis military"
    )

    print(f"  Searching image: {clean}")

    for term in search_terms:
        if not term.strip():
            continue
        tmp_path = None
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key":        os.getenv("PIXABAY_API_KEY"),
                    "q":          term,
                    "image_type": "photo",
                    "per_page":   15,
                    "min_width":  1200,
                    "min_height": 600,
                    "safesearch": "true",
                    "order":      "popular",
                },
                timeout=12
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not data.get("hits"):
                continue

            top_hits = data["hits"][:5]
            hit      = random.choice(top_hits)
            img_url  = hit["largeImageURL"]
            print(f"  Image found for '{term}'")

            img_resp = requests.get(img_url, timeout=20)
            if img_resp.status_code != 200 or len(img_resp.content) < 5000:
                continue

            tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp_path = tmp.name
            tmp.write(img_resp.content)
            tmp.close()

            final = add_text_overlay(tmp_path, headline, source_type, is_breaking)
            if final != tmp_path:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            return final

        except Exception as e:
            print(f"  Image error '{term}': {e}")
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            continue

    return None