"""
STEP 12 — Upload + Metadata

YouTube resumable upload.
Thumbnail: uses the Pillow-designed image from thumbnail_generator (not a frame grab).
Description: proper chapter markers + category hashtags.
Post-upload:
  • SRT captions uploaded via captions.insert (boosts search indexing + accessibility)
  • Engagement comment posted via commentThreads.insert
  • Auto-assigns to category-specific playlist

Fixes applied vs original:
  1. _upload()        — 403 is no longer retried; reason field logged for diagnosis
  2. upload_video()   — token re-fetched before each post-upload API call
  3. _post_pinned_comment() — removed broken pin attempt (YouTube Data API v3
                              does not expose setModerationStatus for pinning);
                              comment is posted correctly and that is all the API allows
  4. _playlist()      — playlist IDs cached to disk; prevents duplicate playlist
                        creation on re-runs / retries
"""

import json
import logging
import os
import random
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_PLAYLISTS = {
    "SPACE":       "MindBlownFacts — Space",
    "SCIENCE":     "MindBlownFacts — Science",
    "HISTORY":     "MindBlownFacts — History",
    "ANIMALS":     "MindBlownFacts — Animals",
    "NATURE":      "MindBlownFacts — Nature",
    "GEOGRAPHY":   "MindBlownFacts — Geography",
    "OCEAN":       "MindBlownFacts — Ocean",
    "CULTURE":     "MindBlownFacts — Culture",
    "TECHNOLOGY":  "MindBlownFacts — Technology",
    "PSYCHOLOGY":  "MindBlownFacts — Psychology",
    "MYTHOLOGY":   "MindBlownFacts — Mythology",
    "MEDICINE":    "MindBlownFacts — Medicine",
    "MATHEMATICS": "MindBlownFacts — Mathematics",
    "ECONOMICS":   "MindBlownFacts — Economics",
    "PHYSICS":     "MindBlownFacts — Physics",
}

_LOGS_DIR            = Path(__file__).parent.parent / "logs"
_PLAYLIST_CACHE_FILE = _LOGS_DIR / "playlist_ids.json"


# ── Public entry point ────────────────────────────────────────────────────────

def upload_video(
    video_path:    Path,
    thumb_path:    Path,
    script:        dict,
    topic:         dict,
    timeline:      dict,
    profile:       str,
    subtitles_dir: Path | None = None,
) -> str | None:
    """
    Input:
        video_path    — Path to encoded .mp4 file
        thumb_path    — Path to designed thumbnail .jpg
        script        — dict with keys: metadata.title, metadata.description,
                        metadata.tags, metadata.engagement_question
        topic         — dict with keys: title, intent
        timeline      — dict with keys: scenes[], total_duration_seconds
        profile       — "shorts" | "standard"
        subtitles_dir — Path to directory containing sub_N.srt files (optional)

    Transformation:
        1. Refresh OAuth token
        2. Build YouTube metadata (title, description, tags, hashtags)
        3. Resumable upload → get video_id
        4. Re-fetch token, upload thumbnail
        5. Re-fetch token, upload SRT captions
        6. Re-fetch token, post engagement comment
        7. Re-fetch token, resolve/create playlist, add video

    Output:
        video_id (str) on success, None on failure

    Variants:
        - If profile == "shorts", appends #Shorts to title
        - If subtitles_dir is None, caption upload is skipped
    """
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

    # Fix 2: notify subscribers only on first video of the day — prevents
    # 3 daily notifications which causes subscribers to mute the channel.
    notify = _should_notify()

    # ── Upload video ──────────────────────────────────────────────────────────
    video_id = _upload(video_path, metadata, token, title, is_short,
                       notify_subscribers=notify)
    if not video_id:
        return None

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    # Re-fetch token: large video upload may have consumed most of the 3600s TTL
    try:
        token = _token()
    except Exception as exc:
        log.warning("Token re-fetch before thumbnail failed: %s", exc)
    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        _upload_thumb(video_id, thumb_path, token)

    # ── Captions ──────────────────────────────────────────────────────────────
    if subtitles_dir:
        try:
            token = _token()
        except Exception as exc:
            log.warning("Token re-fetch before captions failed: %s", exc)
        _upload_captions(video_id, subtitles_dir, timeline, token)

    # ── Engagement comment ────────────────────────────────────────────────────
    try:
        token = _token()
    except Exception as exc:
        log.warning("Token re-fetch before comment failed: %s", exc)
    question = script.get("metadata", {}).get("engagement_question", "")
    if not question or "Which fact" in question:
        _title = topic.get("title", "this topic")[:45]
        question = random.choice([
            f"What did you NOT know about {_title}? Tell us below! 👇",
            "Did you already know this? Comment YES or NO! 🤔",
            "Which part surprised you most? Drop it below! 💬",
            "Would you have believed this before watching? 🌍",
        ])
    _post_comment(video_id, question, token)

    # ── Playlist ──────────────────────────────────────────────────────────────
    try:
        token = _token()
    except Exception as exc:
        log.warning("Token re-fetch before playlist failed: %s", exc)
    pl_name = _PLAYLISTS.get(topic.get("intent", "").upper(), "MindBlownFacts — World")
    pl_id   = _playlist(token, pl_name)
    if pl_id:
        _add_to_playlist(token, video_id, pl_id)

    return video_id


# ── Token ─────────────────────────────────────────────────────────────────────

def _token() -> str:
    """
    Input:
        YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN — env vars

    Transformation:
        POST to Google OAuth2 token endpoint with refresh_token grant

    Output:
        access_token string (TTL = 3600s from issue time)

    Variants:
        Retries up to 3 times on connection errors; raises RuntimeError on auth failure
    """
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
        except ValueError:
            raise  # auth errors are not retryable
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError("Token refresh exhausted retries") from exc
            log.warning("Token attempt %d: %s", attempt + 1, exc)
    raise RuntimeError("Token refresh exhausted retries")


# ── Metadata ──────────────────────────────────────────────────────────────────

def _build_meta(script: dict, topic: dict, timeline: dict, profile: str) -> dict:
    """
    Input:
        script   — LLM output dict
        topic    — topic selector output dict
        timeline — assembled scene timeline dict
        profile  — "shorts" | "standard"

    Transformation:
        Assembles title (≤95 chars), description (≤4900 chars with chapter markers),
        tags list (≤30 items), hashtag block

    Output:
        dict with keys: title (str), description (str), tags (list[str])
    """
    meta  = script.get("metadata", {})
    title = (meta.get("title") or topic["title"])[:95]
    cat   = topic.get("intent", "SCIENCE")
    is_short = profile == "shorts"

    # ── SEO-optimised description ─────────────────────────────────────────────
    raw_desc   = meta.get("description", "")
    desc_lines = raw_desc.split("\n") if raw_desc else []
    first_line = desc_lines[0].strip() if desc_lines else title
    rest_lines = "\n".join(desc_lines[1:]).strip() if len(desc_lines) > 1 else ""

    # Fix 3: #Shorts must be in FIRST LINE of description for Shorts algorithm
    if is_short:
        first_line = f"#Shorts {first_line}" if "#Shorts" not in first_line else first_line

    # Fix 5: channel link in every description — converts viewers to subscribers
    channel_link = "🔔 Subscribe for daily mind-blowing facts: https://www.youtube.com/@MindBlownFacts-z8o"

    parts: list[str] = [
        first_line,
        "",
        rest_lines if rest_lines else (
            f"Discover the most mind-blowing facts about {cat.lower()} "
            f"that most people never learn. Subscribe to MindBlownFacts "
            f"for new facts every day."
        ),
        "",
        channel_link,
        "",
    ]

    # Fix 4: descriptive chapter titles instead of HOOK/TENSION/CORE labels
    if timeline["total_duration_seconds"] > 60:
        parts.append("📌 Chapters")
        t    = 0.0
        seen = set()
        for sc in timeline["scenes"]:
            mm, ss = divmod(int(t), 60)
            label  = sc["segment_label"]
            if not label.startswith("_") and label not in seen:
                seen.add(label)
                parts.append(f"{mm}:{ss:02d} — {_chapter_label(label)}")
            t += sc["duration_ms"] / 1000
        parts.append("")

    parts.append(_build_hashtags(cat, meta.get("tags", []), profile))
    description = "\n".join(parts)[:4900]

    # ── SEO tags — mix broad + specific for best reach ────────────────────────
    cat_lower = cat.lower()
    tags = list(dict.fromkeys(
        meta.get("tags", [])
        + [
            "facts", "did you know", "world facts", "real world facts",
            "mind blowing facts", "educational", "facts you didn't know",
            "interesting facts", "amazing facts", "MindBlownFacts",
            f"{cat_lower} facts", f"{cat_lower} explained", cat_lower,
            "facts in hindi", "facts about the world", "top facts",
        ]
    ))[:30]

    return {"title": title, "description": description, "tags": tags}


_CAT_HASHTAGS: dict[str, list[str]] = {
    "SPACE":       ["#Space", "#Universe", "#NASA", "#Cosmos", "#Astronomy",
                   "#Galaxy", "#BlackHole", "#SolarSystem", "#SpaceFacts", "#Planets"],
    "SCIENCE":     ["#Science", "#ScienceFacts", "#Biology", "#Discovery",
                   "#Research", "#Experiment", "#Innovation", "#ScienceExplained"],
    "HISTORY":     ["#History", "#Ancient", "#Archaeology", "#HistoryFacts",
                   "#AncientCivilization", "#Historical", "#HistoryExplained"],
    "ANIMALS":     ["#Animals", "#Wildlife", "#WildAnimals", "#AnimalFacts",
                   "#Predator", "#Survival", "#NatureWild", "#AnimalLife"],
    "NATURE":      ["#Nature", "#Earth", "#NatureFacts", "#NaturalDisaster",
                   "#Environment", "#Climate", "#NatureExplained", "#Planet"],
    "GEOGRAPHY":   ["#Geography", "#WorldFacts", "#Travel", "#Countries",
                   "#GeographyFacts", "#Geopolitics", "#Exploration", "#Maps"],
    "OCEAN":       ["#Ocean", "#DeepSea", "#MarineLife", "#Underwater",
                   "#OceanFacts", "#SeaCreatures", "#OceanExplained", "#Marine"],
    "CULTURE":     ["#Culture", "#CultureFacts", "#Tradition", "#AncientHistory",
                   "#CulturalFacts", "#Civilisation", "#Ritual", "#Heritage"],
    "TECHNOLOGY":  ["#Technology", "#Tech", "#AI", "#ArtificialIntelligence",
                   "#TechFacts", "#FutureTech", "#Innovation", "#TechExplained"],
    "PSYCHOLOGY":  ["#Psychology", "#PsychologyFacts", "#HumanBehavior", "#MindFacts",
                   "#Brain", "#BrainFacts", "#MentalScience", "#PsychFacts"],
    "MYTHOLOGY":   ["#Mythology", "#MythologyFacts", "#AncientMyths", "#Legend",
                   "#GreekMythology", "#NorseMythology", "#MythsExplained", "#Legends"],
    "MEDICINE":    ["#Medicine", "#MedicalFacts", "#Health", "#HealthFacts",
                   "#HumanBody", "#Biology", "#MedicalScience", "#BodyFacts"],
    "MATHEMATICS": ["#Mathematics", "#MathFacts", "#Numbers", "#MathExplained",
                   "#Geometry", "#MathematicsExplained", "#NumberFacts", "#Maths"],
    "ECONOMICS":   ["#Economics", "#EconomicsFacts", "#Money", "#MoneyFacts",
                   "#Finance", "#FinanceFacts", "#WealthFacts", "#EconomicsExplained"],
    "PHYSICS":     ["#Physics", "#PhysicsFacts", "#Quantum", "#QuantumPhysics",
                   "#PhysicsExplained", "#Science", "#Relativity", "#EnergyFacts"],
}


def _should_notify() -> bool:
    """
    Returns True only for the first upload of the day.
    Prevents 3 daily notifications which causes subscribers to mute the channel.
    Tracks state in logs/notify_state.json.
    """
    import datetime
    state_path = _LOGS_DIR / "notify_state.json"
    today      = datetime.datetime.utcnow().date().isoformat()
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get("last_notify_date") == today:
            log.info("Notification suppressed — already notified today")
            return False
        state["last_notify_date"] = today
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
        log.info("Notification enabled — first upload today")
        return True
    except Exception as exc:
        log.debug("Notify state error: %s", exc)
        return True  # default to notify on error


_CHAPTER_LABELS: dict[str, str] = {
    "HOOK":    "Introduction",
    "TENSION": "The Mystery",
    "CORE":    "The Real Explanation",
    "PAYOFF":  "The Shocking Truth",
    "CLOSE":   "Subscribe for More",
}


def _chapter_label(segment_label: str) -> str:
    """Convert internal segment label to viewer-friendly chapter title."""
    return _CHAPTER_LABELS.get(segment_label.upper(), segment_label.title())


def _build_hashtags(cat: str, script_tags: list, profile: str) -> str:
    base       = ["#MindBlownFacts", "#Facts", "#DidYouKnow", "#WorldFacts",
                  "#Educational", "#InterestingFacts", "#MindBlowing"]
    pool       = _CAT_HASHTAGS.get(cat.upper(), ["#WorldFacts"])
    chosen_cat = random.sample(pool, min(5, len(pool)))
    script_ht  = [f"#{t.replace(' ', '').title()}" for t in script_tags[:3]
                  if t and len(t) < 25]
    all_tags   = base + chosen_cat + script_ht
    if profile == "shorts":
        all_tags = ["#Shorts"] + all_tags
    return " ".join(all_tags)


# ── Upload ────────────────────────────────────────────────────────────────────

def _upload(
    video_path:         Path,
    meta:               dict,
    token:              str,
    title:              str,
    is_short:           bool,
    notify_subscribers: bool = True,
) -> str | None:
    """
    Input:
        video_path — Path to .mp4 file
        meta       — dict with description, tags
        token      — valid OAuth2 access token
        title      — final title string (≤100 chars, #Shorts appended if needed)
        is_short   — bool; sets madeForKids = False, categoryId = 22 for shorts

    Transformation:
        1. POST resumable upload init → receive Location header (upload_url)
        2. PUT video bytes to upload_url
        3. Parse video_id from 200/201 response

    Output:
        video_id string on success, None on failure

    Variants:
        - 403 → hard stop, no retry (quotaExceeded or insufficientPermissions)
        - 401 → token refreshed on next retry attempt
        - 5xx / connection error / timeout → exponential backoff, up to 5 attempts
        - 200 on init but bad Location header → RuntimeError → retry
    """
    size          = video_path.stat().st_size
    cat_id        = "22" if is_short else "27"   # 22 = People & Blogs, 27 = Education
    current_token = token

    for attempt in range(5):
        # Refresh token on every retry — a previous attempt may have taken long
        # enough that the original token is stale, or a 401 told us auth failed.
        if attempt > 0:
            try:
                current_token = _token()
                log.info("  Token refreshed before retry %d/5", attempt + 1)
            except Exception as exc:
                log.warning("  Token refresh failed on retry %d: %s — using previous token",
                            attempt + 1, exc)

        try:
            # ── Step 1: Resumable upload init ─────────────────────────────────
            r = requests.post(
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status",
                headers={
                    "Authorization":           f"Bearer {current_token}",
                    "Content-Type":            "application/json",
                    "X-Upload-Content-Type":   "video/mp4",
                    "X-Upload-Content-Length": str(size),
                },
                json={
                    "snippet": {
                        "title":                title[:100],
                        "description":          meta["description"],
                        "tags":                 meta["tags"],
                        "categoryId":           cat_id,
                        "defaultLanguage":      "en",       # Fix 1: language indexing
                        "defaultAudioLanguage": "en",
                    },
                    "status": {
                        "privacyStatus":           "public",
                        "selfDeclaredMadeForKids": False,
                        "notifySubscribers":       notify_subscribers,  # Fix 2
                    },
                },
                timeout=30,
            )

            # ── 403: non-retryable — quota exhausted or wrong OAuth scope ─────
            if r.status_code == 403:
                body = {}
                try:
                    body = r.json()
                except Exception:
                    pass
                reason = (
                    body.get("error", {})
                        .get("errors", [{}])[0]
                        .get("reason", "unknown")
                )
                log.error(
                    "Upload blocked (403/%s) — aborting all retries. "
                    "quotaExceeded → quota resets midnight Pacific. "
                    "insufficientPermissions → re-auth with youtube.upload scope. "
                    "forbidden → verify YouTube Data API v3 is enabled in GCP project.",
                    reason,
                )
                return None  # hard exit — no retry

            # ── 401: token invalid — next retry will refresh it ───────────────
            if r.status_code == 401:
                raise RuntimeError("Init 401 Unauthorized — token will be refreshed on retry")

            # ── Any other non-200: retryable ──────────────────────────────────
            if r.status_code != 200:
                raise RuntimeError(f"Init {r.status_code}: {r.text[:150]}")

            upload_url = r.headers.get("Location", "")
            if not upload_url:
                raise RuntimeError("Init 200 but no Location header in response")

            # ── Step 2: PUT video bytes ───────────────────────────────────────
            with open(str(video_path), "rb") as f:
                up = requests.put(
                    upload_url,
                    headers={
                        "Content-Type":   "video/mp4",
                        "Content-Length": str(size),
                    },
                    data=f,
                    timeout=600,
                )

            if up.status_code in (200, 201):
                vid = up.json()["id"]
                log.info("  Uploaded: https://youtube.com/watch?v=%s", vid)
                return vid

            raise RuntimeError(f"Upload PUT {up.status_code}: {up.text[:150]}")

        except RuntimeError as exc:
            log.warning("Upload attempt %d/5: %s", attempt + 1, exc)
            if attempt == 4:
                return None
            wait = (2 ** attempt) + random.uniform(0.5, 2.0)
            log.info("  Retrying in %.1fs …", wait)
            time.sleep(wait)

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            log.warning("Upload attempt %d/5 network error: %s",
                        attempt + 1, str(exc)[:120])
            if attempt == 4:
                return None
            wait = (2 ** attempt) + random.uniform(0.5, 2.0)
            log.info("  Retrying in %.1fs …", wait)
            time.sleep(wait)

        except Exception as exc:
            log.error("Upload unexpected error: %s", exc)
            return None  # truly unknown — do not retry

    return None


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def _upload_thumb(video_id: str, thumb: Path, token: str) -> None:
    """
    Input:
        video_id — YouTube video ID string
        thumb    — Path to .jpg thumbnail (Pillow-generated)
        token    — valid OAuth2 access token

    Transformation:
        Multipart POST to thumbnails.set endpoint

    Output:
        None (side effect: thumbnail set on video)

    Variants:
        403 → channel not verified OR token missing youtube scope
    """
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
                "  Thumbnail 403 — channel not verified OR token lacks youtube scope. "
                "Verify at YouTube Studio → Settings → Channel → Feature eligibility."
            )
        else:
            log.warning("  Thumbnail HTTP %d: %s", r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("  Thumbnail upload error: %s", exc)


# ── SRT captions ──────────────────────────────────────────────────────────────

def _upload_captions(video_id: str, subtitles_dir: Path, timeline: dict, token: str) -> None:
    """
    Input:
        video_id      — YouTube video ID
        subtitles_dir — directory containing sub_N.srt files (one per scene)
        timeline      — dict with scenes[] to determine scene order
        token         — valid OAuth2 access token

    Transformation:
        Merges all per-scene SRT files into a single renumbered SRT blob,
        initiates a resumable caption upload, PUTs the SRT content

    Output:
        None (side effect: English captions attached to video)

    Variants:
        403 → token missing youtube.force-ssl scope
        Empty SRT → skipped silently
    """
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
            log.info("  Captions: no SRT content found — skipping")
            return

        srt_bytes = "\n".join(combined).encode("utf-8")

        r = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/captions"
            "?uploadType=resumable&part=snippet",
            headers={
                "Authorization":           f"Bearer {token}",
                "Content-Type":            "application/json",
                "X-Upload-Content-Type":   "text/plain",
                "X-Upload-Content-Length": str(len(srt_bytes)),
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
                    "  Caption 403 — token likely missing youtube.force-ssl scope. "
                    "Re-generate OAuth refresh token with scopes: "
                    "youtube, youtube.force-ssl, youtube.upload"
                )
            else:
                log.warning("  Caption init HTTP %d: %s", r.status_code, r.text[:120])
            return

        upload_url = r.headers.get("Location", "")
        if not upload_url:
            log.warning("  Caption init 200 but no Location header — skipping")
            return

        up = requests.put(
            upload_url,
            headers={"Content-Type": "text/plain"},
            data=srt_bytes,
            timeout=60,
        )
        if up.ok:
            log.info("  Captions uploaded")
        else:
            log.warning("  Caption upload HTTP %d: %s", up.status_code, up.text[:120])

    except Exception as exc:
        log.warning("  Captions error: %s", exc)


# ── Engagement comment ────────────────────────────────────────────────────────

def _post_comment(video_id: str, question: str, token: str) -> None:
    """
    Input:
        video_id — YouTube video ID
        question — engagement question string
        token    — valid OAuth2 access token

    Transformation:
        POST to commentThreads.insert — creates a top-level comment on the video.

    Output:
        None (side effect: comment posted on video)

    NOTE on pinning:
        YouTube Data API v3 does NOT expose a public pinning endpoint.
        comments.setModerationStatus exists but is restricted to CMS partners only.
        Pin manually in YouTube Studio after upload, or accept unpinned.

    Variants:
        403 → token missing youtube.force-ssl scope
        5s sleep before posting gives YouTube time to index the video
    """
    try:
        time.sleep(5)  # let YouTube index the video before commenting
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
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
        if r.ok:
            log.info("  Comment posted (pin manually in YouTube Studio if needed)")
        elif r.status_code == 403:
            log.warning(
                "  Comment 403 — token missing youtube.force-ssl scope. "
                "Re-generate OAuth refresh token with scopes: "
                "youtube, youtube.force-ssl, youtube.upload"
            )
        else:
            log.warning("  Comment HTTP %d: %s", r.status_code, r.text[:120])

    except Exception as exc:
        log.warning("  Comment error: %s", exc)


# ── Playlist ──────────────────────────────────────────────────────────────────

def _get_cached_playlist_id(name: str) -> str | None:
    """
    Input:  playlist name string
    Output: cached playlist ID string, or None if not cached
    """
    try:
        if _PLAYLIST_CACHE_FILE.exists():
            data = json.loads(_PLAYLIST_CACHE_FILE.read_text(encoding="utf-8"))
            return data.get(name)
    except Exception as exc:
        log.debug("Playlist cache read error: %s", exc)
    return None


def _cache_playlist_id(name: str, pl_id: str) -> None:
    """
    Input:  playlist name, playlist ID
    Output: None (side effect: ID written to playlist_ids.json)
    """
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if _PLAYLIST_CACHE_FILE.exists():
            data = json.loads(_PLAYLIST_CACHE_FILE.read_text(encoding="utf-8"))
        data[name] = pl_id
        _PLAYLIST_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.debug("Playlist cache write error: %s", exc)


def _playlist(token: str, name: str) -> str | None:
    """
    Input:
        token — valid OAuth2 access token
        name  — playlist title string

    Transformation:
        1. Check disk cache (playlist_ids.json) → return immediately if hit
        2. GET playlists.list (mine=true) → search by title
        3. If not found → POST playlists.insert to create it
        4. Cache result to disk

    Output:
        playlist ID string, or None on failure

    Variants:
        Cache prevents duplicate playlist creation on re-runs.
        maxResults=50 means channels with >50 playlists may miss the target —
        acceptable tradeoff vs full pagination for this use case.
    """
    # ── 1. Disk cache hit ─────────────────────────────────────────────────────
    cached = _get_cached_playlist_id(name)
    if cached:
        log.debug("Playlist cache hit: %s → %s", name, cached)
        return cached

    # ── 2. API lookup ─────────────────────────────────────────────────────────
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
                    pl_id = item["id"]
                    _cache_playlist_id(name, pl_id)
                    log.info("  Playlist found: %s (%s)", name, pl_id)
                    return pl_id
    except Exception as exc:
        log.warning("  Playlist lookup error: %s", exc)

    # ── 3. Create — only reached if not in cache and not found via API ────────
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {
                    "title":       name[:100],
                    "description": "MindBlownFacts Channel",
                },
                "status": {"privacyStatus": "public"},
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            pl_id = r.json()["id"]
            _cache_playlist_id(name, pl_id)
            log.info("  Playlist created: %s (%s)", name, pl_id)
            return pl_id
        log.warning("  Playlist create HTTP %d: %s", r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("  Playlist create error: %s", exc)

    return None


def _add_to_playlist(token: str, video_id: str, playlist_id: str) -> None:
    """
    Input:
        token       — valid OAuth2 access token
        video_id    — YouTube video ID
        playlist_id — target playlist ID

    Transformation:
        POST to playlistItems.insert

    Output:
        None (side effect: video added to playlist)
    """
    try:
        r = requests.post(
            "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind":    "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
            timeout=15,
        )
        if r.ok:
            log.info("  Added to playlist: %s", playlist_id)
        else:
            log.warning("  Playlist insert HTTP %d: %s", r.status_code, r.text[:120])
    except Exception as exc:
        log.warning("  Playlist insert error: %s", exc)