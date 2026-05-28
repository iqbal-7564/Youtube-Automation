"""
STEP 6 — Visual Fetch + Validation

For each scene: tries up to 3 scene-specific keywords (visual_keywords list),
then falls back to category fallbacks → generic safe keyword.
Pexels portrait orientation filter is enforced for Shorts profile.
Score with text-based CLIP proxy (keyword recall × fuzzy), pick best >= 0.28.
Video clips are trimmed to exact scene duration. Images get Ken Burns in Step 8.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import requests

try:
    from rapidfuzz import fuzz as _fuzz
    def _score(kw: str, text: str) -> float:
        kw_words = set(kw.lower().split())
        text_l   = text.lower()
        recall   = sum(1 for w in kw_words if w in text_l) / max(len(kw_words), 1)
        fuzzy    = _fuzz.partial_ratio(kw.lower(), text_l) / 100.0
        return max(recall, fuzzy * 0.6)
except ImportError:
    def _score(kw: str, text: str) -> float:
        kw_w = set(kw.lower().split())
        tx_w = set(text.lower().split())
        if not kw_w:
            return 0.5
        return len(kw_w & tx_w) / len(kw_w)

log = logging.getLogger(__name__)

_CLIP_THRESHOLD = 0.28

_FALLBACKS: dict[str, list[str]] = {
    "SPACE":     ["galaxy stars milky way",       "planet surface space",       "cosmos nebula wide"],
    "SCIENCE":   ["laboratory science research",  "microscope experiment",      "technology innovation"],
    "HISTORY":   ["ancient ruins archaeology",    "historical monument stone",  "civilisation heritage"],
    "ANIMALS":   ["wildlife nature animal",       "ocean marine creature",      "forest animal habitat"],
    "NATURE":    ["dramatic landscape aerial",    "waterfall river nature",     "forest canopy wide"],
    "GEOGRAPHY": ["aerial earth landscape drone", "mountain peak geography",    "desert landscape wide"],
    "OCEAN":     ["ocean underwater marine",      "deep sea bioluminescence",   "coral reef fish"],
    "CULTURE":   ["ancient temple architecture",  "cultural ceremony people",   "historical artefact"],
}
_GENERIC_FALLBACK = ["nature landscape wide", "aerial earth beautiful", "cosmos stars universe"]


def fetch_visuals(timeline: dict, visuals_dir: Path) -> dict:
    visuals_dir.mkdir(parents=True, exist_ok=True)
    W, H    = timeline["width"], timeline["height"]
    intent  = timeline.get("intent", "SCIENCE")
    orient  = "portrait" if W < H else "landscape"
    fallbacks = _FALLBACKS.get(intent, _GENERIC_FALLBACK)

    for sc in timeline["scenes"]:
        if sc.get("clip_type") == "close" or sc.get("visual_keyword") == "CLOSE":
            sc.update(visual_file="CLOSE", clip_type="close", clip_score=1.0)
            continue

        # Use the ranked keyword list from scene_planner (3 specific options)
        kw_list   = sc.get("visual_keywords") or [sc["visual_keyword"]]
        dur_s     = sc["duration_ms"] / 1000
        primary_kw = kw_list[0]

        path, clip_type, clip_score, retries = _fetch_with_retry(
            primary_kw, kw_list[1:], fallbacks, visuals_dir, sc["scene_id"], dur_s, orient, W, H
        )

        if path:
            sc["visual_file"] = path.name
            sc["clip_type"]   = clip_type
        else:
            log.warning("Scene %d: no visual — black fallback", sc["scene_id"])
            bp = _black_clip(visuals_dir / f"scene_{sc['scene_id']}_visual.mp4", dur_s, W, H)
            sc["visual_file"] = bp.name
            sc["clip_type"]   = "black"

        sc["clip_score"]  = round(clip_score, 3)
        sc["retry_count"] = retries

    return timeline


def _fetch_with_retry(primary_kw, scene_kws, fallbacks, out_dir, scene_id, dur_s, orient, W, H):
    # Try scene-specific keywords first, then category fallbacks, then generic
    kw_tries = [primary_kw] + list(scene_kws) + fallbacks[:2] + [_GENERIC_FALLBACK[0]]
    seen = set()
    deduped = []
    for k in kw_tries:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    kw_tries = deduped[:5]

    best: Optional[dict] = None

    for retry, kw in enumerate(kw_tries):
        candidates = (_pexels_videos(kw, orient) or
                      _pixabay_videos(kw) or
                      _pexels_photos(kw, orient) or
                      _pixabay_photos(kw))
        if not candidates:
            continue

        for c in candidates:
            c["_s"] = _score(primary_kw, c["tags"])
        candidates.sort(key=lambda c: c["_s"], reverse=True)
        top = candidates[0]

        if top["_s"] >= _CLIP_THRESHOLD or retry == len(kw_tries) - 1:
            out_name = f"scene_{scene_id}_visual.{top['ext']}"
            out_path = out_dir / out_name
            if _download(top["url"], out_path):
                if top["type"] == "video":
                    trimmed = _trim(out_path, dur_s, scene_id, out_dir)
                    if trimmed:
                        return trimmed, "video", top["_s"], retry
                else:
                    return out_path, "image", top["_s"], retry

        if best is None or top["_s"] > best.get("_s", 0):
            best = {**top, "out_dir": out_dir, "scene_id": scene_id, "dur_s": dur_s}

    if best:
        out_path = best["out_dir"] / f"scene_{best['scene_id']}_visual.{best['ext']}"
        if _download(best["url"], out_path):
            if best["type"] == "video":
                trimmed = _trim(out_path, best["dur_s"], best["scene_id"], best["out_dir"])
                if trimmed:
                    return trimmed, "video", best["_s"], len(kw_tries)
            else:
                return out_path, "image", best["_s"], len(kw_tries)

    return None, "video", 0.0, len(kw_tries)


# ── Pexels / Pixabay ──────────────────────────────────────────────────────────

def _pexels_videos(kw, orient) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": kw, "per_page": 5, "orientation": orient},
            timeout=10,
        )
        if not r.ok:
            return []
        out = []
        for v in r.json().get("videos", []):
            files = sorted(v.get("video_files", []),
                           key=lambda x: x.get("width", 0), reverse=True)
            if not files:
                continue
            out.append({
                "url":  files[0]["link"],
                "tags": " ".join([v.get("url", ""), kw]),
                "type": "video", "ext": "mp4",
            })
        return out
    except Exception as exc:
        log.debug("Pexels videos: %s", exc)
    return []


def _pixabay_videos(kw) -> list[dict]:
    key = os.getenv("PIXABAY_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": key, "q": kw, "per_page": 5, "video_type": "film"},
            timeout=10,
        )
        if not r.ok:
            return []
        out = []
        for v in r.json().get("hits", []):
            vids = v.get("videos", {})
            url  = (vids.get("large") or vids.get("medium") or {}).get("url", "")
            if not url:
                continue
            out.append({
                "url":  url,
                "tags": v.get("tags", "") + " " + kw,
                "type": "video", "ext": "mp4",
            })
        return out
    except Exception as exc:
        log.debug("Pixabay videos: %s", exc)
    return []


def _pexels_photos(kw, orient) -> list[dict]:
    key = os.getenv("PEXELS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={"query": kw, "per_page": 5, "orientation": orient},
            timeout=10,
        )
        if not r.ok:
            return []
        return [
            {
                "url":  p["src"].get("original", p["src"].get("large2x", "")),
                "tags": p.get("alt", "") + " " + kw,
                "type": "image", "ext": "jpg",
            }
            for p in r.json().get("photos", []) if p.get("src")
        ]
    except Exception as exc:
        log.debug("Pexels photos: %s", exc)
    return []


def _pixabay_photos(kw) -> list[dict]:
    key = os.getenv("PIXABAY_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/",
            params={"key": key, "q": kw, "per_page": 5, "image_type": "photo"},
            timeout=10,
        )
        if not r.ok:
            return []
        return [
            {
                "url":  h.get("largeImageURL", ""),
                "tags": h.get("tags", "") + " " + kw,
                "type": "image", "ext": "jpg",
            }
            for h in r.json().get("hits", []) if h.get("largeImageURL")
        ]
    except Exception as exc:
        log.debug("Pixabay photos: %s", exc)
    return []


# ── Download / trim helpers ───────────────────────────────────────────────────

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
