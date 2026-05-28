"""
STEP 14 — Thumbnail Generation

Creates a 1280×720 designed thumbnail using Pillow — NOT a frame grab.
Layout:
  • Background: best visual from visuals_dir, darkened + blurred
  • Headline: most surprising sentence from HOOK or PAYOFF, bold white,
    high-contrast yellow shadow, wrapped across 2-3 lines
  • Channel pill at bottom-left
  • Intent category pill at top-right

Falls back to a solid-colour branded card if no visual is available.

Output: temp/thumbnail.jpg  (uploaded separately after video upload)
"""

import logging
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)

_TW, _TH = 1280, 720   # YouTube thumbnail spec

_INTENT_BG: dict[str, tuple[int, int, int]] = {
    "SPACE":     (10,  5,  55),
    "SCIENCE":   (0,  30,  90),
    "HISTORY":   (55, 28,   0),
    "ANIMALS":   (10, 50,   0),
    "NATURE":    (0,  50,  15),
    "GEOGRAPHY": (0,  50,  50),
    "OCEAN":     (0,  30,  70),
    "CULTURE":   (60, 25,   0),
}

_INTENT_PILL_COLOR: dict[str, tuple[int, int, int]] = {
    "SPACE":     (26,  10, 107),
    "SCIENCE":   (0,   85, 170),
    "HISTORY":   (107, 58,   0),
    "ANIMALS":   (26,  92,   0),
    "NATURE":    (0,   92,  26),
    "GEOGRAPHY": (0,  102, 102),
    "OCEAN":     (0,   64, 128),
    "CULTURE":   (122, 53,   0),
}


def generate_thumbnail(
    timeline: dict,
    script: dict,
    visuals_dir: Path,
    out_path: Path,
) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        log.warning("Pillow not installed — thumbnail skipped")
        return out_path

    intent   = timeline.get("intent", "SCIENCE").upper()
    headline = _pick_headline(timeline, script)

    # ── Background ────────────────────────────────────────────────────────────
    bg = _load_background(visuals_dir, timeline, intent)

    # Dark overlay so text is always readable
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 160))
    bg = bg.convert("RGBA")
    bg = Image.alpha_composite(bg, overlay).convert("RGB")

    draw = ImageDraw.Draw(bg)

    # ── Headline text ─────────────────────────────────────────────────────────
    font_headline = _load_font(80)
    font_small    = _load_font(32)

    wrapped = textwrap.wrap(headline, width=22)[:3]   # max 3 lines
    line_h  = 90
    total_h = len(wrapped) * line_h
    y_start = (_TH - total_h) // 2 - 40

    for i, line in enumerate(wrapped):
        y = y_start + i * line_h
        # Shadow
        draw.text((42 + 3, y + 3), line, font=font_headline, fill=(0, 0, 0, 200))
        # Main text
        draw.text((42, y), line, font=font_headline, fill=(255, 230, 0))

    # ── Channel logo or pill (bottom-left) ───────────────────────────────────
    pill_color = _INTENT_PILL_COLOR.get(intent, (0, 85, 170))
    logo_path  = Path(__file__).parent.parent / "assets" / "logo.png"
    if logo_path.exists():
        try:
            logo_img = Image.open(logo_path).convert("RGBA")
            logo_img = logo_img.resize((72, 72), Image.LANCZOS)
            bg.paste(logo_img, (30, _TH - 102), logo_img)
        except Exception:
            _draw_pill(draw, "Visionary Minds", font_small, 40, _TH - 80, pill_color)
    else:
        _draw_pill(draw, "Visionary Minds", font_small, 40, _TH - 80, pill_color)

    # ── Category pill (top-right) ─────────────────────────────────────────────
    _draw_pill(draw, intent, font_small, _TW - 200, 30, pill_color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(str(out_path), "JPEG", quality=95)
    log.info("  Thumbnail generated: %s", out_path.name)
    return out_path


def _pick_headline(timeline: dict, script: dict) -> str:
    """Pick the most curiosity-driving headline for the thumbnail."""
    # Prefer the metadata title — it's already CTR-psychology optimised by the LLM
    title = script.get("metadata", {}).get("title", "").strip()
    if title:
        return _ctr_enhance(title)[:72]

    # Fall back to HOOK text
    for sc in timeline.get("scenes", []):
        if sc.get("segment_label") == "HOOK":
            text = sc.get("script_text", "").strip()
            if text:
                return _ctr_enhance(text)[:72]

    return "The Fact That Changes Everything"


# Trigger words that indicate a title already has CTR psychology baked in
_CTR_POWER_WORDS = {
    "impossible", "hidden", "real", "secret", "nobody", "truth",
    "actually", "scientists", "discovered", "found", "breaks", "never",
    "why", "how", "what", "until", "real reason", "not what",
}

def _ctr_enhance(title: str) -> str:
    """
    If the title already uses curiosity-gap language, return as-is.
    Otherwise wrap in a curiosity-gap frame to improve CTR.
    """
    title_lower = title.lower()
    # Already has CTR power words — trust it
    if any(w in title_lower for w in _CTR_POWER_WORDS):
        return title

    # Generic title — apply curiosity frame
    # Strip trailing period
    clean = title.rstrip(".")
    frames = [
        f"Nobody Told You The Truth About {clean}",
        f"The Real Reason {clean} Will Surprise You",
        f"Scientists Found Something Impossible About {clean}",
    ]
    # Pick shortest that fits thumbnail line wrap
    for f in frames:
        if len(f) <= 72:
            return f
    return clean


def _load_background(visuals_dir: Path, timeline: dict, intent: str) -> "Image.Image":
    from PIL import Image, ImageFilter

    # Pick the highest-scoring scene visual that is an image
    best_file = None
    best_score = -1.0
    for sc in timeline.get("scenes", []):
        if sc.get("clip_type") == "image" and sc.get("clip_score", 0) > best_score:
            vf = sc.get("visual_file", "")
            if vf and vf != "CLOSE":
                candidate = visuals_dir / vf
                if candidate.exists():
                    best_file  = candidate
                    best_score = sc["clip_score"]

    if best_file:
        try:
            img = Image.open(best_file).convert("RGB")
            img = img.resize((_TW, _TH), Image.LANCZOS)
            img = img.filter(ImageFilter.GaussianBlur(radius=3))
            return img
        except Exception as exc:
            log.debug("Background image load failed: %s", exc)

    # Solid colour fallback
    bg_color = _INTENT_BG.get(intent, (10, 10, 40))
    return Image.new("RGB", (_TW, _TH), bg_color)


def _load_font(size: int):
    from PIL import ImageFont
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _draw_pill(draw, text: str, font, x: int, y: int, color: tuple) -> None:
    from PIL import ImageDraw
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)

    pad = 14
    rx0, ry0 = x - pad, y - pad
    rx1, ry1 = x + tw + pad, y + th + pad
    draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=10, fill=color)
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
