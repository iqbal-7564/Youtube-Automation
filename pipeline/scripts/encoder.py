"""
STEP 10 — Encoding

Merges assembled video-only track + normalised audio into final MP4.

SHORTS  profile : 1080×1920  9:16  H.264 CRF18 preset=slow  AAC 192k
STANDARD profile: 1920×1080 16:9  same codec settings

Both outputs:
  -movflags +faststart  (moov atom at start)
  -pix_fmt yuv420p      (max compatibility)
  -profile:v high -level 4.1
  -g 60                 (keyframe every 2s at 30fps)
  -r 30 (fixed fps)
"""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_PROFILES: dict[str, dict] = {
    "shorts":   {"W": 1080, "H": 1920, "crf": "18", "preset": "slow"},
    "standard": {"W": 1920, "H": 1080, "crf": "18", "preset": "slow"},
}


def encode_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    profile: str,
) -> None:
    if not video_path.exists():
        raise FileNotFoundError(f"Assembled video not found: {video_path}")
    if not audio_path.exists():
        raise FileNotFoundError(f"Processed audio not found: {audio_path}")

    spec = _PROFILES.get(profile, _PROFILES["standard"])
    W, H = spec["W"], spec["H"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        # Ensure correct dimensions (pad with black bars if needed)
        "-vf", (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        ),
        "-c:v",      "libx264",
        "-preset",   spec["preset"],
        "-crf",      spec["crf"],
        "-profile:v", "high",
        "-level",    "4.1",
        "-r",        "30",
        "-g",        "60",
        "-pix_fmt",  "yuv420p",
        "-c:a",      "aac",
        "-b:a",      "192k",
        "-ar",       "44100",
        "-ac",       "2",
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    log.info("  Encoding [%s] %dx%d crf=%s preset=%s …",
             profile, W, H, spec["crf"], spec["preset"])
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.1f MB → %s", size_mb, output_path.name)
