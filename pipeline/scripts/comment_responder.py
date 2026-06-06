"""
Comment Auto-Responder

Fetches new comments on recent videos and replies within 1 hour.
YouTube algorithm sees fast engagement → boosts video recommendations.

Runs as separate GitHub Actions job every hour.
Requires same YouTube OAuth credentials as uploader.
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent / "logs"

# Varied reply templates — rotated to avoid spam detection
_REPLIES: list[str] = [
    "Thanks for watching! 🙌 Which fact surprised you the most?",
    "So glad you're here! 🌍 Stay tuned — more mind-blowing facts daily!",
    "Love your comment! 🔥 Subscribe for a new fact every single day!",
    "Great question! 💡 We cover this topic more in our other videos!",
    "You're awesome for watching! 🚀 More incredible facts coming tomorrow!",
    "Thanks for the support! 🌟 Tell us which topic you want next!",
    "Mind blown? 🤯 There's so much more — new video every day!",
    "Amazing to have you here! ⚡ Share this with someone who needs to know this!",
    "Facts change everything! 🌏 Subscribe so you never miss one!",
    "Thank you! 💫 Drop a topic you want us to cover next!",
]

# Don't reply to same video more than this many times per run
_MAX_REPLIES_PER_VIDEO = 5


def _token() -> str | None:
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":     os.getenv("YOUTUBE_CLIENT_ID"),
                "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"),
                "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN"),
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        d = r.json()
        return d.get("access_token")
    except Exception as exc:
        log.error("Token error: %s", exc)
        return None


def _get_recent_video_ids(token: str) -> list[str]:
    """Get video IDs from last 7 days via video_results.json."""
    try:
        path = _LOGS_DIR / "video_results.json"
        if not path.exists():
            return []
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        results = json.loads(path.read_text())
        return [
            r["video_id"] for r in results
            if r.get("uploaded_at", "") >= cutoff
            and r.get("video_id")
        ][-20:]  # last 20 videos max
    except Exception as exc:
        log.debug("Video IDs error: %s", exc)
        return []


def _get_unreplied_comments(token: str, video_id: str) -> list[dict]:
    """Fetch top-level comments that have no reply yet."""
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/commentThreads",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "part":       "snippet,replies",
                "videoId":    video_id,
                "maxResults": 20,
                "order":      "time",
            },
            timeout=15,
        )
        if not r.ok:
            return []

        unreplied = []
        for item in r.json().get("items", []):
            # Skip if already has replies
            if item.get("replies"):
                continue
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            # Skip our own comments
            if snippet.get("authorChannelId", {}).get("value") == \
               item["snippet"].get("channelId"):
                continue
            unreplied.append({
                "comment_id": item["snippet"]["topLevelComment"]["id"],
                "text":       snippet.get("textDisplay", ""),
                "author":     snippet.get("authorDisplayName", ""),
            })
        return unreplied

    except Exception as exc:
        log.debug("Comments fetch error: %s", exc)
        return []


def _reply(token: str, comment_id: str, text: str) -> bool:
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/comments?part=snippet",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {
                    "parentId":     comment_id,
                    "textOriginal": text,
                }
            },
            timeout=15,
        )
        return r.ok
    except Exception as exc:
        log.debug("Reply error: %s", exc)
        return False


def _load_replied(logs_dir: Path) -> set[str]:
    try:
        path = logs_dir / "replied_comments.json"
        if path.exists():
            return set(json.loads(path.read_text()))
    except Exception:
        pass
    return set()


def _save_replied(logs_dir: Path, replied: set[str]) -> None:
    try:
        path = logs_dir / "replied_comments.json"
        # Keep last 5000 comment IDs
        trimmed = list(replied)[-5000:]
        path.write_text(json.dumps(trimmed, indent=2))
    except Exception:
        pass


def run_comment_responder() -> None:
    # Analyze all comments for pipeline self-correction
    try:
        from comment_analyzer import run_comment_analyzer
        run_comment_analyzer()
    except Exception as exc:
        log.debug("Comment analyzer skipped: %s", exc)

    token = _token()
    if not token:
        log.error("Comment responder: token failed")
        return

    video_ids = _get_recent_video_ids(token)
    if not video_ids:
        log.info("Comment responder: no recent videos found")
        return

    replied_ids = _load_replied(_LOGS_DIR)
    total_replied = 0

    for video_id in video_ids:
        comments = _get_unreplied_comments(token, video_id)
        replied_this_video = 0

        for comment in comments:
            cid = comment["comment_id"]

            # Skip already replied
            if cid in replied_ids:
                continue

            # Pick random reply
            reply_text = random.choice(_REPLIES)

            success = _reply(token, cid, reply_text)
            if success:
                replied_ids.add(cid)
                total_replied += 1
                replied_this_video += 1
                log.info("Replied to comment on video %s (%s...)",
                         video_id, comment["text"][:40])
                time.sleep(2)  # avoid rate limit

            if replied_this_video >= _MAX_REPLIES_PER_VIDEO:
                break

        if total_replied >= 20:  # max 20 replies per run
            break

    _save_replied(_LOGS_DIR, replied_ids)
    log.info("Comment responder: %d replies sent", total_replied)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run_comment_responder()
