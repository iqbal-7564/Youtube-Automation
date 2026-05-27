"""
STEP 12 — Upload + Metadata

YouTube resumable upload (same pattern as scripts/youtube_upload.py).
Extracts thumbnail at t=2s (inside HOOK — most dramatic frame).
Auto-assigns to intent-specific playlist.
Category: 25 (News & Politics) — never use 24/28 for news content.
"""

import logging
import os
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_PLAYLISTS = {
    "WAR":      "VisionaryMinds — War & Conflict",
    "DISASTER": "VisionaryMinds — Disasters",
    "POLITICS": "VisionaryMinds — Politics",
    "ECONOMY":  "VisionaryMinds — Economy",
    "SPORTS":   "VisionaryMinds — Sports",
}


def upload_video(
    video_path: Path,
    thumb_path: Path,
    script: dict,
    topic: dict,
    timeline: dict,
    profile: str,
) -> str | None:
    try:
        token = _token()
    except Exception as exc:
        log.error("Token refresh failed: %s", exc)
        return None

    metadata = _build_meta(script, topic, timeline, profile)
    is_short = profile == "shorts"
    title    = metadata["title"]
    if is_short and "#Shorts" not in title:
        title = (title[:88] + " #Shorts") if len(title) > 88 else title + " #Shorts"

    video_id = _upload(video_path, metadata, token, title, is_short)
    if not video_id:
        return None

    _extract_thumb(video_path, thumb_path)
    _upload_thumb(video_id, thumb_path, token)

    pl_name = _PLAYLISTS.get(topic.get("intent", "").upper(),
                              "VisionaryMinds — World News")
    pl_id   = _playlist(token, pl_name)
    if pl_id:
        _add_to_playlist(token, video_id, pl_id)

    return video_id


# ── Token ─────────────────────────────────────────────────────────────────────

def _token() -> str:
    for attempt in range(3):
        try:
            r = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id":     os.environ.get("YOUTUBE_CLIENT_ID"),
                    "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET"),
                    "refresh_token": os.environ.get("YOUTUBE_REFRESH_TOKEN"),
                    "grant_type":    "refresh_token",
                },
                timeout=15,
            )
            d = r.json()
            if "access_token" in d:
                return d["access_token"]
            raise ValueError(f"Token error: {d.get('error_description', d)}")
        except Exception as exc:
            if attempt == 2:
                raise
            log.warning("Token attempt %d: %s", attempt + 1, exc)
    raise RuntimeError("Token refresh exhausted retries")


# ── Metadata ──────────────────────────────────────────────────────────────────

def _build_meta(script: dict, topic: dict, timeline: dict, profile: str) -> dict:
    meta  = script.get("metadata", {})
    title = (meta.get("title") or topic["title"])[:95]

    # Description: content + optional timestamps + source + hashtags
    parts = [title, ""]
    if timeline["total_duration_seconds"] > 60:
        t = 0
        for sc in timeline["scenes"]:
            mm, ss = divmod(int(t), 60)
            parts.append(f"{mm}:{ss:02d} - {sc['segment_label']}")
            t += sc["duration_ms"] / 1000
        parts.append("")

    parts += [
        f"Source: {topic['source']} — {topic.get('article_url', '')}",
        "",
        "#VisionaryMinds #News #BreakingNews #WorldNews",
    ]
    description = "\n".join(parts)[:4900]

    tags = (
        meta.get("tags", [])
        + ["news", "world news", "breaking news", "VisionaryMinds",
           topic.get("intent", "news").lower()]
    )[:30]

    return {"title": title, "description": description, "tags": tags}


# ── Upload ────────────────────────────────────────────────────────────────────

def _upload(video_path: Path, meta: dict, token: str,
            title: str, is_short: bool) -> str | None:
    size   = video_path.stat().st_size
    cat_id = "25"   # 25 = News & Politics

    for attempt in range(3):
        try:
            r = requests.post(
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status",
                headers={
                    "Authorization":           f"Bearer {token}",
                    "Content-Type":            "application/json",
                    "X-Upload-Content-Type":   "video/mp4",
                    "X-Upload-Content-Length": str(size),
                },
                json={
                    "snippet": {
                        "title":       title[:100],
                        "description": meta["description"],
                        "tags":        meta["tags"],
                        "categoryId":  cat_id,
                    },
                    "status": {
                        "privacyStatus":           "public",
                        "selfDeclaredMadeForKids": False,
                    },
                },
                timeout=30,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Init {r.status_code}: {r.text[:150]}")

            upload_url = r.headers["Location"]
            with open(str(video_path), "rb") as f:
                up = requests.put(
                    upload_url,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                    data=f,
                    timeout=600,
                )
            if up.status_code in (200, 201):
                vid = up.json()["id"]
                log.info("  Uploaded: https://youtube.com/watch?v=%s", vid)
                return vid
            raise RuntimeError(f"Upload {up.status_code}: {up.text[:150]}")

        except Exception as exc:
            log.warning("Upload attempt %d: %s", attempt + 1, exc)
            if attempt == 2:
                return None


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def _extract_thumb(video: Path, thumb: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "2", "-i", str(video),
         "-vframes", "1", "-q:v", "2", str(thumb)],
        capture_output=True, timeout=30,
    )
    if thumb.exists():
        log.info("  Thumbnail extracted at 2s")


def _upload_thumb(video_id: str, thumb: Path, token: str) -> None:
    if not (thumb.exists() and thumb.stat().st_size > 0):
        return
    try:
        with open(str(thumb), "rb") as f:
            r = requests.post(
                f"https://www.googleapis.com/upload/youtube/v3/"
                f"thumbnails/set?videoId={video_id}",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("thumbnail.jpg", f, "image/jpeg")},
                timeout=60,
            )
        if r.ok:
            log.info("  Thumbnail uploaded")
        else:
            log.warning("  Thumbnail HTTP %d", r.status_code)
    except Exception as exc:
        log.warning("  Thumbnail: %s", exc)


# ── Playlist ──────────────────────────────────────────────────────────────────

def _playlist(token: str, name: str) -> str | None:
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/playlists",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "snippet", "mine": "true", "maxResults": "50"},
            timeout=15,
        )
        if r.ok:
            for item in r.json().get("items", []):
                if item["snippet"]["title"].lower() == name.lower():
                    return item["id"]
    except Exception:
        pass

    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            json={
                "snippet": {"title": name[:100], "description": "VisionaryMinds News"},
                "status":  {"privacyStatus": "public"},
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            return r.json()["id"]
    except Exception:
        pass
    return None


def _add_to_playlist(token: str, video_id: str, playlist_id: str) -> None:
    try:
        requests.post(
            "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            json={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }},
            timeout=15,
        )
    except Exception:
        pass
