"""
STEP 4 — Voice Generation

Generates one audio file per scene (voice_{scene_id}.mp3).
Measures ACTUAL duration with ffprobe, then updates the master timeline.
If actual duration drifts > 500ms from estimate, scene visual duration adjusts
(audio is never stretched — visual window expands/contracts instead).

Engine priority: edge-tts → ElevenLabs → gTTS → silence fallback
ElevenLabs voice settings are tuned per emotion tag:
  excited    → low stability, higher style (dynamic delivery)
  mysterious → high stability, slow rate (eerie, deliberate)
  dramatic   → medium stability, high similarity (powerful)
  neutral    → default settings

300 ms of silence is appended to each voice file to give viewers a
breathing moment between scenes. CORE→PAYOFF boundary gets 600 ms.
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

# ElevenLabs voice settings per emotion
_EL_SETTINGS: dict[str, dict] = {
    "excited":    {"stability": 0.35, "similarity_boost": 0.90, "style": 0.70, "use_speaker_boost": True},
    "mysterious": {"stability": 0.85, "similarity_boost": 0.80, "style": 0.10, "use_speaker_boost": False},
    "dramatic":   {"stability": 0.55, "similarity_boost": 0.90, "style": 0.45, "use_speaker_boost": True},
    "neutral":    {"stability": 0.75, "similarity_boost": 0.85, "style": 0.00, "use_speaker_boost": True},
}

# edge-tts rate per emotion
_EDGE_RATE: dict[str, str] = {
    "excited":    "+5%",
    "mysterious": "-10%",
    "dramatic":   "-5%",
    "neutral":    "-5%",
}

# Silence padding between scenes (ms)
_SCENE_PAD_MS           = 300
_SECTION_BOUNDARY_PAD_MS = 600   # CORE → PAYOFF transition


def generate_voices(timeline: dict, voice_dir: Path) -> dict:
    voice_dir.mkdir(parents=True, exist_ok=True)
    scenes = timeline["scenes"]

    for i, sc in enumerate(scenes):
        path    = voice_dir / f"voice_{sc['scene_id']}.mp3"
        emotion = sc.get("emotion", "neutral")

        if not (path.exists() and path.stat().st_size > 500):
            engine = _generate(sc["script_text"], path, emotion)
            sc["tts_engine"] = engine
        else:
            sc.setdefault("tts_engine", "cached")

        # Append inter-scene silence
        is_core_payoff_boundary = (
            sc["segment_label"] == "CORE" and
            i + 1 < len(scenes) and
            scenes[i + 1]["segment_label"] == "PAYOFF"
        )
        pad_ms = _SECTION_BOUNDARY_PAD_MS if is_core_payoff_boundary else _SCENE_PAD_MS
        _append_silence(path, pad_ms / 1000)

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

    # Log TTS engine usage so quality gate can check
    engines_used = [sc.get("tts_engine", "") for sc in scenes]
    degraded = [e for e in engines_used if e in ("gtts", "silence")]
    if degraded:
        log.warning("  TTS quality degraded for %d scene(s) — engines: %s",
                    len(degraded), set(degraded))

    return timeline


# ── TTS engines ───────────────────────────────────────────────────────────────

def _generate(text: str, out: Path, emotion: str) -> str:
    if _edge_tts(text, out, emotion):
        return "edge-tts"
    if _elevenlabs(text, out, emotion):
        return "elevenlabs"
    if _gtts(text, out):
        return "gtts"
    _silence(out, max(1.0, len(text.split()) / 2.8))
    log.error("All TTS engines failed — silence for: %s", text[:50])
    return "silence"


def _edge_tts(text: str, out: Path, emotion: str) -> bool:
    rate = _EDGE_RATE.get(emotion, "-5%")
    try:
        async def _run():
            import edge_tts
            comm = edge_tts.Communicate(text, voice=_EDGE_VOICE, rate=rate)
            await comm.save(str(out))

        asyncio.run(_run())
        return out.exists() and out.stat().st_size > 500
    except Exception as exc:
        log.debug("edge-tts: %s", exc)
        return False


def _elevenlabs(text: str, out: Path, emotion: str) -> bool:
    key = os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        return False
    settings = _EL_SETTINGS.get(emotion, _EL_SETTINGS["neutral"])
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{_EL_VOICE_ID}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text":     text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": settings,
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
         "-i", "anullsrc=r=44100:cl=stereo",
         "-t", str(duration_s), str(out)],
        capture_output=True,
    )


def _append_silence(path: Path, duration_s: float) -> None:
    """Append silence to an existing audio file in-place."""
    if not path.exists():
        return
    tmp = path.with_suffix(".tmp.mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-i", str(path),
             "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration_s}",
             "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[outa]",
             "-map", "[outa]",
             "-c:a", "libmp3lame", "-q:a", "2",
             str(tmp)],
            capture_output=True, timeout=30,
        )
        if tmp.exists() and tmp.stat().st_size > 500:
            tmp.replace(path)
    except Exception as exc:
        log.debug("append_silence: %s", exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _duration_ms(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(r.stdout)
        for stream in data.get("streams", []):
            dur = stream.get("duration")
            if dur:
                return int(float(dur) * 1000)
        fmt_dur = data.get("format", {}).get("duration")
        if fmt_dur:
            return int(float(fmt_dur) * 1000)
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
