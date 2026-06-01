"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
When ass_path is provided, animated subtitles are burned into the video
(requires re-encode).  Without ass_path the video stream is copied (faster).

A/V sync contract:
  Step 9 guarantees exact audio duration == locked_timeline.
  We use -t locked_duration to enforce the exact output length.
  apad and -shortest are removed: apad on already-padded audio creates
  drift-on-drift, and -shortest can silently truncate the audio tail.
  Post-encode validation confirms output duration matches locked value.
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
    ass_path: Path | None = None,
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

    burn_subs = ass_path and ass_path.exists()
    # Use locked duration as hard output cap — never trust -shortest
    locked_t = ["-t", str(expected_duration_s)] if expected_duration_s > 0 else []

    if burn_subs:
        # ASS path: forward slashes, single-quoted to handle spaces and colons
        safe_ass = "'" + str(ass_path).replace("\\", "/") + "'"
        ass_filter = f"ass={safe_ass}"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map",  "0:v",
            "-map",  "1:a",
            "-vf",   ass_filter,
            "-c:v",  "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a",  "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        ] + locked_t + [
            "-movflags", "+faststart",
            str(output_path),
        ]
        timeout = max(300, 120 + int(expected_duration_s * 1.5))
        log.info("  Encoding [%s] + ASS subtitles …", profile)
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-map",  "0:v",
            "-map",  "1:a",
            "-c:v",  "copy",
            "-c:a",  "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        ] + locked_t + [
            "-movflags", "+faststart",
            str(output_path),
        ]
        timeout = max(120, 60 + int(expected_duration_s * 0.5))
        log.info("  Muxing [%s] …", profile)

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    out_dur = _probe_duration(output_path)
    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.3fs  %.1f MB → %s", out_dur, size_mb, output_path.name)

    # Post-encode validation — confirms output matches locked duration
    if expected_duration_s > 0 and out_dur > 0:
        post_drift = abs(out_dur - expected_duration_s)
        if post_drift > 0.5:
            raise RuntimeError(
                f"Post-encode duration mismatch: "
                f"got {out_dur:.3f}s, expected {expected_duration_s:.3f}s "
                f"(drift {post_drift:.3f}s > 0.5s tolerance)"
            )


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
