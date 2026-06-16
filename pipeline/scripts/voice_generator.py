"""
STEP 4 — Voice Generation

Generates one audio file per scene (voice_{scene_id}.mp3).
Measures ACTUAL duration with ffprobe, then updates the master timeline.
If actual duration drifts > 500ms from estimate, scene visual duration adjusts.

Engine priority: ElevenLabs → edge-tts → gTTS → silence fallback
ElevenLabs voice settings are tuned per emotion tag.

300 ms of silence is appended ONCE (only when the file is freshly generated).
Cached voice files are reused as-is so silence does not accumulate on reruns.
"""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_EL_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
_EDGE_VOICE  = "en-US-ChristopherNeural"

_EL_SETTINGS: dict[str, dict] = {
    "excited":    {"stability": 0.35, "similarity_boost": 0.90, "style": 0.70, "use_speaker_boost": True},
    "mysterious": {"stability": 0.85, "similarity_boost": 0.80, "style": 0.10, "use_speaker_boost": False},
    "dramatic":   {"stability": 0.55, "similarity_boost": 0.90, "style": 0.45, "use_speaker_boost": True},
    "neutral":    {"stability": 0.75, "similarity_boost": 0.85, "style": 0.00, "use_speaker_boost": True},
}

_EDGE_RATE: dict[str, str] = {
    "excited":    "+24%",
    "mysterious": "+14%",
    "dramatic":   "+20%",
    "neutral":    "+22%",
}

_EDGE_PITCH: dict[str, str] = {
    "excited":    "+3Hz",
    "mysterious": "+0Hz",
    "dramatic":   "+2Hz",
    "neutral":    "+2Hz",
}

def _auto_tts_rate_adjust() -> int:
    try:
        p = Path(__file__).parent.parent / "logs" / "auto_fixes.json"
        if p.exists():
            return int(json.loads(p.read_text()).get("tts_rate_adjust", 0))
    except Exception:
        pass
    return 0


_SCENE_PAD_MS            = 300
_SECTION_BOUNDARY_PAD_MS = 600   # CORE → PAYOFF transition


def generate_voices(timeline: dict, voice_dir: Path) -> dict:
    voice_dir.mkdir(parents=True, exist_ok=True)
    scenes = timeline["scenes"]

    for i, sc in enumerate(scenes):
        path    = voice_dir / f"voice_{sc['scene_id']}.mp3"
        emotion = sc.get("emotion", "neutral")

        is_core_payoff = (
            sc["segment_label"] == "CORE" and
            i + 1 < len(scenes) and
            scenes[i + 1]["segment_label"] == "PAYOFF"
        )
        is_last_scene = (i == len(scenes) - 1)
        if is_last_scene:
            # Stage 3 applies a 1s fade-out. 1050ms > 1000ms fade so the fade lands
            # entirely in silence. Kept under 2000ms so silencedetect(d=2) never fires
            # on the trailing gap (TTS natural end ≈300-500ms + 1050ms = ≤1550ms).
            pad_s = 1.05
        elif is_core_payoff:
            pad_s = _SECTION_BOUNDARY_PAD_MS / 1000
        else:
            pad_s = _SCENE_PAD_MS / 1000

        sc["_voice_pad_ms"] = int(pad_s * 1000)   # stored for subtitle sync

        is_fresh = not (path.exists() and path.stat().st_size > 500)
        if is_fresh:
            engine = _generate(sc["script_text"], path, emotion,
                               fallback_duration_s=sc["duration_ms"] / 1000)
            sc["tts_engine"] = engine
            # Mark silence fallback scenes so Quality Gate can block upload
            if engine == "silence":
                sc["audio_failure"] = True
            # Silence padding appended ONLY to freshly generated files.
            # Cached files already have silence from their original generation.
            _append_silence(path, pad_s)
        else:
            sc.setdefault("tts_engine", "cached")

        actual_ms = _duration_ms(path)
        if actual_ms > 0:
            drift = abs(actual_ms - sc["duration_ms"])
            if drift > 500:
                log.info("  Scene %d: drift %dms — adjusting scene to %dms",
                         sc["scene_id"], drift, actual_ms)
                sc["duration_ms"] = actual_ms
                sc["end_ms"]      = sc["start_ms"] + actual_ms

    # Re-anchor all scene timestamps sequentially
    t = 0
    for sc in scenes:
        sc["start_ms"]       = t
        sc["end_ms"]         = t + sc["duration_ms"]
        sc["voice_start_ms"] = t
        sc["voice_end_ms"]   = t + sc["duration_ms"]
        t += sc["duration_ms"]

    timeline["total_duration_ms"]      = t
    timeline["total_duration_seconds"] = round(t / 1000, 2)

    # Respect explicit VIDEO_FORMAT; fall back to duration-based detection.
    # Without this, TTS padding (300-600ms per scene) can push a ~60s shorts
    # script over 60s and incorrectly flip the profile to standard (1920×1080),
    # causing shorts to upload as landscape videos instead of vertical Shorts.
    _vf = os.getenv("VIDEO_FORMAT", "").lower()
    if _vf == "shorts":
        timeline["profile"], timeline["width"], timeline["height"] = "shorts",   1080, 1920
    elif _vf in ("standard", "long"):
        timeline["profile"], timeline["width"], timeline["height"] = "standard", 1920, 1080
    elif timeline["total_duration_seconds"] <= 70:
        timeline["profile"], timeline["width"], timeline["height"] = "shorts",   1080, 1920
    else:
        timeline["profile"], timeline["width"], timeline["height"] = "standard", 1920, 1080

    for sc in scenes:
        # Exclude silence padding from subtitle window so subtitles never
        # run into the gap between scenes (the main cause of voice/sub mismatch).
        pad_ms = sc.get("_voice_pad_ms", _SCENE_PAD_MS)
        voice_end_ms = max(sc["start_ms"] + 500, sc["end_ms"] - pad_ms)
        sc["subtitle_lines"] = _rescale_subs(
            sc["subtitle_lines"], sc["start_ms"], voice_end_ms
        )

    engines_used = [sc.get("tts_engine", "") for sc in scenes]
    degraded = [e for e in engines_used if e in ("gtts", "silence")]
    if degraded:
        log.warning("  TTS quality degraded for %d scene(s) — engines: %s",
                    len(degraded), set(degraded))

    return timeline


# ── TTS engines ───────────────────────────────────────────────────────────────

def _generate(text: str, out: Path, emotion: str, fallback_duration_s: float = 3.0) -> str:
    # ElevenLabs first — it sounds closest to a real human voice.
    # edge-tts is free but recognisably robotic; viewers can tell immediately
    # and it reduces watch time and trust. ElevenLabs is used FIRST because
    # voice quality is the single biggest differentiator vs other channels.
    if _elevenlabs(text, out, emotion):
        return "elevenlabs"
    if _edge_tts(text, out, emotion):
        return "edge-tts"
    if _gtts(text, out):
        return "gtts"
    _silence_file(out, max(1.0, fallback_duration_s))
    log.error("All TTS engines failed — silence for: %s", text[:50])
    return "silence"


def _edge_tts(text: str, out: Path, emotion: str) -> bool:
    base = int(_EDGE_RATE.get(emotion, "+0%").replace("%", ""))
    adjusted = max(-30, min(30, base + _auto_tts_rate_adjust()))
    rate  = f"{adjusted:+d}%"
    pitch = _EDGE_PITCH.get(emotion, "+0Hz")
    for attempt in range(2):
        try:
            async def _run():
                import edge_tts
                comm = edge_tts.Communicate(text, voice=_EDGE_VOICE, rate=rate, pitch=pitch)
                await comm.save(str(out))
            # Use get_event_loop instead of asyncio.run() to avoid nested loop crash
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        ex.submit(asyncio.run, _run()).result(timeout=30)
                else:
                    loop.run_until_complete(_run())
            except RuntimeError:
                asyncio.run(_run())
            if out.exists() and out.stat().st_size > 500:
                return True
        except Exception as exc:
            log.debug("edge-tts attempt %d: %s", attempt + 1, exc)
            if attempt == 0:
                import time as _t; _t.sleep(1)
    return False


def _elevenlabs(text: str, out: Path, emotion: str) -> bool:
    # Try all available keys in order — when one hits quota (429/401) move to next.
    # Add ELEVENLABS_API_KEY_3 / _4 in GitHub secrets to extend monthly quota.
    keys = [
        os.getenv("ELEVENLABS_API_KEY",   "").strip(),
        os.getenv("ELEVENLABS_API_KEY_2", "").strip(),
        os.getenv("ELEVENLABS_API_KEY_3", "").strip(),
        os.getenv("ELEVENLABS_API_KEY_4", "").strip(),
    ]
    settings = _EL_SETTINGS.get(emotion, _EL_SETTINGS["neutral"])

    for key in keys:
        if not key:
            continue
        for attempt in range(2):
            try:
                r = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{_EL_VOICE_ID}",
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    json={"text": text, "model_id": "eleven_monolingual_v1",
                          "voice_settings": settings},
                    timeout=30,
                )
                if r.ok:
                    out.write_bytes(r.content)
                    return True
                if r.status_code in (401, 429):
                    # Quota exhausted or rate limited — switch to next key
                    log.warning("ElevenLabs key …%s HTTP %d — trying next key",
                                key[-4:], r.status_code)
                    break
                log.debug("ElevenLabs HTTP %d (attempt %d)", r.status_code, attempt + 1)
            except Exception as exc:
                log.debug("ElevenLabs attempt %d: %s", attempt + 1, exc)
            if attempt == 0:
                import time as _t; _t.sleep(1)

    return False


def _gtts(text: str, out: Path) -> bool:
    try:
        from gtts import gTTS
        gTTS(text=text, lang="en", slow=False).save(str(out))
        return out.exists()
    except Exception as exc:
        log.debug("gTTS: %s", exc)
    return False


def _silence_file(out: Path, duration_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=stereo",
         "-t", str(duration_s), str(out)],
        capture_output=True,
    )


def _append_silence(path: Path, duration_s: float) -> None:
    """Append exactly duration_s seconds of silence to the voice file.

    Uses anullsrc with the :d= duration option so the silence source
    is finite without relying on -t or a VBR-inaccurate probe.
    """
    if not path.exists():
        return
    tmp = path.with_suffix(".tmp.mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-i", str(path),
             "-f", "lavfi",
             "-i", f"anullsrc=r=44100:cl=stereo:d={duration_s:.3f}",
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
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _duration_ms(path: Path) -> int:
    ms = int(_duration_s(path) * 1000)
    return ms


def _duration_s(path: Path) -> float:
    """Return accurate duration for any audio file including VBR MP3.

    -count_packets forces ffprobe to scan the entire file and count
    packets rather than trusting potentially-wrong VBR headers.
    Without this, VBR MP3 durations are commonly underreported by 10-20%.

    Falls back to ffmpeg -af astats sample counting if ffprobe returns 0.
    A 0.0 return here causes silent timeline corruption, so we try hard.
    """
    if not path.exists():
        return 0.0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format",
             "-count_packets",
             str(path)],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        for stream in data.get("streams", []):
            dur = stream.get("duration")
            if dur and float(dur) > 0:
                return float(dur)
        fmt_dur = data.get("format", {}).get("duration")
        if fmt_dur and float(fmt_dur) > 0:
            return float(fmt_dur)
    except Exception:
        pass

    # Third fallback: derive duration from sample count via ffmpeg astats
    try:
        r2 = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        streams = json.loads(r2.stdout).get("streams", [])
        for s in streams:
            nb = s.get("nb_frames") or s.get("nb_read_frames")
            sr = s.get("sample_rate")
            if nb and sr:
                estimated = int(nb) / int(sr)
                if estimated > 0:
                    log.debug("Duration fallback via nb_frames: %.3fs", estimated)
                    return estimated
    except Exception:
        pass

    log.warning("Could not determine duration for %s — returning 0.0 (timing will be corrupt)",
                path.name)
    return 0.0


def _rescale_subs(lines: list, new_start: int, new_end: int) -> list:
    if not lines:
        return lines
    orig_start = lines[0]["start_ms"]
    orig_dur   = max(lines[-1]["end_ms"] - orig_start, 1)
    new_dur    = new_end - new_start
    scale      = new_dur / orig_dur
    result     = []
    for ln in lines:
        # Round to nearest 50ms grid — prevents drift accumulation in long videos
        ns = new_start + round((ln["start_ms"] - orig_start) * scale / 50) * 50
        ne = new_start + round((ln["end_ms"]   - orig_start) * scale / 50) * 50
        result.append({"text": ln["text"], "start_ms": ns, "end_ms": max(ne, ns + 500)})
    return result
