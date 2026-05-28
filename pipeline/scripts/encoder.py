"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
Video stream is COPIED (no re-encode). Only audio is encoded (AAC 192k).

Duration contract:
  -t is set to timeline["total_duration_seconds"] (locked after voice
  generation — nothing downstream may change it).
  apad pads audio silence exactly to that length.
  A +1 s buffer is added to absorb H.264 GOP rounding without inflating
  the output past the gate's ±1 s tolerance.
"""

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

    vmb = video_path.stat().st_size / 1_048_576
    log.info("  Assembler input: %.1f MB  locked_duration=%.3fs",
             vmb, expected_duration_s)

    # Cap = locked timeline total + 1 s buffer for codec rounding.
    # Using expected_duration_s (from locked timeline) — NOT a probed file
    # duration — so downstream nothing can shrink this value.
    t_cap = expected_duration_s + 1.0 if expected_duration_s > 0 else 0.0

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-af",  "apad",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
    ]

    if t_cap > 0:
        cmd += ["-t", str(t_cap)]

    cmd.append(str(output_path))

    log.info("  Muxing [%s] t_cap=%.3fs …", profile, t_cap)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.1f MB → %s", size_mb, output_path.name)
