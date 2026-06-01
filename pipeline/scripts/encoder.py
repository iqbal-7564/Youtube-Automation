"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
When ass_path is provided, animated subtitles are burned into the video
(requires re-encode).  Without ass_path the video stream is copied (faster).

A/V sync contract:
  Audio is hard-trimmed to exactly locked_duration via atrim+asetpts
  before muxing — eliminates any normalization padding accumulated in
  audio_processor so both streams are frame-accurate at the quality gate.
  -t locked_duration caps the container as a second safety net.
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

    # Profile-aware quality settings:
    #   Shorts   → CRF 16, medium preset, 192k audio  (fast, good quality)
    #   Standard → CRF 14, slow preset,   320k audio  (cinema quality)
    #   Long     → CRF 13, slow preset,   320k audio  (maximum quality)
    is_shorts = profile == "shorts"
    if is_shorts:
        v_preset, v_crf, a_bitrate = "medium", "16", "192k"
    elif profile == "long":
        v_preset, v_crf, a_bitrate = "slow",   "13", "320k"
    else:
        v_preset, v_crf, a_bitrate = "slow",   "14", "320k"

    # Hard-trim audio to exactly locked_duration — eliminates normalization padding
    locked_t = ["-t", str(expected_duration_s)] if expected_duration_s > 0 else []
    if expected_duration_s > 0:
        audio_trim_filter = f"atrim=0:{expected_duration_s},asetpts=PTS-STARTPTS"
    else:
        audio_trim_filter = None

    if burn_subs:
        safe_ass = "'" + str(ass_path).replace("\\", "/") + "'"
        if audio_trim_filter:
            filter_complex = (
                f"[0:v]ass={safe_ass}[vout];"
                f"[1:a]{audio_trim_filter}[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "[aout]",
                "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
            ] + locked_t + [
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-map", "0:v", "-map", "1:a",
                "-vf", f"ass={safe_ass}",
                "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                str(output_path),
            ]
        # slow preset needs more time — scale timeout by profile
        t_mult = 2.0 if is_shorts else 4.0
        timeout = max(600, 180 + int(expected_duration_s * t_mult))
        log.info("  Encoding [%s] preset=%s crf=%s audio=%s …",
                 profile, v_preset, v_crf, a_bitrate)
    else:
        if audio_trim_filter:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-map", "0:v",
                "-filter_complex", f"[1:a]{audio_trim_filter}[aout]",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
            ] + locked_t + [
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                str(output_path),
            ]
        timeout = max(180, 60 + int(expected_duration_s * 0.8))
        log.info("  Muxing [%s] audio=%s …", profile, a_bitrate)

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
