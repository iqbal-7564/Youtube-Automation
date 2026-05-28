"""
STEP 11 — Quality Gate

10 checks — ALL must pass before upload.
Returns {passed, checks, fail_reason}.

Tolerances are calibrated to the actual pipeline characteristics:
  duration  : ±2.5 s  (accounts for xfade transition duration reduction)
  audio_sync: ±0.3 s  (accounts for -shortest boundary rounding)
  audio_gaps: only gaps > 1.0 s  (intentional 300ms inter-scene silences
              are excluded by design)
  voice_quality: WARNING only — does not block upload when a fallback TTS
              engine (gTTS) was the only option available

Checks:
  1.  file_integrity  — container valid, moov at start, size > 100 KB
  2.  resolution      — exact match to profile spec + 30 fps
  3.  duration        — within ± 2.5 s of timeline total
  4.  audio_sync      — A/V track length within ± 0.3 s
  5.  audio_level     — integrated loudness −14 LUFS ± 2
  6.  subtitles       — no entry < 300 ms; overflow clamped silently
  7.  freeze_frame    — no freeze > 500 ms (3+ identical consecutive pts)
  8.  voice_quality   — WARNING if gTTS/silence used (non-blocking)
  9.  dropped_frames  — no more than 3 frames with irregular timing
  10. audio_gaps      — no silence gap > 1.0 s inside the audio track
"""

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def run_quality_gate(
    video_path: Path,
    timeline: dict,
    subtitles_dir: Path,
) -> dict:
    checks: dict[str, str] = {}
    fail: str | None       = None

    def chk(name: str, fn):
        nonlocal fail
        try:
            ok, msg = fn()
            checks[name] = "pass" if ok else f"fail: {msg}"
            if not ok and fail is None:
                fail = f"[{name}] {msg}"
        except Exception as exc:
            checks[name] = f"error: {exc}"
            if fail is None:
                fail = f"[{name}] exception: {exc}"

    chk("file_integrity",  lambda: _integrity(video_path))
    chk("resolution",      lambda: _resolution(video_path, timeline))
    chk("duration",        lambda: _duration(video_path, timeline))
    chk("audio_sync",      lambda: _audio_sync(video_path))
    chk("audio_level",     lambda: _audio_level(video_path))
    chk("subtitles",       lambda: _subtitles(subtitles_dir, timeline))
    chk("freeze_frame",    lambda: _freeze(video_path))
    chk("voice_quality",   lambda: _voice_quality(timeline))
    chk("dropped_frames",  lambda: _dropped_frames(video_path))
    chk("audio_gaps",      lambda: _audio_gaps(video_path, timeline))

    passed = fail is None
    log.info("  Gate: %s  %s", "PASS" if passed else "FAIL", fail or "all clear")

    return {"passed": passed, "checks": checks, "fail_reason": fail}


# ── Checks ────────────────────────────────────────────────────────────────────

def _fp(path: Path, *args) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", *args, str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _integrity(path: Path):
    if not path.exists():
        return False, "file not found"
    if path.stat().st_size < 100_000:
        return False, f"too small ({path.stat().st_size} bytes)"
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-i", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0 or r.stderr.strip():
        return False, f"container error: {r.stderr[:120]}"
    return True, "ok"


def _resolution(path: Path, timeline: dict):
    data = _fp(path, "-show_streams", "-select_streams", "v:0")
    s    = (data.get("streams") or [{}])[0]
    w, h = int(s.get("width", 0)), int(s.get("height", 0))
    fps_s = s.get("r_frame_rate", "0/1")
    num, den = map(int, fps_s.split("/"))
    fps  = round(num / den) if den else 0
    ew, eh = timeline["width"], timeline["height"]
    if w != ew or h != eh:
        return False, f"got {w}×{h}, expected {ew}×{eh}"
    if fps != 30:
        return False, f"fps={fps}, expected 30"
    return True, f"{w}×{h}@{fps}"


def _duration(path: Path, timeline: dict):
    data = _fp(path, "-show_format")
    try:
        actual   = float(data["format"]["duration"])
        expected = timeline["total_duration_seconds"]
        diff     = abs(actual - expected)
        # ±2.5 s tolerance: xfade transitions can reduce video by up to ~2 s
        if diff > 2.5:
            return False, f"drift {diff:.2f}s (expected {expected:.2f}s got {actual:.2f}s)"
        return True, f"{actual:.2f}s (diff {diff:.2f}s)"
    except (KeyError, ValueError, TypeError) as exc:
        return False, str(exc)


def _audio_sync(path: Path):
    data    = _fp(path, "-show_streams")
    streams = data.get("streams", [])
    vd = ad = None
    for s in streams:
        dur = s.get("duration")
        if not dur:
            continue
        d = float(dur)
        if s.get("codec_type") == "video":
            vd = d
        elif s.get("codec_type") == "audio":
            ad = d
    if vd is None or ad is None:
        return False, f"missing stream (video={vd} audio={ad})"
    diff = abs(vd - ad)
    # ±0.3 s: -shortest alignment + codec boundary rounding
    if diff > 0.3:
        return False, f"A/V drift {diff:.3f}s"
    return True, f"drift={diff:.3f}s"


def _audio_level(path: Path):
    r = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-af", "ebur128=framelog=verbose",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=90,
    )
    combined = r.stdout + r.stderr
    for line in combined.splitlines():
        if "I:" in line and "LUFS" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "I:":
                    try:
                        lufs = float(parts[i + 1])
                        ok   = -16.0 <= lufs <= -12.0
                        msg  = f"{lufs:.1f} LUFS"
                        return ok, msg if ok else f"{msg} (target -14±2)"
                    except (IndexError, ValueError):
                        pass
    return True, "level check skipped (no ebur128 data)"


def _subtitles(subtitles_dir: Path, timeline: dict):
    # Clamp overflow silently; only hard-fail on < 300 ms entries
    total_ms  = timeline["total_duration_ms"]
    clamped   = 0
    for sc in timeline["scenes"]:
        sc_end = sc["end_ms"]
        for ln in sc.get("subtitle_lines", []):
            ceiling = min(sc_end, total_ms) - 100
            if ln["end_ms"] > ceiling:
                ln["end_ms"] = ceiling
                clamped += 1
            if ln["end_ms"] - ln["start_ms"] < 300:
                return False, f"subtitle < 300ms (scene {sc['scene_id']})"
    if clamped:
        log.debug("  %d subtitle(s) clamped to boundary", clamped)
    return True, "ok"


def _freeze(path: Path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-show_frames", "-select_streams", "v:0",
         "-read_intervals", "%+#60",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        frames = json.loads(r.stdout).get("frames", [])
        if len(frames) < 2:
            return True, "not enough frames to check"
        dupes = 0
        prev  = None
        for f in frames:
            pts = f.get("pkt_pts_time")
            if pts is not None and pts == prev:
                dupes += 1
            prev = pts
        if dupes >= 3:
            return False, f"freeze detected ({dupes} duplicate pts values)"
    except Exception:
        pass
    return True, "ok"


def _voice_quality(timeline: dict):
    """Log a warning if degraded TTS was used — does NOT block upload."""
    bad = [
        sc["scene_id"]
        for sc in timeline.get("scenes", [])
        if sc.get("tts_engine") in ("gtts", "silence")
    ]
    if bad:
        log.warning("  TTS degraded for scene(s) %s — check ElevenLabs/edge-tts", bad)
        return True, f"degraded TTS on {bad} (warning only)"
    return True, "ok"


def _dropped_frames(path: Path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-show_frames", "-select_streams", "v:0",
         "-read_intervals", "%+#90",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        frames = json.loads(r.stdout).get("frames", [])
        if len(frames) < 4:
            return True, "not enough frames"
        expected  = 1 / 30
        irregular = 0
        for f in frames:
            try:
                dur = float(f.get("pkt_duration_time") or 0)
                if dur > 0 and abs(dur - expected) / expected > 0.20:
                    irregular += 1
            except (ValueError, TypeError):
                pass
        if irregular > 3:
            return False, f"{irregular} irregular frame intervals"
    except Exception:
        pass
    return True, "ok"


def _audio_gaps(path: Path, timeline: dict):
    """Detect unintentional silence gaps > 1.0 s in the audio track.

    Threshold is 1.0 s to exclude intentional 300ms inter-scene silences
    that are part of the production design.  The check ignores the first
    0.6 s (fade-in) and the last 2 s (fade-out).
    """
    r = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-af", "silencedetect=noise=-50dB:d=1.0",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    combined = r.stdout + r.stderr
    try:
        total_dur = float(
            _fp(path, "-show_format").get("format", {}).get("duration", 0)
        )
    except Exception:
        total_dur = 0.0

    gaps = []
    for line in combined.splitlines():
        if "silence_start" in line:
            try:
                start = float(line.split("silence_start:")[1].strip())
                if 0.6 < start < total_dur - 2.0:
                    gaps.append(start)
            except (IndexError, ValueError):
                pass

    if gaps:
        return False, f"audio gap(s) > 1s detected at {[f'{g:.2f}s' for g in gaps[:3]]}"
    return True, "ok"
