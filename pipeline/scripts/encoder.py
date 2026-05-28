"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
Video stream is COPIED (no re-encode). Only audio is encoded (AAC 192k).

A/V sync contract:
  audio is already trimmed to locked_timeline by audio_processor (step 9).
  apad pads silence if audio < video.
  -shortest stops encoding when the shorter stream (typically video, after
  xfade transitions reduce it slightly) ends.
  This yields drift = 0 regardless of transition-induced video shortening.
"""

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def encode_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    profile: str,
    expected_duration_s: float = 0.0,
) -> None:
    if not video_path.exists():
        raise FileNotFoundError(f"Assembled video not found: {video_path}")
    if not audio_path.exists():
        raise FileNotFoundError(f"Processed audio not found: {audio_path}")

    vdur = _probe_duration(video_path)
    adur = _probe_duration(audio_path)
    drift = abs(vdur - adur)
    log.info("  Video=%.3fs  Audio=%.3fs  PreMuxDrift=%.3fs  "
             "locked=%.3fs", vdur, adur, drift, expected_duration_s)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map",  "0:v",
        "-map",  "1:a",
        "-c:v",  "copy",
        # apad fills any silence gap; -shortest stops at video end
        "-af",   "apad",
        "-c:a",  "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    log.info("  Muxing [%s] …", profile)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    out_dur = _probe_duration(output_path)
    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.3fs  %.1f MB → %s", out_dur, size_mb, output_path.name)


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0
