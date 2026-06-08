"""
Comment Analyzer — Learn from viewer feedback to auto-fix pipeline

Reads comments from ALL channel videos, uses Groq to classify fault types,
saves auto_fixes.json that each pipeline script reads before running.

Threshold: 3+ viewers reporting same fault → fix applied automatically.
Recalculates from scratch every run so fixes stay proportional to complaints.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_LOGS_DIR        = Path(__file__).parent.parent / "logs"
_AUTO_FIXES_PATH = _LOGS_DIR / "auto_fixes.json"

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"

_FAULT_THRESHOLD = 3   # min complaints to trigger a fix
_MAX_VIDEOS      = 30  # max videos to analyze per run


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
        return r.json().get("access_token")
    except Exception as exc:
        log.error("Token error: %s", exc)
        return None


def _get_all_video_ids() -> list[str]:
    """Return ALL video IDs from video_results.json (no time filter)."""
    try:
        path = _LOGS_DIR / "video_results.json"
        if not path.exists():
            return []
        results = json.loads(path.read_text())
        return [r["video_id"] for r in results if r.get("video_id")]
    except Exception as exc:
        log.debug("Video IDs error: %s", exc)
        return []


def _get_comments(token: str, video_id: str) -> list[str]:
    """Fetch up to 20 top-level comments from a video."""
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/commentThreads",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "part":       "snippet",
                "videoId":    video_id,
                "maxResults": 20,
                "order":      "relevance",
            },
            timeout=15,
        )
        if not r.ok:
            return []
        return [
            item["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
            for item in r.json().get("items", [])
        ]
    except Exception:
        return []


def _classify_comments(comments: list[str]) -> list[dict]:
    """Use Groq to classify each comment into a technical OR content fault type."""
    if not comments:
        return []

    keys = [
        os.getenv("GROQ_API_KEY_1", "").strip(),
        os.getenv("GROQ_API_KEY_2", "").strip(),
    ]

    batch = "\n".join(f"{i+1}. {c[:200]}" for i, c in enumerate(comments))

    for key in [k for k in keys if k]:
        try:
            r = requests.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [{
                        "role": "system",
                        "content": (
                            "Classify YouTube comments for a facts channel. "
                            "For each comment return ONE type from this list:\n\n"
                            "TECHNICAL:\n"
                            "subtitle_fast — subtitles too fast, can't read\n"
                            "subtitle_slow — subtitles too slow\n"
                            "audio_low — audio too quiet\n"
                            "audio_high — audio too loud or distorted\n"
                            "image_blurry — images blurry or low quality\n"
                            "video_short — video too short\n"
                            "video_long — video too long or boring\n"
                            "speech_fast — narrator speaks too fast\n"
                            "speech_slow — narrator speaks too slow\n"
                            "font_small — text too small to read\n"
                            "topic_request:CATEGORY — wants more videos on CATEGORY "
                            "(SPACE/SCIENCE/HISTORY/ANIMALS/NATURE/GEOGRAPHY/OCEAN/"
                            "CULTURE/TECHNOLOGY/PSYCHOLOGY/MYTHOLOGY/MEDICINE/"
                            "MATHEMATICS/ECONOMICS/PHYSICS)\n\n"
                            "CONTENT (script quality):\n"
                            "facts_too_basic — facts are obvious, viewer already knew them\n"
                            "facts_too_complex — too technical, hard to follow\n"
                            "need_more_examples — wants more analogies or comparisons\n"
                            "factually_wrong — claims seem incorrect or fake\n"
                            "boring_middle — lost interest in the middle section\n"
                            "great_hook — praises the opening/hook specifically\n"
                            "want_more_drama — wants more exciting/dramatic delivery\n"
                            "want_simpler_words — language too difficult\n"
                            "loved_content — praises the facts/content quality\n\n"
                            "positive — happy general comment, no specific fault\n"
                            "none — irrelevant or spam\n\n"
                            "Return ONLY valid JSON array: "
                            "[{\"n\": 1, \"fault\": \"type\"}, ...]"
                        ),
                    }, {
                        "role": "user",
                        "content": f"Classify:\n{batch}",
                    }],
                    "temperature": 0.1,
                    "max_tokens":  600,
                },
                timeout=20,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r"\[.*\]", raw, re.DOTALL)
                if m:
                    return json.loads(m.group())
        except Exception as exc:
            log.debug("Groq classify error: %s", exc)
    return []


def _build_script_feedback(fault_counts: dict) -> dict:
    """Convert content fault counts into a viewer note for script_generator."""
    T = _FAULT_THRESHOLD
    notes: list[str] = []

    if fault_counts.get("facts_too_basic", 0) >= T:
        notes.append(
            f"Viewers say facts are too basic ({fault_counts['facts_too_basic']} complaints). "
            "Use RARER, more counterintuitive facts. Avoid anything a viewer might already know."
        )
    if fault_counts.get("facts_too_complex", 0) >= T:
        notes.append(
            f"Viewers find content too complex ({fault_counts['facts_too_complex']} complaints). "
            "Use simpler language. Add everyday analogies. Explain each fact like talking to a smart 14-year-old."
        )
    if fault_counts.get("need_more_examples", 0) >= T:
        notes.append(
            f"Viewers want more examples ({fault_counts['need_more_examples']} complaints). "
            "Include at least 2 real-world comparisons per fact. Use scale analogies (e.g. 'that's like...')."
        )
    if fault_counts.get("factually_wrong", 0) >= T:
        notes.append(
            f"Viewers questioned factual accuracy ({fault_counts['factually_wrong']} complaints). "
            "Only use facts with extremely high certainty. Prefer officially confirmed scientific data. "
            "Add qualifiers like 'scientists discovered' or 'studies show'."
        )
    if fault_counts.get("boring_middle", 0) >= T:
        notes.append(
            f"Viewers lose interest in the middle ({fault_counts['boring_middle']} complaints). "
            "Make CORE section punchier: shorter sentences, more [WOW] moments, vary rhythm aggressively."
        )
    if fault_counts.get("want_more_drama", 0) >= T:
        notes.append(
            f"Viewers want more excitement ({fault_counts['want_more_drama']} complaints). "
            "Increase dramatic tension. Use more suspense language. Make facts feel urgent and impossible."
        )
    if fault_counts.get("want_simpler_words", 0) >= T:
        notes.append(
            f"Viewers want simpler words ({fault_counts['want_simpler_words']} complaints). "
            "Avoid jargon. Replace technical terms with plain English equivalents."
        )

    # Positive signals — reinforce what's working
    if fault_counts.get("great_hook", 0) >= 2:
        notes.append("Viewers love the hook style. Keep using strong impossibility/contradiction openings.")
    if fault_counts.get("loved_content", 0) >= 3:
        notes.append("Viewers are enjoying the content quality. Maintain current depth and fact selection.")

    return {
        "viewer_note":   "\n".join(notes) if notes else "",
        "fault_counts":  {k: v for k, v in fault_counts.items()
                          if k in ("facts_too_basic", "facts_too_complex",
                                   "need_more_examples", "factually_wrong",
                                   "boring_middle", "want_more_drama",
                                   "want_simpler_words", "great_hook", "loved_content")},
        "last_updated":  datetime.now(timezone.utc).isoformat(),
    }


def _compute_fixes(fault_counts: dict) -> dict:
    """Derive pipeline adjustments from fault counts. Recalculates from scratch."""
    T = _FAULT_THRESHOLD

    # Speech speed: net = fast_complaints - slow_complaints
    net_speech = fault_counts.get("speech_fast", 0) - fault_counts.get("speech_slow", 0)
    if net_speech >= T:
        tts_rate = -min(int(net_speech / T) * 5, 20)   # slower, max -20%
    elif -net_speech >= T:
        tts_rate = min(int(-net_speech / T) * 5, 10)    # faster, max +10%
    else:
        tts_rate = 0

    # Audio level
    net_audio = fault_counts.get("audio_low", 0) - fault_counts.get("audio_high", 0)
    if net_audio >= T:
        loudnorm = min(-14 + int(net_audio / T) * 2, -10)   # louder
    elif -net_audio >= T:
        # Floor at -16: quality gate accepts -16 to -12 LUFS. -18 would fail the gate.
        loudnorm = max(-14 - int(-net_audio / T) * 2, -16)  # quieter
    else:
        loudnorm = -14

    # Image quality
    blurry = fault_counts.get("image_blurry", 0)
    hf_steps = min(int(blurry / T) * 4, 8) if blurry >= T else 0

    # Font size
    small = fault_counts.get("font_small", 0)
    font_adjust = min(int(small / T) * 6, 18) if small >= T else 0

    # Category boost from topic requests
    boost: dict[str, int] = {}
    for fault, count in fault_counts.items():
        if fault.startswith("topic_request:") and count >= 1:
            cat = fault.split(":", 1)[1].upper()
            boost[cat] = min(count * 2, 10)

    fixes = {
        "tts_rate_adjust":      tts_rate,
        "loudnorm_target":      loudnorm,
        "hf_steps_adjust":      hf_steps,
        "subtitle_font_adjust": font_adjust,
        "category_boost":       boost,
        "last_updated":         datetime.now(timezone.utc).isoformat(),
        "fault_counts":         fault_counts,
    }

    # Log what changed
    if tts_rate != 0:
        log.info("Fix: speech speed → tts_rate_adjust=%d%%", tts_rate)
    if loudnorm != -14:
        log.info("Fix: audio level → loudnorm_target=%d dB", loudnorm)
    if hf_steps > 0:
        log.info("Fix: image quality → hf_steps_adjust=+%d", hf_steps)
    if font_adjust > 0:
        log.info("Fix: font size → subtitle_font_adjust=+%d px", font_adjust)
    if boost:
        log.info("Fix: category boost → %s", boost)

    return fixes


def run_comment_analyzer() -> None:
    """Fetch all video comments, classify faults, save auto_fixes.json."""
    token = _token()
    if not token:
        log.error("Comment analyzer: token failed")
        return

    video_ids = _get_all_video_ids()
    if not video_ids:
        log.info("Comment analyzer: no videos found")
        return

    analyze_ids = video_ids[-_MAX_VIDEOS:]  # newest 30
    log.info("Comment analyzer: scanning %d videos", len(analyze_ids))

    fault_counts: dict[str, int] = {}
    total_comments = 0

    for video_id in analyze_ids:
        comments = _get_comments(token, video_id)
        if not comments:
            continue

        classified = _classify_comments(comments)
        for item in classified:
            fault = item.get("fault", "none")
            if fault and fault not in ("none", "positive"):
                fault_counts[fault] = fault_counts.get(fault, 0) + 1

        total_comments += len(comments)
        time.sleep(0.5)

    log.info("Analyzed %d comments | faults: %s", total_comments, fault_counts)

    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    fixes = _compute_fixes(fault_counts)
    _AUTO_FIXES_PATH.write_text(json.dumps(fixes, indent=2))
    log.info("auto_fixes.json saved")

    feedback = _build_script_feedback(fault_counts)
    (_LOGS_DIR / "script_feedback.json").write_text(json.dumps(feedback, indent=2))
    if feedback["viewer_note"]:
        log.info("script_feedback.json saved: %d instruction(s)", feedback["viewer_note"].count("\n") + 1)
    else:
        log.info("script_feedback.json saved: no content issues found yet")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run_comment_analyzer()
