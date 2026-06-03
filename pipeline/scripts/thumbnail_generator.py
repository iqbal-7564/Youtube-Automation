"""
STEP 14 — Thumbnail Generation (Viral-Style, 5 Rotating Layouts)

Creates a 1280×720 YouTube thumbnail using Pillow.
Layout is picked by hashing the video title — same video always gets same
layout, but consecutive videos cycle through 5 distinct designs so the
channel feed never looks repetitive.

Layouts:
  0 left        — dark gradient left, big text left, image visible right
  1 center      — full dark overlay, big text centered (single-word impact)
  2 bottom_band — image top 65%, solid dark band bottom 35% with text
  3 top_split   — solid dark band top 38% with text, image bottom 62%
  4 diagonal    — diagonal gradient top-left→bottom-right, text top-left
"""

import logging
import re
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)

_TW, _TH = 1280, 720

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

_INTENT_ACCENT: dict[str, tuple[int, int, int]] = {
    "SPACE":     (255, 220,  50),
    "SCIENCE":   (100, 220, 255),
    "HISTORY":   (255, 200,  80),
    "ANIMALS":   (120, 255, 100),
    "NATURE":    (100, 255, 150),
    "GEOGRAPHY": ( 80, 230, 230),
    "OCEAN":     ( 80, 200, 255),
    "CULTURE":   (255, 180,  80),
}

_LAYOUTS = ["left", "center", "bottom_band", "top_split", "diagonal"]

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
}


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

    keyword, subtitle = _extract_keyword_and_subtitle(title)
    accent     = _INTENT_ACCENT.get(intent, (255, 220, 50))
    pill_color = _INTENT_PILL_COLOR.get(intent, (0, 85, 170))
    layout     = _LAYOUTS[abs(hash(title)) % len(_LAYOUTS)]

    bg = _load_background(visuals_dir, timeline, intent)

    if layout == "left":
        bg = _overlay_left(bg)
    elif layout == "center":
        bg = _overlay_center(bg)
    elif layout == "bottom_band":
        bg = _overlay_bottom_band(bg, intent)
    elif layout == "top_split":
        bg = _overlay_top_split(bg, intent)
    elif layout == "diagonal":
        bg = _overlay_diagonal(bg)

    draw = ImageDraw.Draw(bg)

    # ── Text positioning per layout ───────────────────────────────────────────
    kw_words     = len(keyword.split())
    kw_font_size = 140 if kw_words == 1 else (118 if kw_words == 2 else 96)
    font_kw    = _load_font(kw_font_size)
    font_sub   = _load_font(44)
    font_small = _load_font(30)

    pad = 55

    if layout == "left":
        zone_w  = int(_TW * 0.62)
        x_start = pad
        kw_lines  = textwrap.wrap(keyword,  width=max(5,  int(zone_w / (kw_font_size * 0.56))))[:2]
        sub_lines = textwrap.wrap(subtitle, width=max(10, int(zone_w / (44 * 0.53))))[:2] if subtitle else []
        y_start = _text_y_center(kw_lines, sub_lines, kw_font_size)
        _draw_text_block(draw, kw_lines, sub_lines, x_start, y_start,
                         kw_font_size, font_kw, font_sub, accent)

    elif layout == "center":
        # Single big keyword centered — maximum impact
        kw_font_size = 160 if kw_words == 1 else (130 if kw_words == 2 else 104)
        font_kw   = _load_font(kw_font_size)
        zone_w    = _TW - 2 * pad
        kw_lines  = textwrap.wrap(keyword,  width=max(5, int(zone_w / (kw_font_size * 0.56))))[:2]
        sub_lines = textwrap.wrap(subtitle, width=max(10, int(zone_w / (44 * 0.53))))[:2] if subtitle else []
        y_start   = _text_y_center(kw_lines, sub_lines, kw_font_size)
        for i, line in enumerate(kw_lines):
            bbox = draw.textbbox((0, 0), line, font=font_kw)
            lw   = bbox[2] - bbox[0]
            x    = (_TW - lw) // 2
            y    = y_start + i * (kw_font_size + 10)
            draw.text((x, y), line, font=font_kw, fill=accent,
                      stroke_width=6, stroke_fill=(0, 0, 0))
        if sub_lines:
            sub_y = y_start + len(kw_lines) * (kw_font_size + 10) + 22
            for i, line in enumerate(sub_lines):
                bbox = draw.textbbox((0, 0), line, font=font_sub)
                lw   = bbox[2] - bbox[0]
                x    = (_TW - lw) // 2
                y    = sub_y + i * 52
                draw.text((x, y), line, font=font_sub, fill=(255, 255, 255),
                          stroke_width=2, stroke_fill=(0, 0, 0))

    elif layout == "bottom_band":
        band_y  = int(_TH * 0.63)
        zone_w  = _TW - 2 * pad
        kw_lines  = textwrap.wrap(keyword,  width=max(5,  int(zone_w / (kw_font_size * 0.56))))[:2]
        sub_lines = textwrap.wrap(subtitle, width=max(10, int(zone_w / (44 * 0.53))))[:1] if subtitle else []
        band_h    = _TH - band_y
        block_h   = len(kw_lines) * (kw_font_size + 10) + (22 + len(sub_lines) * 52 if sub_lines else 0)
        y_start   = band_y + (band_h - block_h) // 2
        _draw_text_block(draw, kw_lines, sub_lines, pad, y_start,
                         kw_font_size, font_kw, font_sub, accent)

    elif layout == "top_split":
        band_h  = int(_TH * 0.38)
        zone_w  = _TW - 2 * pad
        kw_lines  = textwrap.wrap(keyword,  width=max(5,  int(zone_w / (kw_font_size * 0.56))))[:2]
        sub_lines = textwrap.wrap(subtitle, width=max(10, int(zone_w / (44 * 0.53))))[:1] if subtitle else []
        block_h   = len(kw_lines) * (kw_font_size + 10) + (22 + len(sub_lines) * 52 if sub_lines else 0)
        y_start   = (band_h - block_h) // 2
        _draw_text_block(draw, kw_lines, sub_lines, pad, y_start,
                         kw_font_size, font_kw, font_sub, accent)

    elif layout == "diagonal":
        zone_w  = int(_TW * 0.55)
        x_start = pad
        kw_lines  = textwrap.wrap(keyword,  width=max(5,  int(zone_w / (kw_font_size * 0.56))))[:2]
        sub_lines = textwrap.wrap(subtitle, width=max(10, int(zone_w / (44 * 0.53))))[:2] if subtitle else []
        y_start   = pad + 20
        _draw_text_block(draw, kw_lines, sub_lines, x_start, y_start,
                         kw_font_size, font_kw, font_sub, accent)

    # ── Channel logo / name (bottom-left) ─────────────────────────────────────
    logo_path = Path(__file__).parent.parent / "assets" / "logo.png"
    if logo_path.exists():
        try:
            from PIL import Image
            logo_img = Image.open(logo_path).convert("RGBA")
            logo_img = logo_img.resize((58, 58), Image.LANCZOS)
            bg.paste(logo_img, (pad, _TH - 84), logo_img)
        except Exception:
            draw.text((pad, _TH - 50), "MindBlownFacts", font=font_small,
                      fill=(200, 200, 200), stroke_width=1, stroke_fill=(0, 0, 0))
    else:
        draw.text((pad, _TH - 50), "MindBlownFacts", font=font_small,
                  fill=(200, 200, 200), stroke_width=1, stroke_fill=(0, 0, 0))

    # ── Category pill (top-right) ─────────────────────────────────────────────
    _draw_pill(draw, intent, font_small, _TW - 185, 28, pill_color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(str(out_path), "JPEG", quality=95)
    log.info("  Thumbnail: layout=%s keyword='%s'  → %s",
             layout, keyword, out_path.name)
    return out_path


# ── Overlay builders ──────────────────────────────────────────────────────────

def _overlay_left(bg: "Image.Image") -> "Image.Image":
    """Dark gradient left → transparent right."""
    from PIL import Image, ImageDraw
    grad = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d    = ImageDraw.Draw(grad)
    for x in range(_TW):
        alpha = int(215 * max(0.0, 1.0 - x / (_TW * 0.72)))
        d.line([(x, 0), (x, _TH)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(bg.convert("RGBA"), grad).convert("RGB")


def _overlay_center(bg: "Image.Image") -> "Image.Image":
    """Uniform semi-dark overlay — text readable anywhere."""
    from PIL import Image
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 155))
    return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")


def _overlay_bottom_band(bg: "Image.Image", intent: str) -> "Image.Image":
    """Solid dark band at bottom 37% — image visible top."""
    from PIL import Image, ImageDraw
    band_y  = int(_TH * 0.63)
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d       = ImageDraw.Draw(overlay)
    base    = _INTENT_BG.get(intent, (10, 10, 40))
    d.rectangle([0, band_y, _TW, _TH], fill=(*base, 230))
    # Thin gradient blend at top of band
    for y in range(band_y, min(band_y + 40, _TH)):
        alpha = int(230 * (y - band_y) / 40)
        d.line([(0, y), (_TW, y)], fill=(*base, alpha))
    return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")


def _overlay_top_split(bg: "Image.Image", intent: str) -> "Image.Image":
    """Solid dark band at top 38% — image visible bottom."""
    from PIL import Image, ImageDraw
    band_h  = int(_TH * 0.38)
    overlay = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d       = ImageDraw.Draw(overlay)
    base    = _INTENT_BG.get(intent, (10, 10, 40))
    d.rectangle([0, 0, _TW, band_h], fill=(*base, 235))
    for y in range(band_h, min(band_h + 40, _TH)):
        alpha = int(235 * (1 - (y - band_h) / 40))
        d.line([(0, y), (_TW, y)], fill=(*base, alpha))
    return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")


def _overlay_diagonal(bg: "Image.Image") -> "Image.Image":
    """Diagonal gradient — dark top-left, transparent bottom-right."""
    from PIL import Image, ImageDraw
    grad = Image.new("RGBA", (_TW, _TH), (0, 0, 0, 0))
    d    = ImageDraw.Draw(grad)
    for x in range(_TW):
        for y in range(0, _TH, 4):
            ratio = max(0.0, 1.0 - (x / _TW + y / _TH) / 1.3)
            d.line([(x, y), (x, y + 4)], fill=(0, 0, 0, int(220 * ratio)))
    return Image.alpha_composite(bg.convert("RGBA"), grad).convert("RGB")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _text_y_center(kw_lines: list, sub_lines: list, kw_font_size: int) -> int:
    kw_h    = len(kw_lines) * (kw_font_size + 10)
    sub_h   = (22 + len(sub_lines) * 52) if sub_lines else 0
    return (_TH - kw_h - sub_h) // 2


def _draw_text_block(draw, kw_lines: list, sub_lines: list,
                     x: int, y: int, kw_font_size: int,
                     font_kw, font_sub, accent: tuple) -> None:
    for i, line in enumerate(kw_lines):
        draw.text((x, y + i * (kw_font_size + 10)), line,
                  font=font_kw, fill=accent,
                  stroke_width=5, stroke_fill=(0, 0, 0))
    if sub_lines:
        sub_y = y + len(kw_lines) * (kw_font_size + 10) + 22
        for i, line in enumerate(sub_lines):
            draw.text((x, sub_y + i * 52), line,
                      font=font_sub, fill=(255, 255, 255),
                      stroke_width=2, stroke_fill=(0, 0, 0))


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

    meaningful = [
        (i, w) for i, w in enumerate(words)
        if re.sub(r"[^a-z]", "", w.lower()) not in _STOP_WORDS
    ]
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


def _load_background(visuals_dir: Path, timeline: dict, intent: str) -> "Image.Image":
    from PIL import Image
    best_file  = None
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
            return img.resize((_TW, _TH), Image.LANCZOS)
        except Exception as exc:
            log.debug("Background load failed: %s", exc)
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


def _draw_pill(draw, text: str, font, x: int, y: int, color: tuple) -> None:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)
    pad = 12
    draw.rounded_rectangle(
        [x - pad, y - pad, x + tw + pad, y + th + pad],
        radius=8, fill=color,
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
