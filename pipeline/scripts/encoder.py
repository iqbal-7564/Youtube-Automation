"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
Video stream is COPIED (no re-encode) — assembler already outputs H.264
at the correct resolution and fps. Only audio is encoded (AAC 192k).

This keeps encoding time under 10 seconds on any runner.

Both outputs:
  -movflags +faststart  (moov atom at start)
  apad                  (pad audio to video length — prevents A/V drift)
  -shortest             (stop at video end)
  -t cap                (hard ceiling at expected_duration_s + 3s)
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

    # Diagnostic — log what we're actually encoding
    vdur = _probe_duration(video_path)
    vmb  = video_path.stat().st_size / 1_048_576
    log.info("  Assembled video: %.1fs  %.1f MB", vdur, vmb)
    if expected_duration_s and vdur > expected_duration_s * 3:
        log.warning("  Assembled video is %.1fx longer than expected — will be capped",
                    vdur / max(expected_duration_s, 1))

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        # Copy video bitstream unchanged — no re-encode needed
        "-map",  "0:v",
        "-map",  "1:a",
        "-c:v",  "copy",
        # Pad audio with silence so it's never shorter than the video
        "-af",   "apad",
        "-c:a",  "aac",
        "-b:a",  "192k",
        "-ar",   "44100",
        "-ac",   "2",
        "-shortest",
        "-movflags", "+faststart",
    ]

    # Hard cap: never produce a video longer than expected + 3s buffer
    if expected_duration_s > 0:
        cmd += ["-t", str(expected_duration_s + 3.0)]

    cmd.append(str(output_path))

    log.info("  Muxing [%s] (copy video + encode audio) …", profile)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.1f MB → %s", size_mb, output_path.name)


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
