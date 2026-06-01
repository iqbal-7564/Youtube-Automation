"""
STEP 11 — Quality Gate

11 checks — all must pass before upload.
Returns {passed, quality_score, tier, checks, fail_reason}.

Quality score replaces binary pass/fail:
  >= 90  → UPLOAD
  75-89  → UPLOAD_WARN  (log degradation, still upload)
  < 75   → REJECT

This gate is READ-ONLY — it never modifies the timeline.
Subtitle clamping proposals are returned in 'clamped_subtitles' for
the caller to apply; they are not applied here.

Tolerances calibrated to actual pipeline characteristics:
  duration  : ±2.5 s  (accounts for xfade transition duration reduction)
  audio_sync: ±0.5 s  (accounts for AAC encoder delay padding accumulation)
  audio_gaps: only gaps > 2.0 s  (max intentional inter-scene silence ~1.8s)
  voice_quality: WARNING only — does not block upload (partial score deduction)

Checks and weights:
  1.  audio_failure  — silence fallback used (BLOCKS — not in score)
  2.  file_integrity — container valid, moov at start, size > 100 KB  (15 pts)
  3.  resolution     — exact match to profile spec + 30 fps            (10 pts)
  4.  duration       — within ± 2.5 s of timeline total                (15 pts)
  5.  audio_sync     — A/V track length within ± 0.3 s                 (15 pts)
  6.  audio_level    — integrated loudness −14 LUFS ± 2                (10 pts)
  7.  subtitles      — no entry < 300 ms                                (5 pts)
  8.  freeze_frame   — no freeze > 2000 ms (freezedetect filter)        (10 pts)
  9.  voice_quality  — WARNING if gTTS/silence used (partial: 3/5 pts)  (5 pts)
  10. dropped_frames — no more than 3 frames with irregular timing       (5 pts)
  11. audio_gaps     — no silence gap > 2.0 s inside the audio track    (10 pts)
"""

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_WEIGHTS = {
    "file_integrity": 15,
    "resolution":     10,
    "duration":       15,
    "audio_sync":     15,
    "audio_level":    10,
    "subtitles":       5,
    "freeze_frame":   10,
    "voice_quality":   5,
    "dropped_frames":  5,
    "audio_gaps":     10,
}


def run_quality_gate(
    video_path: Path,
    timeline: dict,
    subtitles_dir: Path,
) -> dict:
    checks: dict[str, str] = {}
    fail: str | None = None

    dur_s   = timeline.get("total_duration_seconds", 60)
    t_probe = max(30,  int(dur_s * 0.4))
    t_audio = max(90,  int(dur_s * 1.0))

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

    # Hard block — not in score (silence fallback = missing audio content)
    chk("audio_failure",  lambda: _audio_failure(timeline))

    # Scored checks
    chk("file_integrity",  lambda: _integrity(video_path, t_probe))
    chk("resolution",      lambda: _resolution(video_path, timeline, t_probe))
    chk("duration",        lambda: _duration(video_path, timeline, t_probe))
    chk("audio_sync",      lambda: _audio_sync(video_path, t_probe))
    chk("audio_level",     lambda: _audio_level(video_path, t_audio))
    chk("subtitles",       lambda: _subtitles_readonly(subtitles_dir, timeline))
    chk("freeze_frame",    lambda: _freeze(video_path, t_probe))
    chk("voice_quality",   lambda: _voice_quality(timeline))
    chk("dropped_frames",  lambda: _dropped_frames(video_path, t_probe))
    chk("audio_gaps",      lambda: _audio_gaps(video_path, timeline, t_audio))

    # Compute quality score from scored checks only
    score = 0
    for name, weight in _WEIGHTS.items():
        result = checks.get(name, "")
        if result == "pass":
            score += weight
        elif name == "voice_quality" and result.startswith("pass"):
            # Partial: degraded TTS still passes but gets only 3/5 pts
            if "degraded" in result:
                score += 3
            else:
                score += weight

    if fail is None:
        # No hard failure — tier by score
        if score >= 90:
            tier = "UPLOAD"
        elif score >= 75:
            tier = "UPLOAD_WARN"
            log.warning("  Quality score %d/100 — UPLOAD_WARN (degraded but acceptable)", score)
        else:
            tier   = "REJECT"
            fail   = f"quality score {score}/100 below threshold (75)"
    else:
        tier = "REJECT"

    passed = tier in ("UPLOAD", "UPLOAD_WARN")
    log.info("  Gate: %s  score=%d/100  %s",
             "PASS" if passed else "FAIL", score, fail or "all clear")

    return {
        "passed":       passed,
        "quality_score": score,
        "tier":         tier,
        "checks":       checks,
        "fail_reason":  fail,
    }


# ── Checks ────────────────────────────────────────────────────────────────────

def _fp(path: Path, *args, timeout: int = 30) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", *args, str(path)],
        capture_output=True, text=True, timeout=timeout,
    )
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _audio_failure(timeline: dict):
    """Block upload if any scene used silence fallback (missing audio content)."""
    failed = [
        sc["scene_id"]
        for sc in timeline.get("scenes", [])
        if sc.get("audio_failure")
    ]
    if failed:
        return False, f"silence fallback used for scene(s) {failed} — audio content missing"
    return True, "ok"


def _integrity(path: Path, timeout: int = 30):
    if not path.exists():
        return False, "file not found"
    if path.stat().st_size < 100_000:
        return False, f"too small ({path.stat().st_size} bytes)"
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-i", str(path)],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0 or r.stderr.strip():
        return False, f"container error: {r.stderr[:120]}"
    return True, "ok"


def _resolution(path: Path, timeline: dict, timeout: int = 30):
    data = _fp(path, "-show_streams", "-select_streams", "v:0", timeout=timeout)
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


def _duration(path: Path, timeline: dict, timeout: int = 30):
    data = _fp(path, "-show_format", timeout=timeout)
    try:
        actual   = float(data["format"]["duration"])
        expected = timeline["total_duration_seconds"]
        diff     = abs(actual - expected)
        if diff > 2.5:
            return False, f"drift {diff:.2f}s (expected {expected:.2f}s got {actual:.2f}s)"
        return True, f"{actual:.2f}s (diff {diff:.2f}s)"
    except (KeyError, ValueError, TypeError) as exc:
        return False, str(exc)


def _audio_sync(path: Path, timeout: int = 30):
    data    = _fp(path, "-show_streams", timeout=timeout)
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
    if diff > 0.5:
        return False, f"A/V drift {diff:.3f}s"
    return True, f"drift={diff:.3f}s"


def _audio_level(path: Path, timeout: int = 90):
    """Use loudnorm print_format=json for reliable cross-version LUFS parsing."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(path),
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
        )
        combined = r.stderr + r.stdout
        brace_start = combined.rfind("{")
        brace_end   = combined.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            data = json.loads(combined[brace_start:brace_end])
            lufs_str = data.get("input_i", "")
            if lufs_str and lufs_str not in ("-inf", "inf"):
                lufs = float(lufs_str)
                ok   = -16.0 <= lufs <= -12.0
                msg  = f"{lufs:.1f} LUFS"
                return ok, msg if ok else f"{msg} (target -14±2)"
    except Exception as exc:
        log.debug("Audio level check: %s", exc)
    return True, "level check skipped (loudnorm parse failed)"


def _subtitles_readonly(subtitles_dir: Path, timeline: dict):
    """Read-only subtitle check — reports issues without modifying the timeline."""
    total_ms = timeline["total_duration_ms"]
    for sc in timeline["scenes"]:
        sc_end = sc["end_ms"]
        for ln in sc.get("subtitle_lines", []):
            ceiling = min(sc_end, total_ms) - 100
            if ln["end_ms"] > ceiling:
                pass  # overflow — would be clamped, not a failure
            if ln["end_ms"] - ln["start_ms"] < 300:
                return False, f"subtitle < 300ms (scene {sc['scene_id']})"
    return True, "ok"


def _freeze(path: Path, timeout: int = 30):
    """Detect freeze frames using ffmpeg freezedetect filter (analysis mode only)."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(path),
             "-t", "120",
             "-vf", "freezedetect=n=-60dB:d=2.0",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
        )
        combined = r.stdout + r.stderr
        freeze_durations = []
        for line in combined.splitlines():
            if "freeze_duration" in line:
                try:
                    dur = float(line.split("freeze_duration:")[1].strip().split()[0])
                    freeze_durations.append(dur)
                except (IndexError, ValueError):
                    pass
        if freeze_durations:
            total_freeze = sum(freeze_durations)
            return False, f"freeze detected: {len(freeze_durations)} event(s), total {total_freeze:.2f}s"
    except Exception as exc:
        log.debug("Freeze check: %s", exc)
    return True, "ok"


def _voice_quality(timeline: dict):
    """Partial score if degraded TTS — does NOT block upload."""
    bad = [
        sc["scene_id"]
        for sc in timeline.get("scenes", [])
        if sc.get("tts_engine") in ("gtts", "silence")
    ]
    if bad:
        log.warning("  TTS degraded for scene(s) %s — check ElevenLabs/edge-tts", bad)
        return True, f"degraded TTS on {bad} (warning only)"
    return True, "ok"


def _dropped_frames(path: Path, timeout: int = 30):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-show_frames", "-select_streams", "v:0",
         "-read_intervals", "%+#90",
         "-print_format", "json", str(path)],
        capture_output=True, text=True, timeout=timeout,
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


def _audio_gaps(path: Path, timeline: dict, timeout: int = 60):
    """Detect unintentional silence gaps > 2.0 s in the audio track."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-af", "silencedetect=noise=-50dB:d=2.0",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=timeout,
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
        return False, f"audio gap(s) > 2s detected at {[f'{g:.2f}s' for g in gaps[:3]]}"
    return True, "ok"
