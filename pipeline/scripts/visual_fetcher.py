"""
STEP 6 — Visual Fetch (Pexels / Pixabay)

For each scene:
  1. Groq converts scene keywords + emotion + shot_type → optimised search query
  2. Pexels is tried first (per_page=15, size=large, original URL);
     Pixabay is the fallback (per_page=15, min_width=1920, imageURL preferred)
  3. Up to 15 candidate photos are iterated per source; the first one whose
     MD5 hash is not in the persistent image registry is selected.
  4. Image saved to visuals_dir as scene_{id}_visual.png

Image deduplication — two levels:
  - Query-level  : used_prompts.json tracks query hashes (prevents same search
                   across videos, forcing modifier suffixes)
  - Content-level: used_images.json tracks MD5 hashes of downloaded images
                   (prevents the same photo appearing twice, even if fetched
                   via a different query)
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"

MAX_RETRIES   = 3
RETRY_BASE_S  = 5

_HF_MODEL_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
_HF_KEYS = [
    os.getenv("HUGGINGFACE_API_KEY_1", "").strip(),
    os.getenv("HUGGINGFACE_API_KEY_2", "").strip(),
    os.getenv("HUGGINGFACE_API_KEY_3", "").strip(),
    os.getenv("HUGGINGFACE_API_KEY_4", "").strip(),
    os.getenv("HUGGINGFACE_API_KEY_5", "").strip(),
]

_LOGS_DIR = Path(__file__).parent.parent / "logs"

# Query registry — prevents reusing the same search string across videos
PROMPT_REGISTRY  = _LOGS_DIR / "used_prompts.json"
REGISTRY_LIMIT   = 300

# Image registry — prevents the same photo content appearing in any two videos
IMAGE_REGISTRY       = _LOGS_DIR / "used_images.json"
IMAGE_REGISTRY_LIMIT = 2000      # ~180 days at 3 videos/day × 10 scenes

# Modifiers cycled when a duplicate query is detected
_UNIQUE_MODIFIERS = [
    "different angle", "alternative perspective", "unique composition",
    "contrasting viewpoint", "shifted framing", "varied lighting",
    "opposite vantage point", "distinct atmosphere",
]

# Shot types that produce naturally tall subjects — prefer portrait orientation
_PORTRAIT_SHOTS = {"EXTREME_CLOSE", "CLOSE"}


# ── Main entry ────────────────────────────────────────────────────────────────

def _warmup_huggingface() -> None:
    keys = [k for k in _HF_KEYS if k]
    if not keys:
        return
    try:
        r = requests.post(
            _HF_MODEL_URL,
            headers={"Authorization": f"Bearer {keys[0]}"},
            json={"inputs": "warm up", "parameters": {"num_inference_steps": 1,
                                                    "width": 512, "height": 512}},
            timeout=45,
        )
        if r.status_code == 503:
            log.info("HuggingFace warming up — waiting 30s")
            time.sleep(30)
        else:
            log.info("HuggingFace model ready")
    except Exception as exc:
        log.debug("HuggingFace warmup: %s", exc)


def fetch_visuals(timeline: dict, visuals_dir: Path) -> dict:
    """
    Input:  timeline dict with scenes[] containing visual_keywords, emotion,
            shot_type, scene_id, duration_ms; plus width, height, intent fields
    Output: same timeline dict with each scene updated:
            visual_file (str filename), clip_type ("image"/"black"), clip_score (float)
    """
    visuals_dir.mkdir(parents=True, exist_ok=True)

    # Remove PNG files from previous runs (> 2 h old) so images are never reused
    _cleanup_stale_visuals(visuals_dir, max_age_hours=2)

    W, H   = timeline["width"], timeline["height"]
    intent = timeline.get("intent", "SCIENCE")

    # Load both registries
    used_registry      = _load_prompt_registry()    # list[str] — query hashes
    used_img_registry  = _load_image_registry()     # set[str]  — image MD5 hashes
    session_img_hashes: set[str] = set()            # added this run (merged at end)

    def _known_images() -> set[str]:
        return used_img_registry | session_img_hashes

    for sc in timeline["scenes"]:
        # Close scene is a branded card — skip visual fetch
        if sc.get("clip_type") == "close" or sc.get("visual_keyword") == "CLOSE":
            sc.update(visual_file="CLOSE", clip_type="close", clip_score=1.0)
            sc["extra_visual_files"] = []
            continue

        scene_id  = sc["scene_id"]
        dur_s     = sc["duration_ms"] / 1000
        kw_list   = sc.get("visual_keywords") or [sc["visual_keyword"]]
        emotion   = sc.get("emotion", "neutral")
        shot_type = sc.get("shot_type", "MEDIUM")

        out_path  = visuals_dir / f"scene_{scene_id}_visual.png"

        # Step 1 — Build search query via Groq (falls back to keyword join)
        # 1s delay between scenes — key 2 rotates in on 429 so we stay
        # under the 30 RPM limit without long waits.
        if scene_id > 1:
            time.sleep(1.0)
        raw_query = _groq_to_search_query(
            keywords  = kw_list,
            emotion   = emotion,
            shot_type = shot_type,
            intent    = intent,
        )

        # Ensure the query is unique within this video and across recent videos
        query = _ensure_unique_query(raw_query, session_img_hashes, used_registry, scene_id)
        log.info("Scene %d | query: %s", scene_id, query)

        qh = _prompt_hash(query)
        used_registry.append(qh)

        # Step 2 — Fetch primary image: HuggingFace → Pexels → Pixabay → black clip
        success = _huggingface_fetch(query, out_path, _known_images())

        if not success:
            log.debug("Scene %d: HuggingFace failed — trying Pexels", scene_id)
            success = _pexels_fetch(query, out_path, shot_type, _known_images())

        if not success:
            log.warning("Scene %d: Pexels failed — trying Pixabay", scene_id)
            success = _pixabay_fetch(query, out_path, _known_images())

        if success and not _validate_image(out_path, scene_id):
            out_path.unlink(missing_ok=True)
            success = False

        if success:
            h = _img_hash(out_path)
            if h in _known_images():
                # Content-level duplicate — fetch alternate
                log.warning("Scene %d: duplicate image content — fetching alternate", scene_id)
                alt_q    = _ensure_unique_query(
                    _fallback_query(kw_list[1:] if len(kw_list) > 1 else kw_list),
                    session_img_hashes, used_registry, scene_id + 5000,
                )
                alt_path = visuals_dir / f"scene_{scene_id}_visual_alt.png"
                alt_ok   = (_pexels_fetch(alt_q, alt_path, shot_type, _known_images()) or
                            _pixabay_fetch(alt_q, alt_path, _known_images()))
                if alt_ok and _validate_image(alt_path, scene_id):
                    out_path.unlink(missing_ok=True)
                    alt_path.rename(out_path)
                    h = _img_hash(out_path)
                else:
                    alt_path.unlink(missing_ok=True)
            session_img_hashes.add(h)

        if success:
            sc["visual_file"]  = out_path.name
            sc["clip_type"]    = "image"
            sc["clip_score"]   = 1.0
        else:
            log.warning("Scene %d: all sources failed — black fallback", scene_id)
            bp = _black_clip(
                visuals_dir / f"scene_{scene_id}_visual.mp4", dur_s, W, H
            )
            sc["visual_file"] = bp.name
            sc["clip_type"]   = "black"
            sc["clip_score"]  = 0.0

        sc["retry_count"] = 0

        # Step 3 — Always fetch a 2nd image per scene for slideshow variety
        extra_files: list[str] = []
        if success:
            alt_query  = _ensure_unique_query(
                query + " alternative view",
                session_img_hashes, used_registry, scene_id + 1000
            )
            extra_path = visuals_dir / f"scene_{scene_id}_visual_b.png"
            extra_ok   = (_huggingface_fetch(alt_query, extra_path, _known_images()) or
                          _pexels_fetch(alt_query, extra_path, shot_type, _known_images()) or
                          _pixabay_fetch(alt_query, extra_path, _known_images()))
            if extra_ok and _validate_image(extra_path, scene_id):
                eh = _img_hash(extra_path)
                if eh not in _known_images():
                    session_img_hashes.add(eh)
                    extra_files.append(extra_path.name)
                    log.info("Scene %d | extra image: %s", scene_id, extra_path.name)
                else:
                    extra_path.unlink(missing_ok=True)
            else:
                extra_path.unlink(missing_ok=True)

        sc["extra_visual_files"] = extra_files

    # Persist both registries
    _save_prompt_registry(used_registry)
    _save_image_registry(used_img_registry | session_img_hashes)

    return timeline


# ── Image deduplication helpers ───────────────────────────────────────────────

def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _load_prompt_registry() -> list[str]:
    try:
        if PROMPT_REGISTRY.exists():
            data = json.loads(PROMPT_REGISTRY.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-REGISTRY_LIMIT:]
    except Exception as exc:
        log.debug("Prompt registry load error: %s", exc)
    return []


def _save_prompt_registry(registry: list[str]) -> None:
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        PROMPT_REGISTRY.write_text(
            json.dumps(registry[-REGISTRY_LIMIT:], indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("Prompt registry save error: %s", exc)


def _load_image_registry() -> set[str]:
    try:
        if IMAGE_REGISTRY.exists():
            data = json.loads(IMAGE_REGISTRY.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data[-IMAGE_REGISTRY_LIMIT:])
    except Exception as exc:
        log.debug("Image registry load error: %s", exc)
    return set()


def _save_image_registry(hashes: set[str]) -> None:
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        trimmed = list(hashes)[-IMAGE_REGISTRY_LIMIT:]
        IMAGE_REGISTRY.write_text(
            json.dumps(trimmed, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("Image registry save error: %s", exc)


def _ensure_unique_query(
    query: str,
    session_img_hashes: set[str],
    used_registry: list[str],
    scene_id: int,
) -> str:
    registry_set = set(used_registry)
    modifier_idx = 0
    current      = query

    for _ in range(len(_UNIQUE_MODIFIERS) + 1):
        qh = _prompt_hash(current)
        if qh not in registry_set:
            return current
        if modifier_idx < len(_UNIQUE_MODIFIERS):
            mod     = _UNIQUE_MODIFIERS[modifier_idx]
            current = f"{query} {mod}"
            modifier_idx += 1
        else:
            current = f"{query} scene {scene_id}"
            break

    return current


def _cleanup_stale_visuals(visuals_dir: Path, max_age_hours: int = 2) -> None:
    cutoff = time.time() - max_age_hours * 3600
    for pattern in ("scene_*_visual.png", "scene_*_visual_b.png", "scene_*_visual_alt.png"):
        for f in visuals_dir.glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    log.debug("Removed stale visual: %s", f.name)
            except Exception:
                pass


# ── Groq: scene metadata → search query ──────────────────────────────────────

def _groq_to_search_query(
    keywords:  list[str],
    emotion:   str,
    shot_type: str,
    intent:    str,
) -> str:
    api_keys = [
        os.getenv("GROQ_API_KEY_1", "").strip(),
        os.getenv("GROQ_API_KEY_2", "").strip(),
    ]
    api_keys = [k for k in api_keys if k]
    if not api_keys:
        return _fallback_query(keywords)
    api_key = api_keys[0]

    system_prompt = (
        "You convert educational video scene metadata into stock-photo search queries.\n"
        "Rules:\n"
        "- Output ONLY the search query. No explanation, no preamble, no quotes.\n"
        "- 4 to 7 words.\n"
        "- Think: what would a PHOTOGRAPHER actually photograph for this scene?\n"
        "  Translate abstract/scientific concepts into visible, physical subjects.\n"
        "  BAD: 'neutron star explosion'  (no stock photos exist)\n"
        "  GOOD: 'bright star night sky cosmic'\n"
        "  BAD: 'DNA CRISPR editing'\n"
        "  GOOD: 'scientist microscope laboratory closeup'\n"
        "  BAD: 'Vikings discovering America'\n"
        "  GOOD: 'ancient wooden ship ocean voyage'\n"
        "- Match the emotion and shot type to the visual mood.\n"
        "- Use concrete, searchable nouns and adjectives only.\n"
        "- Never use abstract words: 'concept', 'idea', 'mystery', 'fact', 'truth'."
    )

    user_message = (
        f"Keywords: {', '.join(keywords)}\n"
        f"Emotion: {emotion}\n"
        f"Shot type: {shot_type}\n"
        f"Category: {intent}\n"
        "Generate a stock-photo search query that will find a visually relevant image."
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(
                GROQ_API_BASE,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       GROQ_MODEL,
                    "messages":    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_message},
                    ],
                    "max_tokens":  50,
                    "temperature": 0.4,
                },
                timeout=15,
            )
            if r.ok:
                query = r.json()["choices"][0]["message"]["content"].strip()
                return " ".join(query.split()[:7])
            elif r.status_code == 429:
                # Rate limited — rotate to next key immediately
                if len(api_keys) > 1:
                    api_key = api_keys[1]
                    log.info("Groq 429 — rotated to key 2")
                else:
                    wait = RETRY_BASE_S * attempt
                    log.warning("Groq 429 rate limit — waiting %ds", wait)
                    time.sleep(wait)
            else:
                log.warning("Groq query API %d: %s", r.status_code, r.text[:200])
                break
        except requests.exceptions.ConnectionError as exc:
            wait = RETRY_BASE_S * attempt
            log.warning("Groq connection error (attempt %d/%d) — waiting %ds: %s",
                        attempt, MAX_RETRIES, wait, str(exc)[:120])
            time.sleep(wait)
        except requests.exceptions.InvalidHeader as exc:
            log.error("GROQ_API_KEY contains illegal characters — fix the env var: %s", exc)
            break
        except Exception as exc:
            log.warning("Groq query call failed: %s", exc)
            break

    return _fallback_query(keywords)


def _huggingface_fetch(query: str, out_path: Path,
                       avoid_hashes: set[str] | None = None) -> bool:
    keys = [k for k in _HF_KEYS if k]
    if not keys:
        return False
    avoid  = avoid_hashes or set()
    prompt = f"{query}, photorealistic, cinematic, dramatic lighting, high quality"
    for key in keys:
        for attempt in range(2):
            try:
                r = requests.post(
                    _HF_MODEL_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"inputs": prompt, "parameters": {"num_inference_steps": 8,
                                                        "width": 1280, "height": 720}},
                    timeout=60,
                )
                if r.status_code == 503:
                    log.debug("HuggingFace: model loading — waiting 20s")
                    time.sleep(20)
                    continue
                if r.status_code == 429:
                    log.debug("HuggingFace: rate limit key …%s — trying next", key[-4:])
                    break
                if not r.ok or len(r.content) < 1000:
                    log.debug("HuggingFace: %d bad response", r.status_code)
                    break
                tmp = out_path.with_suffix(".hf.tmp.png")
                tmp.write_bytes(r.content)
                h = _img_hash(tmp)
                if h and h not in avoid:
                    tmp.rename(out_path)
                    log.info("HuggingFace: generated image for '%s'", query[:50])
                    return True
                tmp.unlink(missing_ok=True)
                break
            except Exception as exc:
                log.debug("HuggingFace fetch: %s", exc)
                break
    return False


def _fallback_query(keywords: list[str]) -> str:
    return " ".join(keywords[:4])


# ── Image validation & hash helpers ──────────────────────────────────────────

def _validate_image(path: Path, scene_id: int) -> bool:
    if not path.exists() or path.stat().st_size < 5_000:
        log.warning("Scene %d: image file missing or too small after fetch", scene_id)
        return False
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            if w < 960 or h < 540:
                log.warning("Scene %d: image resolution too low (%dx%d) — skipping",
                            scene_id, w, h)
                return False
    except Exception:
        pass  # PIL not available or corrupt — accept based on file size
    return True


def _img_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()[:65536]).hexdigest()
    except Exception:
        return ""


# ── Pexels fetcher ────────────────────────────────────────────────────────────

def _pexels_fetch(query: str, out_path: Path,
                  shot_type: str = "MEDIUM",
                  avoid_hashes: set[str] | None = None) -> bool:
    """
    Fetches the best available full-HD photo from Pexels.
    Requests 15 candidates, iterates through them and picks the first
    whose content MD5 is not in avoid_hashes.
    Uses original URL for full resolution; size=large filters to ≥ 4 MP.
    """
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return False

    avoid = avoid_hashes or set()

    # Reuse if already downloaded this run (< 2 h old) and not a known duplicate
    cutoff = time.time() - 2 * 3600
    if (out_path.exists()
            and out_path.stat().st_mtime > cutoff
            and out_path.stat().st_size > 10_000):
        h = _img_hash(out_path)
        if h not in avoid:
            log.info("Reusing current-run image: %s", out_path.name)
            return True
        out_path.unlink(missing_ok=True)

    orientation = "portrait" if shot_type in _PORTRAIT_SHOTS else "landscape"
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={
                "query":       query,
                "per_page":    15,
                "orientation": orientation,
                "size":        "large",      # Pexels: only images ≥ 4 MP
            },
            timeout=15,
        )
        if not r.ok:
            log.warning("Pexels API %d: %s", r.status_code, r.text[:120])
            return False

        photos = r.json().get("photos", [])
        for photo in photos:
            src = photo.get("src", {})
            # original = full resolution; large2x ≈ 1880 px as fallback
            img_url = src.get("original") or src.get("large2x")
            if not img_url:
                continue
            tmp = out_path.with_suffix(".tmp.png")
            if not _download(img_url, tmp):
                tmp.unlink(missing_ok=True)
                continue
            h = _img_hash(tmp)
            if h and h not in avoid:
                tmp.rename(out_path)
                log.debug("Pexels photo id=%s  size=%s",
                          photo.get("id"), photo.get("width"))
                return True
            # This photo is a duplicate — discard and try the next
            log.debug("Pexels photo id=%s is duplicate — trying next", photo.get("id"))
            tmp.unlink(missing_ok=True)

    except Exception as exc:
        log.warning("Pexels fetch error: %s", exc)

    return False


# ── Pixabay fetcher ───────────────────────────────────────────────────────────

def _pixabay_fetch(query: str, out_path: Path,
                   avoid_hashes: set[str] | None = None) -> bool:
    """
    Fetches the best available full-HD photo from Pixabay.
    Requests 15 candidates with min_width=1920; prefers imageURL (original
    resolution) → largeImageURL (1280 px) → webformatURL (640 px).
    Iterates until finding a photo whose MD5 is not in avoid_hashes.
    """
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return False

    avoid = avoid_hashes or set()

    # Reuse if already downloaded this run (< 2 h old) and not a known duplicate
    cutoff = time.time() - 2 * 3600
    if (out_path.exists()
            and out_path.stat().st_mtime > cutoff
            and out_path.stat().st_size > 10_000):
        h = _img_hash(out_path)
        if h not in avoid:
            log.info("Reusing current-run image: %s", out_path.name)
            return True
        out_path.unlink(missing_ok=True)

    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key":        api_key,
                "q":          "+".join(query.split()[:4]),
                "image_type": "photo",
                "per_page":   15,
                "safesearch": "true",
                "min_width":  1920,
                "min_height": 1080,
                "order":      "popular",
            },
            timeout=15,
        )
        if not r.ok:
            log.warning("Pixabay API %d: %s", r.status_code, r.text[:120])
            return False

        hits = r.json().get("hits", [])

        # Retry without resolution constraint if no results at 1920p
        if not hits:
            r2 = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key":        api_key,
                    "q":          "+".join(query.split()[:4]),
                    "image_type": "photo",
                    "per_page":   15,
                    "safesearch": "true",
                    "order":      "popular",
                },
                timeout=15,
            )
            if r2.ok:
                hits = r2.json().get("hits", [])

        for hit in hits:
            # Prefer full-resolution → 1280 px → 640 px fallback
            img_url = (hit.get("imageURL")
                       or hit.get("fullHDURL")
                       or hit.get("largeImageURL")
                       or hit.get("webformatURL"))
            if not img_url:
                continue
            tmp = out_path.with_suffix(".tmp.png")
            if not _download(img_url, tmp):
                tmp.unlink(missing_ok=True)
                continue
            h = _img_hash(tmp)
            if h and h not in avoid:
                tmp.rename(out_path)
                log.debug("Pixabay id=%s  %dx%d",
                          hit.get("id"), hit.get("imageWidth", 0), hit.get("imageHeight", 0))
                return True
            log.debug("Pixabay id=%s is duplicate — trying next", hit.get("id"))
            tmp.unlink(missing_ok=True)

    except Exception as exc:
        log.warning("Pixabay fetch error: %s", exc)

    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _download(url: str, path: Path) -> bool:
    try:
        r = requests.get(url, timeout=30, stream=True)
        if r.ok:
            path.write_bytes(r.content)
            return path.stat().st_size > 1_000
    except Exception as exc:
        log.debug("Download %s: %s", url[:60], exc)
    return False


def _trim(src: Path, dur_s: float, scene_id: int, out_dir: Path) -> Optional[Path]:
    out = out_dir / f"scene_{scene_id}_visual_trimmed.mp4"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-ss", "0", "-t", str(dur_s),
             "-c:v", "copy", "-an", str(out)],
            capture_output=True, timeout=60,
        )
        if out.exists() and out.stat().st_size > 1_000:
            return out
    except Exception as exc:
        log.debug("Trim: %s", exc)
    return None


def _black_clip(path: Path, dur_s: float, W: int, H: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:size={W}x{H}:rate=30",
         "-t", str(dur_s), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-an", str(path)],
        capture_output=True, timeout=60,
    )
    return path
