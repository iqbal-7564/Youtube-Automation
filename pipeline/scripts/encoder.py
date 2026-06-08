"""
STEP 10 — Encoding

Muxes assembled video-only track + normalised audio into final MP4.
Always re-encodes with libx264 to guarantee 2-second keyframe intervals
required for YouTube HLS segmentation. When ass_path is provided, subtitles
are burned in via the ass filter.

A/V sync contract:
  Audio is hard-trimmed to min(video_actual_duration, locked_duration) via
  atrim+asetpts before muxing.  xfade transitions shorten the assembled
  video below locked_duration (each overlap eats transition_dur seconds);
  trimming audio to match the actual video length keeps both streams
  frame-accurate at the quality gate.
  Post-encode validation confirms output duration matches the trim target.
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
    #   Shorts   → CRF 18, fast preset,   192k audio
    #   Standard → CRF 16, medium preset, 320k audio
    #   Long     → CRF 15, medium preset, 320k audio
    is_shorts = profile == "shorts"
    if is_shorts:
        v_preset, v_crf, a_bitrate = "fast",   "18", "192k"
    elif profile == "long":
        v_preset, v_crf, a_bitrate = "medium", "15", "320k"
    else:
        v_preset, v_crf, a_bitrate = "medium", "16", "320k"

    # YouTube HLS streaming requires a keyframe at least every 2 seconds so its
    # CDN can segment the video correctly. Without this, playback fails mid-video
    # ("An error occurred") at the first segment boundary with no keyframe.
    # -g 60        = keyframe every 60 frames (2s at 30fps)
    # -keyint_min 30 = never skip more than 1s between forced keyframes
    # -sc_threshold 0 = disable scene-change extra keyframes (we control this)
    h264_keyframe_args = [
        "-g", "60", "-keyint_min", "30", "-sc_threshold", "0",
    ]

    # Trim audio to actual video duration so both streams are frame-accurate.
    # xfade transitions shorten the assembled video below locked_duration;
    # using the video's real length as the ceiling eliminates the resulting drift.
    trim_to = min(vdur, expected_duration_s) if expected_duration_s > 0 and vdur > 0 \
              else (expected_duration_s or vdur)
    locked_t = ["-t", str(trim_to)] if trim_to > 0 else []
    if trim_to > 0:
        audio_trim_filter = f"atrim=0:{trim_to},asetpts=PTS-STARTPTS"
    else:
        audio_trim_filter = None

    v264_args = [
        "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
        "-pix_fmt", "yuv420p",
    ] + h264_keyframe_args

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
            ] + v264_args + [
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
            ] + v264_args + [
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                str(output_path),
            ]
        t_mult = 2.0 if is_shorts else 4.0
        timeout = max(600, 180 + int(expected_duration_s * t_mult))
        log.info("  Encoding [%s] preset=%s crf=%s audio=%s …",
                 profile, v_preset, v_crf, a_bitrate)
    else:
        # No subtitle burn — still re-encode (never stream copy) so that
        # keyframe spacing is guaranteed every 2s for YouTube HLS segmentation.
        # Stream copy preserves the assembler's irregular keyframes which causes
        # "An error occurred" mid-video when YouTube's CDN finds no keyframe
        # at a segment boundary.
        if audio_trim_filter:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-map", "0:v",
                "-filter_complex", f"[1:a]{audio_trim_filter}[aout]",
                "-map", "[aout]",
            ] + v264_args + [
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
            ] + v264_args + [
                "-c:a", "aac", "-b:a", a_bitrate, "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                str(output_path),
            ]
        timeout = max(600, 180 + int(expected_duration_s * 2.0))
        log.info("  Encoding [%s] preset=%s crf=%s audio=%s (no subs) …",
                 profile, v_preset, v_crf, a_bitrate)

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if res.returncode != 0:
        log.error("Encoder FAILED:\n%s", res.stderr[-800:])
        raise RuntimeError("FFmpeg encoder failed")

    out_dur = _probe_duration(output_path)
    size_mb = output_path.stat().st_size / 1_048_576
    log.info("  Encoded: %.3fs  %.1f MB → %s", out_dur, size_mb, output_path.name)

    # Post-encode validation — confirms output matches the actual trim target
    if trim_to > 0 and out_dur > 0:
        post_drift = abs(out_dur - trim_to)
        if post_drift > 0.5:
            raise RuntimeError(
                f"Post-encode duration mismatch: "
                f"got {out_dur:.3f}s, expected {trim_to:.3f}s "
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
