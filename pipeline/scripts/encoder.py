"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
Video stream is COPIED (no re-encode) — assembler already outputs H.264
at the correct resolution and fps. Only audio is encoded (AAC 192k).

Duration contract:
  -t is set to the EXACT assembled video duration (probed via ffprobe).
  apad then pads silence to precisely that length — no more, no less.
  This prevents the audio track from inflating the container beyond the
  video end, which was causing a persistent +3.0s drift in the quality gate.
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

    # Probe the assembled video's actual duration — this is the authoritative
    # length. Using expected_duration_s alone is wrong because the assembler
    # adds pre-roll / hook card / end card that the timeline doesn't count.
    actual_video_dur = _probe_duration(video_path)
    vmb = video_path.stat().st_size / 1_048_576
    log.info("  Assembled video: %.3fs  %.1f MB", actual_video_dur, vmb)

    # Decide the hard cap for -t:
    # 1. Use probed duration if available — apad will pad audio to exactly this.
    # 2. Fall back to expected + 3s safety margin only if probe failed.
    if actual_video_dur > 0:
        t_cap = actual_video_dur
    elif expected_duration_s > 0:
        t_cap = expected_duration_s + 3.0
        log.warning("  ffprobe failed — using expected+3s cap (%.1fs)", t_cap)
    else:
        t_cap = 0.0

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        # apad extends audio to t_cap; -t ensures it stops exactly there.
        "-af",  "apad",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar",  "44100",
        "-ac",  "2",
        "-movflags", "+faststart",
    ]

    if t_cap > 0:
        cmd += ["-t", str(t_cap)]

    cmd.append(str(output_path))

    log.info("  Muxing [%s] cap=%.3fs …", profile, t_cap)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    out_dur = _probe_duration(output_path)
    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.3fs  %.1f MB → %s", out_dur, size_mb, output_path.name)

    # Sanity-check our own output so surprises surface here, not at the gate.
    if t_cap > 0 and abs(out_dur - t_cap) > 0.5:
        log.warning("  Output duration %.3fs differs from cap %.3fs by %.3fs",
                    out_dur, t_cap, abs(out_dur - t_cap))


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
