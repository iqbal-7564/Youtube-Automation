"""
STEP 4 — Voice Generation

Generates one audio file per scene (voice_{scene_id}.mp3).
Measures ACTUAL duration with ffprobe, then updates the master timeline.
If actual duration drifts > 500ms from estimate, scene visual duration adjusts
(audio is never stretched — visual window expands/contracts instead).

Engine priority: edge-tts → ElevenLabs → gTTS → silence fallback
Voice settings:  speed -5% (0.95x), stability 0.75, similarity_boost 0.85
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_EL_VOICE_ID = "pNInz6obpgDQGcFmaJgB"   # Adam — authoritative news style
_EDGE_VOICE  = "en-US-GuyNeural"


def generate_voices(timeline: dict, voice_dir: Path) -> dict:
    voice_dir.mkdir(parents=True, exist_ok=True)
    scenes = timeline["scenes"]

    for sc in scenes:
        path = voice_dir / f"voice_{sc['scene_id']}.mp3"
        if not (path.exists() and path.stat().st_size > 500):
            _generate(sc["script_text"], path)

        actual_ms = _duration_ms(path)
        if actual_ms > 0:
            drift = abs(actual_ms - sc["duration_ms"])
            if drift > 500:
                log.info("  Scene %d: drift %dms — adjusting scene to %dms",
                         sc["scene_id"], drift, actual_ms)
                sc["duration_ms"] = actual_ms
                sc["end_ms"]      = sc["start_ms"] + actual_ms

    # Re-anchor all scene timestamps sequentially after any adjustments
    t = 0
    for sc in scenes:
        sc["start_ms"]       = t
        sc["end_ms"]         = t + sc["duration_ms"]
        sc["voice_start_ms"] = t
        sc["voice_end_ms"]   = t + sc["duration_ms"]
        t += sc["duration_ms"]

    timeline["total_duration_ms"]      = t
    timeline["total_duration_seconds"] = round(t / 1000, 2)

    # Recalculate profile based on actual duration
    if timeline["total_duration_seconds"] <= 60:
        timeline["profile"], timeline["width"], timeline["height"] = "shorts",   1080, 1920
    else:
        timeline["profile"], timeline["width"], timeline["height"] = "standard", 1920, 1080

    # Rescale subtitle timestamps to match new scene windows
    for sc in scenes:
        sc["subtitle_lines"] = _rescale_subs(
            sc["subtitle_lines"], sc["start_ms"], sc["end_ms"]
        )

    return timeline


# ── TTS engines ───────────────────────────────────────────────────────────────

def _generate(text: str, out: Path) -> None:
    if _edge_tts(text, out):
        return
    if _elevenlabs(text, out):
        return
    if _gtts(text, out):
        return
    _silence(out, max(1.0, len(text.split()) / 2.8))
    log.error("All TTS engines failed — silence for: %s", text[:50])


def _edge_tts(text: str, out: Path) -> bool:
    try:
        async def _run():
            import edge_tts
            comm = edge_tts.Communicate(text, voice=_EDGE_VOICE, rate="-5%")
            await comm.save(str(out))

        asyncio.run(_run())
        return out.exists() and out.stat().st_size > 500
    except Exception as exc:
        log.debug("edge-tts: %s", exc)
        return False


def _elevenlabs(text: str, out: Path) -> bool:
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        return False
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{_EL_VOICE_ID}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text":     text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability":         0.75,
                    "similarity_boost":  0.85,
                    "style":             0.0,
                    "use_speaker_boost": True,
                },
            },
            timeout=30,
        )
        if r.ok:
            out.write_bytes(r.content)
            return True
        log.debug("ElevenLabs HTTP %d", r.status_code)
    except Exception as exc:
        log.debug("ElevenLabs: %s", exc)
    return False


def _gtts(text: str, out: Path) -> bool:
    try:
        from gtts import gTTS
        gTTS(text=text, lang="en", slow=False).save(str(out))
        return out.exists()
    except Exception as exc:
        log.debug("gTTS: %s", exc)
    return False


def _silence(out: Path, duration_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"anullsrc=r=44100:cl=stereo",
         "-t", str(duration_s), str(out)],
        capture_output=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _duration_ms(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        for stream in json.loads(r.stdout).get("streams", []):
            dur = stream.get("duration")
            if dur:
                return int(float(dur) * 1000)
    except Exception:
        pass
    return 0


def _rescale_subs(lines: list, new_start: int, new_end: int) -> list:
    if not lines:
        return lines
    orig_start = lines[0]["start_ms"]
    orig_dur   = max(lines[-1]["end_ms"] - orig_start, 1)
    new_dur    = new_end - new_start
    scale      = new_dur / orig_dur
    result     = []
    for ln in lines:
        ns = new_start + int((ln["start_ms"] - orig_start) * scale)
        ne = new_start + int((ln["end_ms"]   - orig_start) * scale)
        result.append({"text": ln["text"], "start_ms": ns, "end_ms": max(ne, ns + 500)})
    return result
