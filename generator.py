import os, json, time, requests, random
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from groq import Groq
from langdetect import detect
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import tempfile
import textwrap

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

_FONT_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "arialbd.ttf",
    "arial.ttf",
]

_FONT_REGULAR = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "arial.ttf",
]

def _http_get(url, params=None, hard_timeout=12):
    """requests.get with a thread-enforced hard deadline that works on all platforms."""
    def _call():
        return requests.get(url, params=params, timeout=(5, hard_timeout))
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call)
        try:
            return fut.result(timeout=hard_timeout + 3)
        except (FuturesTimeout, Exception):
            return None

def _load_font(size, bold=False):
    paths = _FONT_BOLD if bold else _FONT_REGULAR
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

def _text_width(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except AttributeError:
        return draw.textsize(text, font=font)[0]

def _draw_shadow_text(draw, pos, text, font, fill="white", shadow=(15, 15, 15)):
    x, y = pos
    draw.text((x + 2, y + 2), text, fill=shadow, font=font)
    draw.text((x, y), text, fill=fill, font=font)

def detect_language(article):
    try:
        return detect(article["title"] + " " + article["summary"])
    except:
        return "en"

def get_post_length(score, level):
    if level == 1 and score >= 100:
        return "up to 50 lines — this is a major breaking story, explain fully"
    elif level == 1 and score >= 80:
        return "up to 20 lines — important breaking news, explain in detail"
    elif level <= 2 and score >= 60:
        return "7 lines — important news, cover key facts"
    else:
        return "4 to 5 lines — brief and punchy"

def add_text_overlay(image_path, headline, source_type="world", is_breaking=False):
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((1200, 630), Image.LANCZOS)
        w, h = img.size

        if source_type == "pakistan":
            accent   = (0, 150, 0)
            tag_text = "PAKISTAN NEWS"
        else:
            accent   = (200, 20, 20)
            tag_text = "WORLD NEWS"

        font_headline = _load_font(44, bold=True)
        font_tag      = _load_font(21, bold=True)
        font_breaking = _load_font(21, bold=True)
        font_brand_b  = _load_font(21, bold=True)
        font_brand    = _load_font(21)

        # Strong gradient covering bottom half
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ov      = ImageDraw.Draw(overlay)
        start   = h // 2
        for i in range(h - start):
            alpha = int((i / (h - start)) ** 0.6 * 245)
            ov.rectangle([(0, start + i), (w, start + i + 1)], fill=(0, 0, 0, alpha))
        img  = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Source tag — top left
        tag_w = _text_width(draw, tag_text, font_tag) + 26
        tx, ty = 20, 20
        draw.rectangle([(tx, ty), (tx + tag_w, ty + 38)], fill=accent)
        draw.text((tx + 13, ty + 8), tag_text, fill="white", font=font_tag)

        # Breaking badge — next to source tag
        if is_breaking:
            bx      = tx + tag_w + 10
            br_text = "⚡ BREAKING"
            br_w    = _text_width(draw, br_text, font_breaking) + 26
            draw.rectangle([(bx, ty), (bx + br_w, ty + 38)], fill=(215, 0, 0))
            draw.text((bx + 13, ty + 8), br_text, fill="white", font=font_breaking)

        # Accent line above headline
        line_y = h - 222
        draw.rectangle([(20, line_y), (72, line_y + 4)], fill=accent)
        draw.rectangle([(76, line_y + 1), (w - 20, line_y + 2)], fill=(140, 140, 140))

        # Headline text
        wrapped = textwrap.wrap(headline, width=46)[:3]
        y_text  = line_y + 15
        for line in wrapped:
            _draw_shadow_text(draw, (20, y_text), line, font_headline)
            y_text += 58

        # Branding bar
        bar_y = h - 52
        draw.rectangle([(0, bar_y), (w, h)], fill=(8, 8, 8))
        draw.text((20, bar_y + 14), "VISIONARY MINDS", fill=accent, font=font_brand_b)
        sep_x = 20 + _text_width(draw, "VISIONARY MINDS", font_brand_b) + 10
        draw.text((sep_x, bar_y + 14), "|  Authentic News, Every Hour", fill=(165, 165, 165), font=font_brand)

        output = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(output.name, "JPEG", quality=95)
        output.close()
        print(f"  Image overlay applied successfully")
        return output.name

    except Exception as e:
        print(f"  Overlay error: {e}")
        return image_path


def generate_post(article):
    lang      = detect_language(article)
    lang_names = {"ur": "Urdu", "ar": "Arabic", "hi": "Hindi", "fa": "Persian"}
    instruction = (
        f"The article is in {lang_names.get(lang, 'another language')}. Translate fully to English."
        if lang != "en" else "Article is in English."
    )

    source_label = "🇵🇰 Pakistan" if article["source_type"] == "pakistan" else "🌍 World News"
    score        = article.get("score", 50)
    level        = article.get("level", 3)
    post_length  = get_post_length(score, level)

    prompt = f"""You are a senior editor at a world-class international news network (BBC, Reuters, Al Jazeera level quality).

Article Title: {article['title']}
Article Details: {article['summary']}
Category: {source_label}
Importance Score: {score}
{instruction}

Write a professional Facebook news post.

WRITING RULES:
- Open directly with the most important fact — no filler phrases like "In a shocking development", "According to reports", or "It has been revealed"
- Be factual, authoritative, and clear — like a Reuters wire report rewritten for social media
- Short punchy sentences. No passive voice. No fluff.
- Only state confirmed facts from the article — zero speculation
- End with one sharp closing line that gives perspective or invites a reaction
- NO sexual content — if the article has any sexual theme, write only about the legal/political/social impact

STRUCTURE TO FOLLOW:
[Relevant emoji] [Strong opening statement — the single most important fact]

[2-3 sentences of key verified facts]

[1-2 sentences of context — background or why this matters globally/regionally]

[1 sharp closing line — significance or a thought-provoking question]

[Hashtags on their own line — 5 to 7, specific and relevant]

POST LENGTH: {post_length}
LANGUAGE: English only
HASHTAGS: Include #Pakistan for Pakistan news. Make hashtags specific, not generic (#PakistanFlood not just #news).

Return ONLY valid JSON with no extra text before or after:
{{
  "post_text": "your complete post here with hashtags at the very end",
  "image_keywords": "3-4 specific words describing the actual scene/location/event for image search. Example: 'pakistan train rescue workers', 'gaza buildings smoke rubble', 'india protest crowd street'. Never use: news, breaking, media, photorealistic, powerful.",
  "image_headline": "6-8 word direct factual headline for the image overlay. No vague words."
}}"""

    for attempt in range(3):
        try:
            print(f"  Groq attempt {attempt+1}...")
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}]
            )
            text = r.choices[0].message.content
            if not text or not text.strip():
                print(f"  Empty response from Groq")
                time.sleep(2)
                continue
            text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text)
            print(f"  Keywords: {result.get('image_keywords')}")
            print(f"  Headline: {result.get('image_headline')}")
            return result

        except json.JSONDecodeError as e:
            print(f"  JSON error: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  Groq error: {e}")
            time.sleep(2)
    return None


def generate_image(keywords, headline, source_type="world", is_breaking=False):
    clean_keywords = keywords.lower()
    remove_words   = ["news", "breaking", "media", "photorealistic",
                      "powerful", "scene", "photo", "image"]
    for word in remove_words:
        clean_keywords = clean_keywords.replace(word, "").strip()

    search_terms = [
        clean_keywords,
        " ".join(clean_keywords.split()[:2]),
        clean_keywords.split()[0] if clean_keywords.split() else "world",
        "pakistan" if source_type == "pakistan" else "world crisis"
    ]

    print(f"  Searching image: {clean_keywords}")

    for term in search_terms:
        if not term.strip():
            continue
        try:
            r = _http_get(
                "https://pixabay.com/api/",
                params={
                    "key":        os.getenv("PIXABAY_API_KEY"),
                    "q":          term,
                    "image_type": "photo",
                    "per_page":   10,
                    "min_width":  1200,
                    "safesearch": "true",
                    "order":      "popular",
                    "category":   "news" if source_type == "world" else ""
                }
            )
            if r is None:
                print(f"  Pixabay timeout for '{term}'")
                continue
            data = r.json()

            if data.get("hits"):
                hit     = random.choice(data["hits"])
                img_url = hit["largeImageURL"]
                print(f"  Image found for '{term}'")

                img_resp = _http_get(img_url, hard_timeout=20)
                if img_resp is None:
                    continue
                img_data = img_resp.content
                if len(img_data) > 5000:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    tmp.write(img_data)
                    tmp.close()
                    final_path = add_text_overlay(tmp.name, headline, source_type, is_breaking)
                    if final_path != tmp.name:
                        try:
                            os.unlink(tmp.name)
                        except:
                            pass
                    return final_path

        except Exception as e:
            print(f"  Image error '{term}': {e}")
            continue

    return None
