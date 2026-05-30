"""
STEP 6 — Visual Fetch via AI Image Generation

For each scene:
  1. HF text model converts scene keywords + emotion + shot_type → optimized FLUX.1 visual prompt
  2. HF FLUX.1-schnell generates a semantically matched image
  3. Image saved to visuals_dir as scene_{id}_visual.png

Image deduplication:
  - Within a video:  session_prompts set prevents identical prompts across scenes
  - Across videos:   stale PNG files (> 2 h old) are purged before each run;
                     a persistent registry (logs/used_prompts.json) tracks recently
                     used prompt hashes and forces unique modifiers when needed
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

HF_MODEL        = "black-forest-labs/FLUX.1-schnell"
HF_API_BASE     = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

# HF text model for semantic prompt generation (OpenAI-compatible endpoint)
HF_TEXT_MODEL   = "meta-llama/Meta-Llama-3.1-8B-Instruct"
HF_TEXT_URL     = "https://api-inference.huggingface.co/v1/chat/completions"

# FLUX.1-schnell specific — DO NOT change these
FLUX_STEPS      = 4      # schnell is optimized at exactly 4 steps
FLUX_GUIDANCE   = 0.0   # schnell requires guidance_scale = 0.0

MAX_RETRIES     = 5      # HF model loading retries
RETRY_BASE_S    = 5      # exponential backoff base (seconds)

# Cross-video prompt registry (rolling, keeps last 300 entries)
_LOGS_DIR       = Path(__file__).parent.parent / "logs"
PROMPT_REGISTRY = _LOGS_DIR / "used_prompts.json"
REGISTRY_LIMIT  = 300

# Modifiers cycled when a duplicate prompt is detected
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
    # across videos.  Files from the current run (recent) are kept for retry safety.
    _cleanup_stale_visuals(visuals_dir, max_age_hours=2)

    W, H   = timeline["width"], timeline["height"]
    intent = timeline.get("intent", "SCIENCE")

    # Load cross-video registry and build within-video session set
    used_registry   = _load_prompt_registry()
    session_prompts: set[str] = set()   # hashes of prompts used this run

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

        # Step 1 — Convert scene metadata → FLUX.1 visual prompt via HF text model
        raw_prompt = _hf_to_visual_prompt(
            keywords  = kw_list,
            emotion   = emotion,
            shot_type = shot_type,
            intent    = intent,
            portrait  = (W < H),
        )

        # Ensure the prompt is unique (within this video and across recent videos)
        prompt = _ensure_unique_prompt(raw_prompt, session_prompts, used_registry, scene_id)
        log.info("Scene %d | prompt: %s", scene_id, prompt)

        # Record prompt in session and registry to prevent future reuse
        ph = _prompt_hash(prompt)
        session_prompts.add(ph)
        used_registry.append(ph)

        # Step 2 — Generate image via FLUX.1-schnell
        success = _flux_generate_image(prompt, out_path, W, H)

        if success:
            sc["visual_file"]       = out_path.name
            sc["clip_type"]         = "image"
            sc["clip_score"]        = 1.0
        else:
            log.warning("Scene %d: FLUX generation failed — black fallback", scene_id)
            bp = _black_clip(
                visuals_dir / f"scene_{scene_id}_visual.mp4", dur_s, W, H
            )
            sc["visual_file"] = bp.name
            sc["clip_type"]   = "black"
            sc["clip_score"]  = 0.0

        sc["retry_count"]        = 0
        sc["extra_visual_files"] = []

    # Persist updated registry (trimmed to REGISTRY_LIMIT)
    _save_prompt_registry(used_registry)

    return timeline


# ── Image deduplication helpers ───────────────────────────────────────────────

def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _load_prompt_registry() -> list[str]:
    """Returns list of recent prompt hashes (oldest first)."""
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
        trimmed = registry[-REGISTRY_LIMIT:]
        PROMPT_REGISTRY.write_text(
            json.dumps(trimmed, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("Registry save error: %s", exc)


def _ensure_unique_prompt(
    prompt: str,
    session_prompts: set[str],
    used_registry: list[str],
    scene_id: int,
) -> str:
    """
    Add a modifier to prompt if its hash appears in the session or registry,
    cycling through _UNIQUE_MODIFIERS until a unique hash is found.
    """
    registry_set = set(used_registry)
    modifier_idx = 0

    current = prompt
    for _ in range(len(_UNIQUE_MODIFIERS) + 1):
        ph = _prompt_hash(current)
        if ph not in session_prompts and ph not in registry_set:
            return current
        if modifier_idx < len(_UNIQUE_MODIFIERS):
            mod = _UNIQUE_MODIFIERS[modifier_idx % len(_UNIQUE_MODIFIERS)]
            current = f"{prompt}, {mod}"
            modifier_idx += 1
        else:
            # Last resort: append scene_id to guarantee uniqueness
            current = f"{prompt}, scene variant {scene_id}"
            break

    return current


def _cleanup_stale_visuals(visuals_dir: Path, max_age_hours: int = 2) -> None:
    """Delete PNG visual files older than max_age_hours (cross-video reuse prevention)."""
    cutoff = time.time() - max_age_hours * 3600
    for f in visuals_dir.glob("scene_*_visual.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                log.debug("Removed stale visual: %s", f.name)
        except Exception:
            pass


# ── HF text model: scene metadata → visual prompt ────────────────────────────

def _hf_to_visual_prompt(
    keywords:  list[str],
    emotion:   str,
    shot_type: str,
    intent:    str,
    portrait:  bool,
) -> str:
    """
    Uses HF Inference API (OpenAI-compatible) with Meta-Llama-3.1-8B-Instruct
    to convert scene metadata into a 40-55 word FLUX.1 image generation prompt.
    Falls back to keyword-based prompt if HF_API_KEY is missing or call fails.
    """
    api_key = os.getenv("HF_API_KEY", "")
    if not api_key:
        return _fallback_prompt(keywords, emotion, shot_type, portrait)

    orientation_hint = "vertical portrait composition" if portrait else "wide cinematic landscape"

    system_prompt = (
        "You convert scene metadata into image generation prompts for FLUX.1.\n"
        "Rules:\n"
        "- Output ONLY the prompt. No explanation, no preamble, no quotes.\n"
        "- 40 to 55 words maximum.\n"
        "- Describe VISIBLE elements only — no abstract concepts.\n"
        "- Include the shot type naturally (aerial view / extreme close-up / wide shot etc.).\n"
        "- Match the emotion in lighting and mood (mysterious=dark fog; excited=golden light; "
        "dramatic=storm contrast; neutral=clean natural light).\n"
        f"- Composition must suit {orientation_hint}.\n"
        "- End with: photorealistic, cinematic, sharp focus, 8k"
    )

    user_message = (
        f"Keywords: {', '.join(keywords)}\n"
        f"Emotion: {emotion}\n"
        f"Shot type: {shot_type}\n"
        f"Category: {intent}"
    )

    for attempt in range(1, 3):   # 2 attempts before falling back
        try:
            r = requests.post(
                HF_TEXT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":      HF_TEXT_MODEL,
                    "messages":   [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_message},
                    ],
                    "max_tokens": 120,
                    "temperature": 0.4,
                },
                timeout=20,
            )
            if r.ok:
                prompt = r.json()["choices"][0]["message"]["content"].strip()
                # Enforce token limit — FLUX.1 truncates at ~77 tokens (~55 words)
                words = prompt.split()
                if len(words) > 55:
                    prompt = " ".join(words[:55])
                return prompt
            else:
                log.warning("HF text API %d: %s", r.status_code, r.text[:200])
                break   # HTTP error — no point retrying
        except requests.exceptions.ConnectionError as exc:
            log.warning("HF text connection error (attempt %d/2) — waiting 10s: %s",
                        attempt, str(exc)[:120])
            time.sleep(10)
        except Exception as exc:
            log.warning("HF text prompt call failed: %s", exc)
            break

    return _fallback_prompt(keywords, emotion, shot_type, portrait)


def _fallback_prompt(
    keywords: list[str], emotion: str, shot_type: str, portrait: bool
) -> str:
    shot_map = {
        "WIDE":          "wide shot",
        "AERIAL":        "aerial drone view",
        "MEDIUM":        "medium shot",
        "CLOSE":         "close-up shot",
        "EXTREME_CLOSE": "extreme close-up",
    }
    mood_map = {
        "excited":    "golden hour lighting, vibrant",
        "mysterious": "dark foggy atmosphere, moody",
        "dramatic":   "storm clouds, high contrast lighting",
        "neutral":    "natural daylight, clean",
    }
    shot_str  = shot_map.get(shot_type, "cinematic shot")
    mood_str  = mood_map.get(emotion, "cinematic lighting")
    orient    = "vertical portrait" if portrait else "wide landscape"
    kw_str    = ", ".join(keywords[:2])

    return (
        f"{shot_str} of {kw_str}, {mood_str}, "
        f"{orient} composition, photorealistic, cinematic, sharp focus, 8k"
    )


# ── HF FLUX.1-schnell: prompt → image ────────────────────────────────────────

def _flux_generate_image(prompt: str, out_path: Path, W: int, H: int) -> bool:
    """
    POST to HF Inference API → FLUX.1-schnell generates PNG → written to out_path.

    File reuse: only reuses an existing file if it was written in the current run
    (i.e., modified within the last 2 hours — stale files are purged by
    _cleanup_stale_visuals before this function is ever called).

    Handles 503 (model loading) with exponential backoff and 429 (rate limit)
    with a 60 s wait.  Returns False after MAX_RETRIES exhausted.
    """
    api_key = os.getenv("HF_API_KEY", "")
    if not api_key:
        log.error("HF_API_KEY not set — cannot generate image")
        return False

    # Reuse only files written in this run (within 2 h) — handles pipeline retries
    # without carrying over images from previous video runs.
    cutoff = time.time() - 2 * 3600
    if out_path.exists() and out_path.stat().st_mtime > cutoff and out_path.stat().st_size > 10_000:
        log.info("Reusing current-run image: %s", out_path.name)
        return True

    payload = {
        "inputs": prompt,
        "parameters": {
            "width":               W,
            "height":              H,
            "num_inference_steps": FLUX_STEPS,
            "guidance_scale":      FLUX_GUIDANCE,
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(
                HF_API_BASE,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                    "Accept":        "image/png",
                },
                json=payload,
                timeout=120,
            )

            if r.status_code == 503:
                wait = RETRY_BASE_S * (2 ** (attempt - 1))
                log.info("HF model loading (attempt %d/%d) — waiting %ds",
                         attempt, MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            if r.status_code == 429:
                log.warning("HF rate limit hit — waiting 60s")
                time.sleep(60)
                continue

            if not r.ok:
                log.error("HF API error %d: %s", r.status_code, r.text[:300])
                return False

            image_bytes = r.content
            if len(image_bytes) < 10_000:
                log.warning("HF returned suspiciously small image (%d bytes)", len(image_bytes))
                return False

            out_path.write_bytes(image_bytes)
            log.info("Generated image: %s (%d KB)", out_path.name, len(image_bytes) // 1024)
            return True

        except requests.Timeout:
            log.warning("HF request timeout (attempt %d/%d)", attempt, MAX_RETRIES)
            time.sleep(RETRY_BASE_S * attempt)
        except requests.exceptions.ConnectionError as exc:
            # DNS / network blip — wait and retry (transient on GitHub Actions runners)
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            log.warning("HF connection error (attempt %d/%d) — waiting %ds: %s",
                        attempt, MAX_RETRIES, wait, str(exc)[:120])
            time.sleep(wait)
        except Exception as exc:
            log.error("HF generation unexpected error: %s", exc)
            return False

    log.error("FLUX.1 failed after %d attempts for prompt: %s", MAX_RETRIES, prompt[:80])
    return False


# ── Unchanged helpers ─────────────────────────────────────────────────────────

def _download(url: str, path: Path) -> bool:
    if path.exists() and path.stat().st_size > 10_000:
        return True
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
