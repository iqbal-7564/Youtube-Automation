"""
STEP 9 — Audio Processing

Standardize → Merge → Normalize pipeline.

Why standardize first:
  TTS engines output MP3 at mixed sample rates.  FFmpeg's filter_complex
  concat silently truncates streams on format mismatch.  Converting every
  file to identical AAC 44.1 kHz stereo before concat is the only reliable
  approach.

Normalization rule: NEVER change duration.
  atrim / -t / -shortest are all banned from the normalize step.
  Fade-out start is calculated from the actual merged duration so it
  can never exceed the file length.
  An assertion after normalization verifies duration stayed within ±0.5 s.
"""

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_STD_RATE = 44100
_STD_CH   = 2


def process_audio(
    voice_dir: Path,
    temp_dir: Path,
    duration_cap_s: float = 0.0,
) -> Path:
    raw_files = sorted(
        voice_dir.glob("voice_*.mp3"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not raw_files:
        raise RuntimeError(f"No voice_*.mp3 files in {voice_dir}")

    log.info("  Standardizing %d voice files to AAC 44.1 kHz …", len(raw_files))

    # ── Step 1: Standardize every file ───────────────────────────────────────
    std_dir = temp_dir / "voice_std"
    std_dir.mkdir(parents=True, exist_ok=True)

    std_files: list[Path] = []
    total_dur = 0.0

    for f in raw_files:
        std_f = std_dir / f.with_suffix(".m4a").name
        _standardize(f, std_f)
        dur = _probe_duration(std_f)
        log.info("    %s → %.3fs", f.name, dur)
        total_dur += dur
        std_files.append(std_f)

    log.info("  Scene audio total: %.3fs  locked=%.3fs",
             total_dur, duration_cap_s)

    if duration_cap_s > 0:
        diff = abs(total_dur - duration_cap_s)
        if diff > 1.0:
            log.warning(
                "  ⚠ Actual audio total %.3fs vs locked %.3fs (diff %.3fs). "
                "Timeline may have been locked from inaccurate VBR durations.",
                total_dur, duration_cap_s, diff,
            )

    # ── Step 2: Merge ─────────────────────────────────────────────────────────
    merged = voice_dir / "merged_voice.m4a"
    _merge(std_files, merged)
    merged_dur = _probe_duration(merged)
    log.info("  Merged audio: %.3fs", merged_dur)

    # ── Step 3: Normalize (duration MUST NOT change) ──────────────────────────
    normalized = voice_dir / "normalized_voice.aac"
    _normalize(merged, normalized, merged_dur)

    norm_dur = _probe_duration(normalized)
    log.info("  Normalized audio: %.3fs", norm_dur)

    if abs(norm_dur - merged_dur) > 0.5:
        raise RuntimeError(
            f"Normalization changed duration: merged={merged_dur:.3f}s "
            f"normalized={norm_dur:.3f}s — check filter chain"
        )

    return normalized


# ── Helpers ───────────────────────────────────────────────────────────────────

def _standardize(src: Path, out: Path) -> None:
    if out.exists() and out.stat().st_size > 1_000:
        return
    _run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "aac", "-b:a", "192k",
         str(out)],
        f"std {src.name}",
    )


def _merge(files: list[Path], output: Path) -> None:
    if len(files) == 1:
        import shutil
        shutil.copy(files[0], output)
        return

    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]

    n             = len(files)
    concat_inputs = "".join(f"[{i}:a]" for i in range(n))
    concat_filter = f"{concat_inputs}concat=n={n}:v=0:a=1[outa]"

    _run(
        ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", concat_filter,
            "-map", "[outa]",
            "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ],
        "merge",
    )


def _normalize(src: Path, out: Path, src_dur: float) -> None:
    """Apply loudness / EQ / fade processing.  Must NOT change duration."""
    # Fade-out start: 1 s before end, but never negative
    fade_out_start = max(0.5, src_dur - 1.0)

    af_parts = [
        "loudnorm=I=-14:TP=-1.5:LRA=11",
        "afftdn=nf=-40",
        "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50",
        "afade=t=in:st=0:d=0.5",
        f"afade=t=out:st={fade_out_start:.3f}:d=1.0",
    ]
    # NO atrim, NO -t, NO -shortest — duration must be preserved
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-af", ",".join(af_parts),
        "-c:a", "aac", "-b:a", "192k",
        "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
        str(out),
    ]
    log.info("  Normalize cmd: %s", " ".join(cmd))
    _run(cmd, "normalize")


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


def _run(cmd: list, label: str) -> None:
    log.debug("Audio [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        log.error("Audio [%s] FAILED:\n%s", label, res.stderr[-500:])
        raise RuntimeError(f"Audio processing failed: {label}")
