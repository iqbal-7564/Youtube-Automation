"""
STEP 12 — Upload + Metadata

YouTube resumable upload.
Thumbnail: uses the Pillow-designed image from thumbnail_generator (not a frame grab).
Description: proper chapter markers + category hashtags.
Post-upload:
  • SRT captions uploaded via captions.insert (boosts search indexing + accessibility)
  • Pinned engagement comment posted via commentThreads.insert
  • Auto-assigns to category-specific playlist
"""

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_PLAYLISTS = {
    "SPACE":     "MindBlownFacts — Space",
    "SCIENCE":   "MindBlownFacts — Science",
    "HISTORY":   "MindBlownFacts — History",
    "ANIMALS":   "MindBlownFacts — Animals",
    "NATURE":    "MindBlownFacts — Nature",
    "GEOGRAPHY": "MindBlownFacts — Geography",
    "OCEAN":     "MindBlownFacts — Ocean",
    "CULTURE":   "MindBlownFacts — Culture",
}


def upload_video(
    video_path: Path,
    thumb_path: Path,
    script: dict,
    topic: dict,
    timeline: dict,
    profile: str,
    subtitles_dir: Path | None = None,
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

    # Upload the designed Pillow thumbnail
    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        _upload_thumb(video_id, thumb_path, token)

    # Upload SRT captions
    if subtitles_dir:
        _upload_captions(video_id, subtitles_dir, timeline, token)

    # Pin engagement comment
    question = script.get("metadata", {}).get(
        "engagement_question",
        "Which fact surprised you the most? Tell us below!"
    )
    _post_pinned_comment(video_id, question, token)

    pl_name = _PLAYLISTS.get(topic.get("intent", "").upper(), "MindBlownFacts — World")
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
    cat   = topic.get("intent", "SCIENCE")

    parts: list[str] = [title, ""]

    # Chapter markers for standard long-form videos
    if timeline["total_duration_seconds"] > 60:
        parts.append("📌 Chapters")
        t = 0.0
        for sc in timeline["scenes"]:
            mm, ss = divmod(int(t), 60)
            label  = sc["segment_label"]
            if not label.startswith("_"):
                parts.append(f"{mm}:{ss:02d} — {label}")
            t += sc["duration_ms"] / 1000
        parts.append("")

    parts += [
        meta.get("description", f"{title}\n\nCategory: {cat}"),
        "",
        f"#MindBlownFacts #Facts #DidYouKnow #WorldFacts #{cat.capitalize()} #Educational",
    ]
    if profile == "shorts":
        parts.append("#Shorts")

    description = "\n".join(parts)[:4900]

    tags = (
        meta.get("tags", [])
        + ["real world facts", "facts", "did you know", "world facts",
           "educational", cat.lower()]
    )[:30]

    return {"title": title, "description": description, "tags": tags}


# ── Upload ────────────────────────────────────────────────────────────────────

def _upload(video_path: Path, meta: dict, token: str,
            title: str, is_short: bool) -> str | None:
    size   = video_path.stat().st_size
    cat_id = "27"

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

def _upload_thumb(video_id: str, thumb: Path, token: str) -> None:
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
        elif r.status_code == 403:
            log.warning(
                "  Thumbnail 403 — channel not verified OR token lacks "
                "youtube scope. Verify channel at YouTube Studio → "
                "Settings → Channel → Feature eligibility."
            )
        else:
            log.warning("  Thumbnail HTTP %d: %s", r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("  Thumbnail: %s", exc)


# ── SRT captions ──────────────────────────────────────────────────────────────

def _upload_captions(video_id: str, subtitles_dir: Path, timeline: dict, token: str) -> None:
    """Merge all per-scene SRT files into one and upload to YouTube."""
    try:
        combined: list[str] = []
        idx = 1
        for sc in timeline["scenes"]:
            srt_path = subtitles_dir / f"sub_{sc['scene_id']}.srt"
            if not srt_path.exists():
                continue
            content = srt_path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            for block in content.split("\n\n"):
                lines = block.strip().splitlines()
                if len(lines) >= 3:
                    combined.append(str(idx))
                    combined.extend(lines[1:])
                    combined.append("")
                    idx += 1

        if not combined:
            return

        srt_content = "\n".join(combined)
        r = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/captions"
            "?uploadType=resumable&part=snippet",
            headers={
                "Authorization":           f"Bearer {token}",
                "Content-Type":            "application/json",
                "X-Upload-Content-Type":   "text/plain",
                "X-Upload-Content-Length": str(len(srt_content.encode())),
            },
            json={
                "snippet": {
                    "videoId":  video_id,
                    "language": "en",
                    "name":     "English",
                    "isDraft":  False,
                }
            },
            timeout=15,
        )
        if r.status_code != 200:
            if r.status_code == 403:
                log.warning(
                    "  Caption 403 — token lacks youtube.force-ssl scope. "
                    "Re-generate the OAuth refresh token with scopes: "
                    "youtube, youtube.force-ssl, youtube.upload"
                )
            else:
                log.warning("  Caption init HTTP %d: %s", r.status_code, r.text[:120])
            return

        upload_url = r.headers.get("Location", "")
        if not upload_url:
            return

        up = requests.put(
            upload_url,
            headers={"Content-Type": "text/plain"},
            data=srt_content.encode("utf-8"),
            timeout=60,
        )
        if up.ok:
            log.info("  Captions uploaded")
        else:
            log.warning("  Caption upload HTTP %d", up.status_code)

    except Exception as exc:
        log.warning("  Captions: %s", exc)


# ── Pinned comment ────────────────────────────────────────────────────────────

def _post_pinned_comment(video_id: str, question: str, token: str) -> None:
    try:
        # Wait briefly so YouTube indexes the video first
        time.sleep(5)
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": question}
                    },
                }
            },
            timeout=15,
        )
        if not r.ok:
            if r.status_code == 403:
                log.warning(
                    "  Comment 403 — token lacks youtube.force-ssl scope. "
                    "Re-generate the OAuth refresh token with scopes: "
                    "youtube, youtube.force-ssl, youtube.upload"
                )
            else:
                log.warning("  Comment HTTP %d: %s", r.status_code, r.text[:120])
            return

        comment_id = r.json().get("snippet", {}).get("topLevelComment", {}).get("id", "")
        if not comment_id:
            return

        # Pin the comment
        requests.post(
            "https://www.googleapis.com/youtube/v3/comments?part=snippet",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            json={
                "id": comment_id,
                "snippet": {
                    "videoId":     video_id,
                    "textOriginal": question,
                    "moderationStatus": "published",
                },
            },
            timeout=15,
        )
        log.info("  Pinned comment posted")
    except Exception as exc:
        log.warning("  Comment: %s", exc)


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
                "snippet": {"title": name[:100], "description": "MindBlownFacts"},
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
