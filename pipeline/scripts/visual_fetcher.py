"""
STEP 6 — Visual Fetch (Pexels / Pixabay)

For each scene:
  1. Groq converts scene keywords + emotion + shot_type → optimised search query
  2. Pexels is tried first; Pixabay is the fallback
  3. Image saved to visuals_dir as scene_{id}_visual.png

Image deduplication:
  - Within a video:  session_prompts set prevents identical queries across scenes
  - Across videos:   stale PNG files (> 2 h old) are purged before each run;
                     a persistent registry (logs/used_prompts.json) tracks recently
                     used query hashes and forces unique modifiers when needed
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

GROQ_MODEL    = "llama3-8b-8192"
GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"

MAX_RETRIES   = 3
RETRY_BASE_S  = 5

# Cross-video prompt registry (rolling, keeps last 300 entries)
_LOGS_DIR       = Path(__file__).parent.parent / "logs"
PROMPT_REGISTRY = _LOGS_DIR / "used_prompts.json"
REGISTRY_LIMIT  = 300

# Modifiers cycled when a duplicate query is detected
_UNIQUE_MODIFIERS = [
    "different angle", "alternative perspective", "unique composition",
    "contrasting viewpoint", "shifted framing", "varied lighting",
    "opposite vantage point", "distinct atmosphere",
]


# ── Main entry ────────────────────────────────────────────────────────────────

def fetch_visuals(timeline: dict, visuals_dir: Path) -> dict:
    """
    Input:  timeline dict with scenes[] containing visual_keywords, emotion,
            shot_type, scene_id, duration_ms; plus width, height, intent fields
    Output: same timeline dict with each scene updated:
            visual_file (str filename), clip_type ("image"/"black"), clip_score (float)
    """
    visuals_dir.mkdir(parents=True, exist_ok=True)

    # Remove PNG files from previous runs (> 2 h old) so images are never reused
    # across videos. Files from the current run (recent) are kept for retry safety.
    _cleanup_stale_visuals(visuals_dir, max_age_hours=2)

    W, H   = timeline["width"], timeline["height"]
    intent = timeline.get("intent", "SCIENCE")

    # Load cross-video registry and build within-video session sets
    used_registry    = _load_prompt_registry()
    session_prompts: set[str] = set()   # hashes of queries used this run
    session_img_hashes: set[str] = set()  # MD5 hashes of downloaded images (dedup content)

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
        raw_query = _groq_to_search_query(
            keywords  = kw_list,
            emotion   = emotion,
            shot_type = shot_type,
            intent    = intent,
        )

        # Ensure the query is unique within this video and across recent videos
        query = _ensure_unique_query(raw_query, session_prompts, used_registry, scene_id)
        log.info("Scene %d | query: %s", scene_id, query)

        # Record query in session and registry to prevent future reuse
        qh = _prompt_hash(query)
        session_prompts.add(qh)
        used_registry.append(qh)

        # Step 2 — Fetch primary image: Pexels → Pixabay → black clip
        # Pass shot_type so orientation matches (AERIAL/WIDE → landscape, etc.)
        success = _pexels_fetch(query, out_path, shot_type)

        if not success:
            log.warning("Scene %d: Pexels failed — trying Pixabay", scene_id)
            success = _pixabay_fetch(query, out_path)

        # Fix #2: validate file actually exists with valid content after fetch
        if success and not _validate_image(out_path, scene_id):
            out_path.unlink(missing_ok=True)
            success = False

        # Fix #11: detect duplicate image content via MD5 hash — re-fetch if same
        # image was used by a previous scene in this run
        if success:
            img_hash = _img_hash(out_path)
            if img_hash in session_img_hashes:
                log.warning("Scene %d: duplicate image detected — fetching alternate",
                            scene_id)
                alt_q = _ensure_unique_query(
                    _fallback_query(kw_list[1:] if len(kw_list) > 1 else kw_list),
                    session_prompts, used_registry, scene_id + 5000,
                )
                alt_path = visuals_dir / f"scene_{scene_id}_visual_alt.png"
                alt_ok = _pexels_fetch(alt_q, alt_path, shot_type) or \
                         _pixabay_fetch(alt_q, alt_path)
                if alt_ok and _validate_image(alt_path, scene_id):
                    out_path.unlink(missing_ok=True)
                    alt_path.rename(out_path)
                    img_hash = _img_hash(out_path)
                else:
                    alt_path.unlink(missing_ok=True)
            session_img_hashes.add(img_hash)

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

        # Step 3 — Fetch extra image for slideshow (scenes ≥ 4s with multiple keywords)
        extra_files: list[str] = []
        if success and dur_s >= 4.0 and len(kw_list) >= 2:
            alt_query = _ensure_unique_query(
                _fallback_query(kw_list[1:]), session_prompts, used_registry, scene_id + 1000
            )
            extra_path = visuals_dir / f"scene_{scene_id}_visual_b.png"
            extra_ok = _pexels_fetch(alt_query, extra_path, shot_type)
            if not extra_ok:
                extra_ok = _pixabay_fetch(alt_query, extra_path)
            if extra_ok and _validate_image(extra_path, scene_id):
                extra_hash = _img_hash(extra_path)
                if extra_hash not in session_img_hashes:
                    session_img_hashes.add(extra_hash)
                    extra_files.append(extra_path.name)
                    log.info("Scene %d | extra image: %s", scene_id, extra_path.name)
                else:
                    extra_path.unlink(missing_ok=True)
            else:
                extra_path.unlink(missing_ok=True)

        sc["extra_visual_files"] = extra_files

    # Persist updated registry (trimmed to REGISTRY_LIMIT)
    _save_prompt_registry(used_registry)

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
        log.debug("Registry load error: %s", exc)
    return []


def _save_prompt_registry(registry: list[str]) -> None:
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        PROMPT_REGISTRY.write_text(
            json.dumps(registry[-REGISTRY_LIMIT:], indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("Registry save error: %s", exc)


def _ensure_unique_query(
    query: str,
    session_prompts: set[str],
    used_registry: list[str],
    scene_id: int,
) -> str:
    registry_set = set(used_registry)
    modifier_idx = 0
    current = query

    for _ in range(len(_UNIQUE_MODIFIERS) + 1):
        qh = _prompt_hash(current)
        if qh not in session_prompts and qh not in registry_set:
            return current
        if modifier_idx < len(_UNIQUE_MODIFIERS):
            mod = _UNIQUE_MODIFIERS[modifier_idx]
            current = f"{query} {mod}"
            modifier_idx += 1
        else:
            current = f"{query} scene {scene_id}"
            break

    return current


def _cleanup_stale_visuals(visuals_dir: Path, max_age_hours: int = 2) -> None:
    cutoff = time.time() - max_age_hours * 3600
    for f in visuals_dir.glob("scene_*_visual.png"):
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
    """
    Sends scene metadata to Groq llama3-8b-8192 and gets back a short
    Pexels/Pixabay-optimised search query (3-6 words).
    Falls back to a plain keyword join if keys are missing or the call fails.
    """
    api_key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY_2", "")
    if not api_key:
        return _fallback_query(keywords)

    system_prompt = (
        "You convert scene metadata into short stock-photo search queries.\n"
        "Rules:\n"
        "- Output ONLY the search query. No explanation, no preamble, no quotes.\n"
        "- 3 to 6 words maximum.\n"
        "- Use concrete, visual, searchable nouns and adjectives.\n"
        "- Avoid abstract words like 'concept', 'idea', 'mystery'."
    )

    user_message = (
        f"Keywords: {', '.join(keywords)}\n"
        f"Emotion: {emotion}\n"
        f"Shot type: {shot_type}\n"
        f"Category: {intent}"
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
                    "max_tokens":  30,
                    "temperature": 0.3,
                },
                timeout=15,
            )
            if r.ok:
                query = r.json()["choices"][0]["message"]["content"].strip()
                return " ".join(query.split()[:6])   # hard cap at 6 words
            else:
                log.warning("Groq query API %d: %s", r.status_code, r.text[:200])
                break
        except requests.exceptions.ConnectionError as exc:
            wait = RETRY_BASE_S * attempt
            log.warning("Groq connection error (attempt %d/%d) — waiting %ds: %s",
                        attempt, MAX_RETRIES, wait, str(exc)[:120])
            time.sleep(wait)
        except Exception as exc:
            log.warning("Groq query call failed: %s", exc)
            break

    return _fallback_query(keywords)


def _fallback_query(keywords: list[str]) -> str:
    return " ".join(keywords[:4])


# ── Image validation & hash helpers ──────────────────────────────────────────

# Shot types that produce naturally tall subjects — prefer portrait orientation
_PORTRAIT_SHOTS = {"EXTREME_CLOSE", "CLOSE"}

def _validate_image(path: Path, scene_id: int) -> bool:
    """Fix #2 & #9: verify file exists, is large enough, and meets min resolution."""
    if not path.exists() or path.stat().st_size < 5_000:
        log.warning("Scene %d: image file missing or too small after fetch", scene_id)
        return False
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            if w < 640 or h < 360:
                log.warning("Scene %d: image resolution too low (%dx%d) — skipping",
                            scene_id, w, h)
                return False
    except Exception:
        pass   # PIL not available or corrupt — accept file based on size alone
    return True


def _img_hash(path: Path) -> str:
    """Fix #11: fast MD5 of first 64 KB — enough to detect duplicate images."""
    try:
        return hashlib.md5(path.read_bytes()[:65536]).hexdigest()
    except Exception:
        return ""


# ── Pexels / Pixabay fetchers ─────────────────────────────────────────────────

def _pexels_fetch(query: str, out_path: Path, shot_type: str = "MEDIUM") -> bool:
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return False

    # Reuse if already downloaded this run (< 2 h old)
    cutoff = time.time() - 2 * 3600
    if out_path.exists() and out_path.stat().st_mtime > cutoff and out_path.stat().st_size > 10_000:
        log.info("Reusing current-run image: %s", out_path.name)
        return True

    # Fix #12: use portrait for close-up shots, landscape for everything else
    orientation = "portrait" if shot_type in _PORTRAIT_SHOTS else "landscape"
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 5, "orientation": orientation},
            timeout=15,
        )
        if r.ok:
            photos = r.json().get("photos", [])
            if photos:
                img_url = photos[0]["src"].get("large2x") or photos[0]["src"]["original"]
                return _download(img_url, out_path)
        else:
            log.warning("Pexels API %d: %s", r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("Pexels fetch error: %s", exc)
    return False


def _pixabay_fetch(query: str, out_path: Path) -> bool:
    api_key = os.getenv("PIXABAY_API_KEY", "")
    if not api_key:
        return False

    # Reuse if already downloaded this run (< 2 h old)
    cutoff = time.time() - 2 * 3600
    if out_path.exists() and out_path.stat().st_mtime > cutoff and out_path.stat().st_size > 10_000:
        log.info("Reusing current-run image: %s", out_path.name)
        return True

    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key":        api_key,
                "q":          "+".join(query.split()[:4]),
                "image_type": "photo",
                "per_page":   5,
                "safesearch": "true",
            },
            timeout=15,
        )
        if r.ok:
            hits = r.json().get("hits", [])
            if hits:
                img_url = hits[0].get("largeImageURL") or hits[0].get("webformatURL")
                return _download(img_url, out_path)
        else:
            log.warning("Pixabay API %d: %s", r.status_code, r.text[:120])
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
