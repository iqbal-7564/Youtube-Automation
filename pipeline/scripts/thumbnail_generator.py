"""
STEP 14 — Thumbnail Generation (8 Distinct Viral Layouts)

Each layout is modeled after a proven high-CTR thumbnail style observed
in channels with 10K-44K views per video:

  pure_text    — near-black bg, text IS the visual  ("99.9999% IS NOTHING.")
  claim_left   — dark left + image right, 2-line claim  ("DISTANCE IS / AN ILLUSION")
  highlight_box — bright colored box behind text on image bg ("DO YOU HAVE X?")
  bottom_wide  — full image + solid band at bottom ("IMPOSSIBLE DISTANCE")
  full_text    — heavy dark overlay, full-frame text block ("THE REASON THEY HURT YOU")
  split_vs     — left dark label vs right bright concept  ("MYTHS vs REALITY")
  number_hero  — giant number dominates center
  top_banner   — text in dark strip top, image bottom half

Layout is chosen by hashing the video title so the same video always
gets the same layout, but consecutive videos cycle through all 8 styles.
"""

import logging
import os
import random
import re
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)

_TW, _TH = 1280, 720

_INTENT_BG: dict[str, tuple[int, int, int]] = {
    "SPACE":       (8,   4,  48),
    "SCIENCE":     (0,  25,  80),
    "HISTORY":     (50, 24,   0),
    "ANIMALS":     (8,  44,   0),
    "NATURE":      (0,  44,  12),
    "GEOGRAPHY":   (0,  44,  44),
    "OCEAN":       (0,  24,  60),
    "CULTURE":     (55, 22,   0),
    "TECHNOLOGY":  (0,  16,  55),
    "PSYCHOLOGY":  (36,  0,  64),
    "MYTHOLOGY":   (44, 26,   0),
    "MEDICINE":    (64,  0,  18),
    "MATHEMATICS": (0,  12,  55),
    "ECONOMICS":   (0,  40,  12),
    "PHYSICS":     (55, 22,   0),
}

_INTENT_PILL_COLOR: dict[str, tuple[int, int, int]] = {
    "SPACE":       (26,  10, 107),
    "SCIENCE":     (0,   85, 170),
    "HISTORY":     (107, 58,   0),
    "ANIMALS":     (26,  92,   0),
    "NATURE":      (0,   92,  26),
    "GEOGRAPHY":   (0,  102, 102),
    "OCEAN":       (0,   64, 128),
    "CULTURE":     (122, 53,   0),
    "TECHNOLOGY":  (0,   90, 180),
    "PSYCHOLOGY":  (90,   0, 160),
    "MYTHOLOGY":   (120, 70,   0),
    "MEDICINE":    (160,  0,  50),
    "MATHEMATICS": (0,   50, 150),
    "ECONOMICS":   (0,  110,  40),
    "PHYSICS":     (160, 60,   0),
}

_INTENT_ACCENT: dict[str, tuple[int, int, int]] = {
    "SPACE":       (255, 220,  50),
    "SCIENCE":     (80,  210, 255),
    "HISTORY":     (255, 195,  60),
    "ANIMALS":     (110, 255,  90),
    "NATURE":      (90,  255, 140),
    "GEOGRAPHY":   (70,  225, 225),
    "OCEAN":       (70,  195, 255),
    "CULTURE":     (255, 175,  70),
    "TECHNOLOGY":  (40,  215, 255),
    "PSYCHOLOGY":  (210, 90,  255),
    "MYTHOLOGY":   (255, 195,  40),
    "MEDICINE":    (255,  70, 110),
    "MATHEMATICS": (90,  175, 255),
    "ECONOMICS":   (40,  215,  90),
    "PHYSICS":     (255, 130,  40),
}

# Box background color (for highlight_box layout) — vivid, high-contrast
_INTENT_BOX_COLOR: dict[str, tuple[int, int, int]] = {
    "SPACE":       (20,   0, 120),
    "SCIENCE":     (0,   60, 160),
    "HISTORY":     (130,  50,   0),
    "ANIMALS":     (0,  110,  20),
    "NATURE":      (0,  120,  40),
    "GEOGRAPHY":   (0,  110, 110),
    "OCEAN":       (0,   70, 160),
    "CULTURE":     (150,  60,   0),
    "TECHNOLOGY":  (0,   50, 180),
    "PSYCHOLOGY":  (100,   0, 190),
    "MYTHOLOGY":   (130,  60,   0),
    "MEDICINE":    (180,   0,  50),
    "MATHEMATICS": (0,   50, 180),
    "ECONOMICS":   (0,  130,  40),
    "PHYSICS":     (180,  50,   0),
}

_STOP_WORDS = {
    "the", "a", "an", "of", "that", "could", "was", "is", "are", "were",
    "be", "been", "being", "have", "has", "had", "will", "would", "can",
    "may", "might", "shall", "should", "to", "for", "in", "on", "at",
    "by", "with", "from", "into", "about", "and", "or", "but", "if",
    "as", "so", "it", "its", "this", "these", "those", "there", "here",
    "all", "every", "some", "than", "then", "too", "very", "just",
}

_POWER_WORDS = {
    "impossible", "hidden", "secret", "destroyed", "dead", "dying",
    "never", "forbidden", "exposed", "revealed", "truth", "lie", "fake",
    "real", "terrifying", "dangerous", "deadly", "massive", "ancient",
    "lost", "found", "discovered", "broke", "breaks", "failed", "extinct",
    "vanished", "buried", "dark", "deep", "invisible", "wrong", "disaster",
    "insane", "crazy", "genius", "perfect", "ultimate", "survive", "kill",
    "glow", "frozen", "burning", "alive", "missing", "banned", "warning",
    "crisis", "shock", "mystery", "cursed", "haunted", "doomed",
    "lied", "hiding", "erased", "wiped", "collapsed", "silent",
    "proof", "confirmed", "leaked", "classified", "untold", "covered",
}

_RIBBON_POWER = [
    "EXPOSED", "REVEALED", "TRUTH", "PROOF", "HIDDEN", "REAL",
    "LEAKED", "LIED", "BANNED", "UNTOLD", "CONFIRMED", "FORBIDDEN",
]

# 9 distinct layouts — each looks completely different visually.
# person_claim appears 3× because it's the #1 CTR format on YouTube
# (shocked face + text claim matches how top channels structure thumbnails).
_LAYOUTS = [
    "person_claim",  # shocked face right + 2-line claim left  ← #1 CTR
    "claim_left",    # dark left gradient + image right
    "highlight_box", # bright colored box behind text on image
    "person_claim",  # shocked face (different query, 2nd rotation)
    "bottom_wide",   # full dramatic image + solid bottom band
    "pure_text",     # near-black bg, giant centered text
    "person_claim",  # shocked face (3rd rotation)
    "split_vs",      # dark left panel vs right image with divider
    "top_banner",    # dark top strip + image bottom
    "full_text",     # heavy overlay + accent boxes behind text
]

# ── Pollinations.ai visual styles per category ────────────────────────────────
_INTENT_THUMB_STYLE: dict[str, str] = {
    "SPACE":       "deep space nebula explosion, glowing galaxy, cosmic black hole, dramatic starfield",
    "SCIENCE":     "dramatic laboratory experiment, glowing particles, DNA helix, scientific explosion",
    "HISTORY":     "ancient ruins dramatic lighting, mysterious civilization, epic historical scene",
    "ANIMALS":     "extreme close-up wildlife, powerful predator, dramatic animal portrait, intense eyes",
    "NATURE":      "dramatic lightning storm, volcanic eruption, epic natural disaster, extreme weather",
    "GEOGRAPHY":   "dramatic aerial canyon, alien landscape, extreme mountain, volcanic lava field",
    "OCEAN":       "deep ocean bioluminescent creature, dramatic underwater abyss, sea monster encounter",
    "CULTURE":     "ancient mysterious temple, dramatic archaeological discovery, lost civilization",
    "TECHNOLOGY":  "futuristic AI visualization, glowing circuit neural network, dramatic neon cybertech",
    "PSYCHOLOGY":  "dramatic human mind concept, glowing brain visualization, psychological illusion",
    "MYTHOLOGY":   "epic mythological battle, ancient gods, dramatic fantasy epic scene, divine power",
    "MEDICINE":    "dramatic microscopic cellular world, glowing virus visualization, medical breakthrough",
    "MATHEMATICS": "dramatic fractal geometry, abstract mathematical dimension, impossible structure",
    "ECONOMICS":   "dramatic financial collapse visualization, glowing global market data, crisis scene",
    "PHYSICS":     "particle accelerator explosion, quantum visualization, dramatic energy wave",
}


# Shocked/amazed human face queries — rotated per video for variety.
# Portrait orientation gives clean face shots for the person_claim layout.
_FACE_QUERIES = [
    "shocked person expression face",
    "amazed man open mouth surprise",
    "surprised woman wide eyes face",
    "shocked reaction person closeup",
    "stunned amazed expression face",
    "disbelief jaw drop person face",
    "mind blown expression person",
    "person pointing shocked face",
    "young man shocked surprised face",
    "woman shocked disbelief expression",
    "man wide eyes amazed face",
    "person covering mouth shocked",
]

# Topic-specific Pexels background queries per category.
# These return real photographs that are visually relevant to the video topic.
_INTENT_BG_QUERIES: dict[str, str] = {
    "SPACE":       "space galaxy nebula dramatic stars",
    "SCIENCE":     "laboratory science experiment glowing",
    "HISTORY":     "ancient ruins stone temple dramatic light",
    "ANIMALS":     "wildlife predator dramatic nature animal",
    "NATURE":      "dramatic storm lightning nature landscape",
    "GEOGRAPHY":   "canyon landscape aerial dramatic mountain",
    "OCEAN":       "ocean underwater dramatic blue deep sea",
    "CULTURE":     "ancient architecture temple city dramatic",
    "TECHNOLOGY":  "technology neon circuit futuristic glow",
    "PSYCHOLOGY":  "human brain mind concept dramatic",
    "MYTHOLOGY":   "epic ancient statue mystery dramatic",
    "MEDICINE":    "medical science cell microscope dramatic",
    "MATHEMATICS": "geometric pattern abstract dramatic light",
    "ECONOMICS":   "financial city architecture wealth dramatic",
    "PHYSICS":     "energy wave particle physics abstract",
}

# ── AI background generation ──────────────────────────────────────────────────

def _build_pollinations_prompt(title: str, intent: str) -> tuple[str, int]:
    style = _INTENT_THUMB_STYLE.get(intent.upper(), "dramatic cinematic scene, extreme lighting")
    stop  = {
        "the","a","an","of","that","is","are","was","were","and","or","in","on",
        "at","to","for","with","by","from","it","its","this","these","those",
        "be","been","being","have","has","had","will","would","can","could",
        "why","how","what","where","when","who","which","never","ever",
    }
    keywords = [
        w.strip(".,!?:;\"'|").replace("|", "")
        for w in title.split()
        if w.lower().strip(".,!?:;\"'|") not in stop
        and len(w.strip(".,!?:;\"'|")) > 2
    ][:5]
    kw_str = " ".join(keywords)
    seed   = abs(hash(title)) % 999983
    return (
        f"ultra-photorealistic cinematic YouTube thumbnail background, {kw_str}, "
        f"{style}, dramatic extreme lighting, ultra high contrast, 8K hyper-detail, "
        f"cinematic color grading, award-winning photography, jaw-dropping shocking visual, "
        f"no text, no watermark, no UI elements, no letters, professional studio quality, "
        f"volumetric rays, depth of field bokeh, epic dramatic atmosphere"
    ), seed


def _fetch_ai_bg(title: str, intent: str, cache_dir: Path) -> "Path | None":
    import os, urllib.parse, time
    try:
        import requests as _req
    except ImportError:
        return None

    prompt, seed = _build_pollinations_prompt(title, intent)
    cache_path   = cache_dir / f"thumb_ai_{seed % 10000}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 20_000:
        return cache_path

    hf_keys = [os.getenv(f"HUGGINGFACE_API_KEY_{i}", "").strip() for i in range(1, 6)]
    hf_keys = [k for k in hf_keys if k]

    if hf_keys:
        log.info("  Generating AI thumbnail via HuggingFace SDXL ...")
        hf_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        for key in hf_keys:
            for attempt in range(2):
                try:
                    r = _req.post(
                        hf_url,
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "inputs": prompt,
                            "parameters": {
                                "width":               1344,
                                "height":              768,
                                "num_inference_steps": 25,
                                "guidance_scale":      7.5,
                                "seed":                seed,
                            },
                        },
                        timeout=90,
                    )
                    if r.status_code == 200 and len(r.content) > 20_000:
                        cache_path.write_bytes(r.content)
                        log.info("  HF SDXL AI background ready (%d KB)", len(r.content) // 1024)
                        return cache_path
                    if r.status_code == 503:
                        log.debug("HF model loading, waiting 20s ...")
                        time.sleep(20)
                    else:
                        log.debug("HF attempt %d key[%s]: status=%d", attempt + 1, key[:8], r.status_code)
                        break
                except Exception as exc:
                    log.debug("HF attempt %d failed: %s", attempt + 1, exc)

    log.info("  Trying Pollinations.ai as fallback ...")
    encoded = urllib.parse.quote(prompt)
    pol_url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1280&height=720&enhance=true&nologo=true&seed={seed}"
    )
    for attempt in range(2):
        try:
            r = _req.get(pol_url, timeout=55)
            if r.status_code == 200 and len(r.content) > 15_000:
                cache_path.write_bytes(r.content)
                log.info("  Pollinations AI background ready (%d KB)", len(r.content) // 1024)
                return cache_path
        except Exception as exc:
            log.debug("Pollinations attempt %d failed: %s", attempt + 1, exc)
        if attempt < 1:
            time.sleep(4)

    log.warning("  AI background generation failed — falling back to Pexels image")
    return None


# ── Pexels real-photo fetching ────────────────────────────────────────────────

def _fetch_pexels_face(title: str, cache_dir: Path) -> "Path | None":
    """
    Fetch a shocked/amazed human face from Pexels for the person_claim layout.
    Uses portrait orientation so the face fills the right side of the thumbnail.
    Query rotates based on title hash so consecutive videos show different faces.
    """
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return None
    try:
        import requests as _req
    except ImportError:
        return None

    query      = _FACE_QUERIES[abs(hash(title)) % len(_FACE_QUERIES)]
    cache_path = cache_dir / f"thumb_face_{abs(hash(title + 'face')) % 99991}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 15_000:
        return cache_path

    try:
        r = _req.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "portrait",
                    "per_page": 15, "size": "large"},
            timeout=15,
        )
        if not r.ok:
            return None
        photos = r.json().get("photos", [])
        if not photos:
            return None
        photo = photos[abs(hash(title)) % len(photos)]
        url   = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not url:
            return None
        img_r = _req.get(url, timeout=20)
        if img_r.ok and len(img_r.content) > 15_000:
            cache_path.write_bytes(img_r.content)
            log.info("  Pexels face image ready: %s", query)
            return cache_path
    except Exception as exc:
        log.debug("Pexels face fetch '%s': %s", query, exc)
    return None


def _fetch_pexels_bg(title: str, intent: str, cache_dir: Path) -> "Path | None":
    """
    Fetch a topic-matched background from Pexels using title keywords + category style.
    Falls back gracefully if PEXELS_API_KEY is not set.
    """
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return None
    try:
        import requests as _req
    except ImportError:
        return None

    stop = {
        "the","a","an","of","is","are","was","were","and","or","in","on","at","to",
        "for","with","by","from","it","this","that","why","how","what","do","does",
        "did","can","will","would","could","should","really","actually","ever","never",
    }
    kw    = [w.strip(".,!?:;\"'|") for w in title.split()
             if w.lower().strip(".,!?:;\"'|") not in stop
             and len(w.strip(".,!?:;\"'|")) > 2][:3]
    style = _INTENT_BG_QUERIES.get(intent.upper(), "dramatic cinematic scene")
    query = (" ".join(kw) + " " + style).strip() if kw else style

    cache_path = cache_dir / f"thumb_pexbg_{abs(hash(title + 'bg')) % 99991}.jpg"
    if cache_path.exists() and cache_path.stat().st_size > 20_000:
        return cache_path

    try:
        r = _req.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "landscape",
                    "per_page": 15, "size": "large"},
            timeout=15,
        )
        if not r.ok:
            return None
        photos = r.json().get("photos", [])
        if not photos:
            return None
        photo = photos[abs(hash(title)) % len(photos)]
        url   = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not url:
            return None
        img_r = _req.get(url, timeout=20)
        if img_r.ok and len(img_r.content) > 20_000:
            cache_path.write_bytes(img_r.content)
            log.info("  Pexels topic bg ready: '%s'", query[:55])
            return cache_path
    except Exception as exc:
        log.debug("Pexels bg fetch '%s': %s", query[:40], exc)
    return None


# ── Hook → thumbnail claim ────────────────────────────────────────────────────

_HOOK_FILLER_STARTS = {
    "did", "do", "does", "have", "has", "there", "this", "in", "a", "an", "the",
    "today", "welcome", "here", "wait", "stop", "so", "now", "well", "basically",
    "imagine", "consider", "think", "let", "what", "if",
}


def _hook_to_thumb_lines(hook_text: str, title: str) -> tuple[str, str]:
    """
    Convert hook sentence into 2 punchy thumbnail lines.
    Line 1 (accent color, largest): 2-3 content words — the shocking subject
    Line 2 (white, smaller):        2-4 content words — the implication

    Examples:
      "Black holes literally stop time." → ("BLACK HOLES", "STOP TIME")
      "99.9999% of space is nothing."   → ("99.9999%", "IS NOTHING.")
      "The ocean glows blue at night."  → ("OCEAN GLOWS", "BLUE AT NIGHT")
    """
    first = re.split(r"[.!?]", hook_text)[0].strip()
    words = [w.strip(".,!?:;\"'()") for w in first.split() if w.strip(".,!?:;\"'()")]

    while words and words[0].lower() in _HOOK_FILLER_STARTS:
        words.pop(0)

    if len(words) < 2:
        return _extract_keyword_and_subtitle(title)

    split = 2 if len(words) <= 5 else 3
    line1 = " ".join(words[:split]).upper()
    line2_words = [w for w in words[split:split + 5] if w.lower() not in _STOP_WORDS]
    line2 = " ".join(line2_words[:4]).upper() if line2_words else ""

    if not line2:
        tw = [w.strip(".,!?:;\"'|") for w in title.split()
              if w.lower().strip(".,!?:;\"'|") not in _STOP_WORDS]
        line2 = " ".join(tw[-2:]).upper() if len(tw) >= 2 else ""

    return line1, line2


# ── Main entry ────────────────────────────────────────────────────────────────

def generate_thumbnail(
    timeline: dict,
    script:   dict,
    visuals_dir: Path,
    out_path: Path,
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.warning("Pillow not installed — thumbnail skipped")
        return out_path

    intent = timeline.get("intent", "SCIENCE").upper()

    title = script.get("metadata", {}).get("title", "").strip()
    if not title:
        for sc in timeline.get("scenes", []):
            if sc.get("segment_label") == "HOOK":
                title = sc.get("script_text", "").strip()[:80]
                break
    if not title:
        title = "The Fact That Changes Everything"

    # Extract hook sentence for the thumbnail claim
    hook_text = next(
        (sc.get("script_text", "") for sc in timeline.get("scenes", [])
         if sc.get("segment_label") == "HOOK"),
        "",
    )

    if hook_text and len(hook_text.split()) >= 3:
        line1, line2 = _hook_to_thumb_lines(hook_text, title)
    else:
        line1, line2 = _extract_keyword_and_subtitle(title)

    accent     = _INTENT_ACCENT.get(intent, (255, 220, 50))
    pill_color = _INTENT_PILL_COLOR.get(intent, (0, 85, 170))
    box_color  = _INTENT_BOX_COLOR.get(intent, (20, 0, 120))
    bg_color   = _INTENT_BG.get(intent, (10, 10, 40))

    # Force number_hero when title has an impressive number
    big_number = _extract_number(title)
    if big_number:
        layout = "number_hero"
    else:
        layout = _LAYOUTS[abs(hash(title)) % len(_LAYOUTS)]

    # Fetch face image for person_claim layout (portrait Pexels photo)
    face_path = None
    if layout == "person_claim":
        face_path = _fetch_pexels_face(title, visuals_dir)
        if not face_path:
            # No face available — fall back to claim_left which has the same structure
            layout = "claim_left"
            log.debug("Face fetch failed — downgrading person_claim → claim_left")

    bg   = _load_background(visuals_dir, timeline, intent, title)
    draw = ImageDraw.Draw(bg)

    pad        = 50
    font_small = _load_font(30)

    # ── Per-layout rendering ──────────────────────────────────────────────────

    if layout == "person_claim":
        _render_person_claim(bg, draw, face_path, line1, line2, accent, pad)
        draw = ImageDraw.Draw(bg)   # redraw after pastes

    elif layout == "claim_left":
        _render_claim_left(bg, draw, line1, line2, accent, pad)

    elif layout == "highlight_box":
        _render_highlight_box(bg, draw, line1, line2, accent, box_color, pad)

    elif layout == "bottom_wide":
        _render_bottom_wide(bg, draw, line1, line2, accent, bg_color, pad)

    elif layout == "pure_text":
        _render_pure_text(bg, draw, line1, line2, accent, bg_color, pad)

    elif layout == "full_text":
        _render_full_text(bg, draw, line1, line2, accent, pad)

    elif layout == "split_vs":
        _render_split_vs(bg, draw, line1, line2, accent, bg_color, pad)

    elif layout == "top_banner":
        _render_top_banner(bg, draw, line1, line2, accent, bg_color, pad)

    elif layout == "number_hero":
        _render_number_hero(bg, draw, big_number or line1, line2, accent, pad)

    # ── Shock badge (bottom-right corner) ────────────────────────────────────
    badge = "?" if any(w in title.lower() for w in ("why", "how", "what", "where", "when", "?")) else "!"
    _draw_shock_badge(draw, badge, _load_font(68), _TW - 110, _TH - 110, accent)

    # ── Truth ribbon (bottom-left accent) ────────────────────────────────────
    _draw_truth_ribbon(draw, title, accent)

    # ── Channel branding ──────────────────────────────────────────────────────
    logo_path = Path(__file__).parent.parent / "assets" / "logo.png"
    if logo_path.exists():
        try:
            from PIL import Image as _I
            logo_img = _I.open(logo_path).convert("RGBA").resize((54, 54), _I.LANCZOS)
            bg.paste(logo_img, (pad, _TH - 80), logo_img)
        except Exception:
            draw.text((pad, _TH - 48), "MindBlownFacts", font=font_small,
                      fill=(210, 210, 210), stroke_width=1, stroke_fill=(0, 0, 0))
    else:
        draw.text((pad, _TH - 48), "MindBlownFacts", font=font_small,
                  fill=(210, 210, 210), stroke_width=1, stroke_fill=(0, 0, 0))

    # ── Category pill (top-right) ─────────────────────────────────────────────
    _draw_pill(draw, intent, font_small, _TW - 180, 26, pill_color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(str(out_path), "JPEG", quality=95)
    log.info("  Thumbnail: layout=%s line1='%s' line2='%s' → %s",
             layout, line1, line2, out_path.name)
    return out_path


# ── Layout renderers ──────────────────────────────────────────────────────────

def _render_claim_left(bg, draw, line1: str, line2: str, accent: tuple, pad: int):
    """
    Strong dark gradient left 50% → image clearly visible right 50%.
    Line 1: accent color, 150px — the shocking noun/subject
    Line 2: white, 100px — the predicate/implication
    Modeled after: "DISTANCE IS / AN ILLUSION", "WHAT MOVED / INSIDE THE SUN?"
    """
    from PIL import Image, ImageDraw as _ID
    grad = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d    = _ID.Draw(grad)
    for x in range(_TW):
        if x < int(_TW * 0.44):
            alpha = 215
        elif x < int(_TW * 0.72):
            alpha = int(215 * (1.0 - (x - _TW * 0.44) / (_TW * 0.28)))
        else:
            alpha = 0
        d.line([(x, 0), (x, _TH)], fill=(0, 0, 0, alpha))
    result = Image.alpha_composite(bg.convert("RGBA"), grad).convert("RGB")
    bg.paste(result)

    zone_w  = int(_TW * 0.58)
    l1_sz   = 148 if len(line1.split()) <= 2 else 118
    l2_sz   = 96  if len(line1.split()) <= 2 else 80

    font_l1 = _load_font(l1_sz)
    font_l2 = _load_font(l2_sz)

    l1_lines = textwrap.wrap(line1, width=max(4, int(zone_w / (l1_sz * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(4, int(zone_w / (l2_sz * 0.55))))[:2] if line2 else []

    total_h = len(l1_lines) * (l1_sz + 8) + (16 + len(l2_lines) * (l2_sz + 6) if l2_lines else 0)
    y = (_TH - total_h) // 2

    for i, line in enumerate(l1_lines):
        _draw_glow_text(draw, (pad, y + i * (l1_sz + 8)), line, font_l1, accent, accent)
    if l2_lines:
        y2 = y + len(l1_lines) * (l1_sz + 8) + 16
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * (l2_sz + 6)), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))


def _render_highlight_box(bg, draw, line1: str, line2: str, accent: tuple,
                          box_color: tuple, pad: int):
    """
    Bright colored rectangle behind text on dramatic image background.
    Modeled after: "DO YOU HAVE MACHIAVELLIAN INTELLIGENCE?" yellow box style.
    The box is vivid (category color), text inside is white + bold.
    """
    from PIL import Image, ImageDraw as _ID
    # Light darkening of the whole image so box stands out
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 80))
    result  = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    font_l1 = _load_font(110)
    font_l2 = _load_font(72)

    zone_w  = int(_TW * 0.64)
    l1_lines = textwrap.wrap(line1, width=max(4, int(zone_w / (110 * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(5, int(zone_w / (72 * 0.55))))[:2] if line2 else []

    # Measure total text block
    block_w = zone_w
    block_h = (len(l1_lines) * 120 + (14 + len(l2_lines) * 82) if l2_lines else len(l1_lines) * 120)
    bx = pad - 16
    by = (_TH - block_h) // 2 - 18
    bw = bx + block_w + 32
    bh = by + block_h + 36

    # Colored rectangle with slight rounded look (border)
    draw.rectangle([bx, by, bw, bh], fill=(*box_color, 230))
    # Accent top border strip
    draw.rectangle([bx, by, bw, by + 8], fill=accent)

    y = by + 28
    for i, line in enumerate(l1_lines):
        draw.text((pad, y + i * 120), line, font=font_l1,
                  fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    if l2_lines:
        y2 = y + len(l1_lines) * 120 + 14
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * 82), line, font=font_l2,
                      fill=accent, stroke_width=2, stroke_fill=(0, 0, 0))


def _render_bottom_wide(bg, draw, line1: str, line2: str, accent: tuple,
                        bg_color: tuple, pad: int):
    """
    Full dramatic image top 58% — solid dark band bottom 42% with wide bold text.
    Accent line separates image from band.
    Modeled after: "IMPOSSIBLE DISTANCE", "SCIENCE CRACKS TWO QUANTUM BARRIERS"
    """
    from PIL import Image, ImageDraw as _ID
    band_y = int(_TH * 0.58)
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d = _ID.Draw(overlay)
    # Solid band
    d.rectangle([0, band_y, _TW, _TH], fill=(*bg_color, 240))
    # Gradient fade at top of band (blend zone)
    for y in range(band_y - 30, band_y):
        alpha = int(240 * (y - (band_y - 30)) / 30)
        d.line([(0, y), (_TW, y)], fill=(*bg_color, alpha))
    result = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    # Accent border line at top of band
    draw.rectangle([0, band_y, _TW, band_y + 6], fill=accent)

    font_l1 = _load_font(120)
    font_l2 = _load_font(72)
    zone_w  = _TW - 2 * pad
    l1_lines = textwrap.wrap(line1, width=max(5, int(zone_w / (120 * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(6, int(zone_w / (72 * 0.55))))[:1] if line2 else []

    band_h   = _TH - band_y
    block_h  = len(l1_lines) * 130 + (14 + len(l2_lines) * 80 if l2_lines else 0)
    y        = band_y + 6 + (band_h - block_h) // 2

    for i, line in enumerate(l1_lines):
        _draw_glow_text(draw, (pad, y + i * 130), line, font_l1, accent, accent)
    if l2_lines:
        y2 = y + len(l1_lines) * 130 + 14
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * 80), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))


def _render_pure_text(bg, draw, line1: str, line2: str, accent: tuple,
                      bg_color: tuple, pad: int):
    """
    Near-black overlay — text IS the visual. Text fills most of the frame.
    Modeled after: "99.9999% IS NOTHING." on black with "THAT'S YOU" arrow.
    The background image is barely visible (very dark). Text has maximum contrast.
    """
    from PIL import Image
    overlay = Image.new("RGBA", (_TW, _TH), (*bg_color, 210))
    result  = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    l1_words = len(line1.split())
    l1_sz    = 200 if l1_words == 1 else (160 if l1_words == 2 else 128)
    l2_sz    = 96
    font_l1  = _load_font(l1_sz)
    font_l2  = _load_font(l2_sz)

    zone_w   = _TW - 2 * pad
    l1_lines = textwrap.wrap(line1, width=max(3, int(zone_w / (l1_sz * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(4, int(zone_w / (l2_sz * 0.55))))[:2] if line2 else []

    total_h  = len(l1_lines) * (l1_sz + 12) + (20 + len(l2_lines) * (l2_sz + 8) if l2_lines else 0)
    y        = (_TH - total_h) // 2

    # Line 1 — accent color, massive
    for i, line in enumerate(l1_lines):
        bbox = draw.textbbox((0, 0), line, font=font_l1)
        lw   = bbox[2] - bbox[0]
        x    = (_TW - lw) // 2    # center-aligned
        _draw_glow_text(draw, (x, y + i * (l1_sz + 12)), line, font_l1, accent, accent)

    # Line 2 — white, smaller
    if l2_lines:
        y2 = y + len(l1_lines) * (l1_sz + 12) + 20
        for i, line in enumerate(l2_lines):
            bbox = draw.textbbox((0, 0), line, font=font_l2)
            lw   = bbox[2] - bbox[0]
            x    = (_TW - lw) // 2
            draw.text((x, y2 + i * (l2_sz + 8)), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))


def _render_full_text(bg, draw, line1: str, line2: str, accent: tuple, pad: int):
    """
    Heavy dark overlay, large bold text dominates full frame left-aligned.
    Modeled after: "THE REASON THEY HURT YOU AND ACT LIKE NOTHING EVER HAPPENED !!!"
    Works best for psychology/emotional topics with multi-word claims.
    """
    from PIL import Image
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 175))
    result  = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    # Yellow/accent colored highlight box behind line 1
    font_l1  = _load_font(108)
    font_l2  = _load_font(76)
    zone_w   = _TW - 2 * pad
    l1_lines = textwrap.wrap(line1, width=max(4, int(zone_w / (108 * 0.54))))[:3]
    l2_lines = textwrap.wrap(line2, width=max(5, int(zone_w / (76 * 0.54))))[:2] if line2 else []

    block_h = len(l1_lines) * 118 + (18 + len(l2_lines) * 86 if l2_lines else 0)
    y = (_TH - block_h) // 2

    # Draw accent highlight box behind each l1 line
    for i, line in enumerate(l1_lines):
        bbox = draw.textbbox((0, 0), line, font=font_l1)
        lw   = bbox[2] - bbox[0]
        lh   = bbox[3] - bbox[1]
        ly   = y + i * 118
        # Yellow/accent box
        draw.rectangle([pad - 10, ly - 6, pad + lw + 10, ly + lh + 6],
                       fill=(*accent, 220))
        draw.text((pad, ly), line, font=font_l1, fill=(0, 0, 0))  # black text on accent

    if l2_lines:
        y2 = y + len(l1_lines) * 118 + 18
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * 86), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))


def _render_split_vs(bg, draw, line1: str, line2: str, accent: tuple,
                     bg_color: tuple, pad: int):
    """
    Left dark panel with CLAIM, right shows full image.
    A vertical divider line with accent color separates the two halves.
    Modeled after: "MYTHS vs REALITY", "WE ARE HERE" type thumbnails.
    """
    from PIL import Image, ImageDraw as _ID
    mid = _TW // 2

    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d = _ID.Draw(overlay)
    # Solid dark left half
    d.rectangle([0, 0, mid, _TH], fill=(*bg_color, 230))
    # Gradient blend on right edge of dark panel
    for x in range(mid, min(mid + 60, _TW)):
        alpha = int(230 * (1.0 - (x - mid) / 60))
        d.line([(x, 0), (x, _TH)], fill=(*bg_color, alpha))
    result = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    # Accent vertical divider line
    draw.rectangle([mid - 4, 0, mid + 4, _TH], fill=accent)

    font_l1  = _load_font(118)
    font_l2  = _load_font(80)
    zone_w   = mid - 2 * pad
    l1_lines = textwrap.wrap(line1, width=max(3, int(zone_w / (118 * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(4, int(zone_w / (80 * 0.55))))[:2] if line2 else []

    block_h = len(l1_lines) * 128 + (14 + len(l2_lines) * 88 if l2_lines else 0)
    y = (_TH - block_h) // 2

    for i, line in enumerate(l1_lines):
        _draw_glow_text(draw, (pad, y + i * 128), line, font_l1, accent, accent)
    if l2_lines:
        y2 = y + len(l1_lines) * 128 + 14
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * 88), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))

    # Label on right half: shortened title concept
    font_r = _load_font(64)
    right_x = mid + 20
    right_words = [w for w in line2.split() if w.lower() not in _STOP_WORDS][:3]
    right_text  = " ".join(right_words).upper() if right_words else "TRUTH"
    draw.text((right_x, _TH // 2 - 40), right_text, font=font_r,
              fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))


def _render_top_banner(bg, draw, line1: str, line2: str, accent: tuple,
                       bg_color: tuple, pad: int):
    """
    Dark banner at top 36% — image visible bottom 64%.
    Accent bottom-border line at bottom of banner.
    Modeled after: BBC Earth style, clean top-title thumbnails.
    """
    from PIL import Image, ImageDraw as _ID
    band_h = int(_TH * 0.36)
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d = _ID.Draw(overlay)
    d.rectangle([0, 0, _TW, band_h], fill=(*bg_color, 235))
    for y in range(band_h, min(band_h + 40, _TH)):
        alpha = int(235 * (1.0 - (y - band_h) / 40))
        d.line([(0, y), (_TW, y)], fill=(*bg_color, alpha))
    result = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    # Accent line at bottom of band
    draw.rectangle([0, band_h - 6, _TW, band_h], fill=accent)

    font_l1  = _load_font(118)
    font_l2  = _load_font(76)
    zone_w   = _TW - 2 * pad
    l1_lines = textwrap.wrap(line1, width=max(4, int(zone_w / (118 * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(5, int(zone_w / (76 * 0.55))))[:1] if line2 else []

    block_h = len(l1_lines) * 126 + (12 + len(l2_lines) * 82 if l2_lines else 0)
    y = (band_h - block_h) // 2

    for i, line in enumerate(l1_lines):
        _draw_glow_text(draw, (pad, y + i * 126), line, font_l1, accent, accent)
    if l2_lines:
        y2 = y + len(l1_lines) * 126 + 12
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * 82), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))


def _render_number_hero(bg, draw, number: str, subtitle: str, accent: tuple, pad: int):
    """
    Giant number centered, keyword below.
    Proven highest-CTR style for "N facts / N% / N billion" type topics.
    """
    from PIL import Image
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 155))
    result  = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.paste(result)

    num_sz   = 220 if len(number) <= 4 else (175 if len(number) <= 8 else 138)
    font_num = _load_font(num_sz)
    font_sub = _load_font(80)

    bbox_n = draw.textbbox((0, 0), number, font=font_num)
    nw = bbox_n[2] - bbox_n[0]
    nx = (_TW - nw) // 2
    ny = int(_TH * 0.10)
    _draw_glow_text(draw, (nx, ny), number, font_num, accent, accent)

    if subtitle:
        sub_lines = textwrap.wrap(subtitle, width=max(5, int((_TW - 2*pad) / (80 * 0.54))))[:2]
        y = ny + num_sz + 24
        for i, line in enumerate(sub_lines):
            bbox = draw.textbbox((0, 0), line, font=font_sub)
            lw   = bbox[2] - bbox[0]
            x    = (_TW - lw) // 2
            draw.text((x, y + i * 90), line, font=font_sub,
                      fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))


def _render_person_claim(bg, draw, face_path, line1: str, line2: str,
                         accent: tuple, pad: int):
    """
    #1 highest-CTR YouTube thumbnail format — used by every top educational channel:
    - RIGHT 48%: real shocked/amazed human face (from Pexels portrait photo)
    - LEFT 55%: dark overlay + large 2-line claim in accent + white
    - Blended edge where face meets dark side

    Psychology: viewer sees EMOTION on face → reads TEXT → clicks.
    The human face triggers a mirror-neuron response — viewers feel the shock
    before they even read the words.
    """
    from PIL import Image, ImageDraw as _ID
    W, H = _TW, _TH

    # Strong dark gradient covering left 50%, fading to transparent at 72%
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = _ID.Draw(grad)
    for x in range(W):
        if x < int(W * 0.50):
            alpha = 225
        elif x < int(W * 0.72):
            alpha = int(225 * (1.0 - (x - W * 0.50) / (W * 0.22)))
        else:
            alpha = 0
        d.line([(x, 0), (x, H)], fill=(0, 0, 0, alpha))
    result = Image.alpha_composite(bg.convert("RGBA"), grad).convert("RGB")
    bg.paste(result)

    # Paste the human face on the right half
    if face_path:
        try:
            face = Image.open(face_path).convert("RGB")
            fw, fh = face.size
            target_w = int(W * 0.50)
            target_h = H
            scale = max(target_w / fw, target_h / fh)
            nw, nh = int(fw * scale), int(fh * scale)
            face = face.resize((nw, nh), Image.LANCZOS)
            # Center horizontally; bias upward so face (not chest) is visible
            xo = (nw - target_w) // 2
            yo = max(0, (nh - target_h) // 5)
            face_crop = face.crop((xo, yo, xo + target_w, yo + target_h))
            bg.paste(face_crop, (W - target_w, 0))
            log.debug("Face pasted (%dx%d crop from %dx%d)", target_w, target_h, nw, nh)
        except Exception as exc:
            log.debug("Face paste failed: %s", exc)

    # Blend edge: gradient shadow at the face/text boundary so they merge cleanly
    edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ed = _ID.Draw(edge)
    blend_start = int(W * 0.47)
    blend_end   = int(W * 0.58)
    for x in range(blend_start, blend_end):
        alpha = int(160 * (1.0 - (x - blend_start) / (blend_end - blend_start)))
        ed.line([(x, 0), (x, H)], fill=(0, 0, 0, alpha))
    merged = Image.alpha_composite(bg.convert("RGBA"), edge).convert("RGB")
    bg.paste(merged)

    # Redraw for ImageDraw after pastes
    draw._image = bg

    # Text on the left
    zone_w  = int(W * 0.58)
    l1_sz   = 148 if len(line1.split()) <= 2 else 112
    l2_sz   = 94  if len(line1.split()) <= 2 else 76
    font_l1 = _load_font(l1_sz)
    font_l2 = _load_font(l2_sz)

    l1_lines = textwrap.wrap(line1, width=max(4, int(zone_w / (l1_sz * 0.55))))[:2]
    l2_lines = textwrap.wrap(line2, width=max(5, int(zone_w / (l2_sz * 0.55))))[:2] if line2 else []

    total_h = len(l1_lines) * (l1_sz + 10) + (16 + len(l2_lines) * (l2_sz + 8) if l2_lines else 0)
    y = (H - total_h) // 2

    for i, line in enumerate(l1_lines):
        _draw_glow_text(draw, (pad, y + i * (l1_sz + 10)), line, font_l1, accent, accent)
    if l2_lines:
        y2 = y + len(l1_lines) * (l1_sz + 10) + 16
        for i, line in enumerate(l2_lines):
            draw.text((pad, y2 + i * (l2_sz + 8)), line, font=font_l2,
                      fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _draw_glow_text(draw, pos: tuple, text: str, font, fill: tuple, glow: tuple) -> None:
    x, y = pos
    for r in (14, 10, 7):
        for dx in range(-r, r + 1, r):
            for dy in range(-r, r + 1, r):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font,
                              fill=glow, stroke_width=r // 2, stroke_fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill, stroke_width=5, stroke_fill=(0, 0, 0))


def _draw_shock_badge(draw, char: str, font, x: int, y: int, accent: tuple) -> None:
    try:
        bbox = draw.textbbox((0, 0), char, font=font)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
    except AttributeError:
        tw = th = 40
    r  = max(tw, th) // 2 + 18
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(15, 15, 15))
    draw.ellipse([x - r, y - r, x + r, y + r], outline=accent, width=5)
    draw.text((x - tw // 2, y - th // 2), char, font=font,
              fill=accent, stroke_width=2, stroke_fill=(0, 0, 0))


def _draw_truth_ribbon(draw, title: str, accent: tuple) -> None:
    title_lower = title.lower()
    ribbon_word = None
    for rw in _RIBBON_POWER:
        if rw.lower() in title_lower:
            ribbon_word = rw
            break
    if not ribbon_word:
        for w in title.split():
            clean = re.sub(r"[^a-z]", "", w.lower())
            if clean in _POWER_WORDS and len(clean) >= 5:
                ribbon_word = clean.upper()
                break
    if not ribbon_word:
        ribbon_word = "REVEALED"

    font_r = _load_font(52)
    try:
        bbox  = draw.textbbox((0, 0), ribbon_word, font=font_r)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = 220, 50

    px, py = 18, 8
    rx, ry = 55, _TH - 158
    rw, rh = tw + px * 2, th + py * 2
    draw.rectangle([rx, ry, rx + rw, ry + rh], fill=(200, 28, 28))
    draw.line([rx, ry, rx + rw, ry], fill=(255, 100, 100), width=3)
    draw.text((rx + px, ry + py), ribbon_word, font=font_r,
              fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))


def _draw_pill(draw, text: str, font, x: int, y: int, color: tuple) -> None:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = 120, 28
    p = 12
    draw.rounded_rectangle([x - p, y - p, x + tw + p, y + th + p], radius=8, fill=color)
    draw.text((x, y), text, font=font, fill=(255, 255, 255))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_number(title: str) -> str:
    patterns = [
        r'\d[\d,]*\s*(?:billion|million|trillion)',
        r'\d[\d,]*\s*(?:thousand)',
        r'\d[\d,.]*\s*(?:km|mph|km/h|ly|°|%)',
        r'\d[\d,]{3,}',
        r'\d+\s*(?:years?|days?|seconds?|meters?)',
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return m.group().strip()
    return ""


def _extract_keyword_and_subtitle(title: str) -> tuple[str, str]:
    words = title.split()
    for i, word in enumerate(words):
        clean = re.sub(r"[^a-z]", "", word.lower())
        if clean in _POWER_WORDS:
            kw_words = [word]
            if (i + 1 < len(words)
                    and re.sub(r"[^a-z]", "", words[i + 1].lower()) not in _STOP_WORDS):
                kw_words.append(words[i + 1])
            keyword  = " ".join(kw_words).upper()
            used_idx = set(range(i, i + len(kw_words)))
            subtitle = " ".join(
                w for j, w in enumerate(words)
                if j not in used_idx
                and re.sub(r"[^a-z]", "", w.lower()) not in _STOP_WORDS
            )[:52]
            return keyword, subtitle

    meaningful = [(i, w) for i, w in enumerate(words)
                  if re.sub(r"[^a-z]", "", w.lower()) not in _STOP_WORDS]
    if len(meaningful) >= 2:
        last_two = meaningful[-2:]
        keyword  = " ".join(w for _, w in last_two).upper()
        used_idx = {i for i, _ in last_two}
        subtitle = " ".join(w for i, w in enumerate(words) if i not in used_idx)[:52]
        return keyword, subtitle
    if meaningful:
        keyword  = meaningful[-1][1].upper()
        used_idx = {meaningful[-1][0]}
        subtitle = " ".join(w for i, w in enumerate(words) if i not in used_idx)[:52]
        return keyword, subtitle

    return title[:24].upper(), ""


def _drama_score(img_path: Path) -> float:
    try:
        from PIL import Image, ImageStat
        img  = Image.open(img_path).convert("RGB").resize((160, 90), Image.LANCZOS)
        gray = img.convert("L")
        contrast  = ImageStat.Stat(gray).stddev[0]
        saturation = sum(ImageStat.Stat(img).stddev) / 3
        return contrast * 0.6 + saturation * 0.4
    except Exception:
        return 0.0


def _load_background(visuals_dir: Path, timeline: dict, intent: str,
                     title: str = "") -> "Image.Image":
    from PIL import Image

    # 1. AI-generated background (HuggingFace SDXL / Pollinations)
    if title:
        ai_path = _fetch_ai_bg(title, intent, visuals_dir)
        if ai_path:
            try:
                return Image.open(ai_path).convert("RGB").resize((_TW, _TH), Image.LANCZOS)
            except Exception as exc:
                log.debug("AI background load failed: %s", exc)

    # 2. Pexels topic-matched real photograph (title keywords + category style)
    if title:
        pex_path = _fetch_pexels_bg(title, intent, visuals_dir)
        if pex_path:
            try:
                return Image.open(pex_path).convert("RGB").resize((_TW, _TH), Image.LANCZOS)
            except Exception as exc:
                log.debug("Pexels bg load failed: %s", exc)

    # 3. Pre-saved thumbnail background from a previous step
    thumb_bg = visuals_dir / "thumbnail_bg.png"
    if thumb_bg.exists() and thumb_bg.stat().st_size > 5_000:
        try:
            return Image.open(thumb_bg).convert("RGB").resize((_TW, _TH), Image.LANCZOS)
        except Exception as exc:
            log.debug("thumbnail_bg.png load failed: %s", exc)

    # 4. Most dramatic image from video scenes (already fetched and topic-relevant)
    best_file  = None
    best_score = -1.0
    for sc in timeline.get("scenes", []):
        if sc.get("clip_type") == "image":
            vf = sc.get("visual_file", "")
            if vf and vf != "CLOSE":
                candidate = visuals_dir / vf
                if candidate.exists():
                    drama = _drama_score(candidate)
                    if drama > best_score:
                        best_file  = candidate
                        best_score = drama

    if best_file:
        try:
            return Image.open(best_file).convert("RGB").resize((_TW, _TH), Image.LANCZOS)
        except Exception as exc:
            log.debug("Video scene background load failed: %s", exc)

    # 5. Solid category colour as last resort
    return Image.new("RGB", (_TW, _TH), _INTENT_BG.get(intent, (10, 10, 40)))


def _load_font(size: int):
    from PIL import ImageFont
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(fp, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()
