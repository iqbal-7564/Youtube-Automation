"""
STEP 9 — Audio Processing

Standardize → Merge → Normalize pipeline.

Why standardize first:
  TTS engines output MP3 at mixed sample rates (edge-tts: 24 kHz,
  gTTS: 22 kHz, ElevenLabs: 44.1 kHz).  FFmpeg's filter_complex concat
  silently truncates or drops streams when inputs have mismatched rates,
  which is the exact cause of the "8.6s missing audio" issue.
  Converting every file to identical AAC 44100 Hz stereo before concat
  eliminates all format-mismatch losses.

Steps:
  1. Standardize each voice_*.mp3 → AAC 44.1 kHz stereo (temp/voice_std/)
  2. Log and sum per-scene durations; assert total ≈ locked timeline
  3. Merge with filter_complex concat (reliable on identical formats)
  4. Normalize: atrim(cap) → loudnorm → noise gate → limiter → fade in/out
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

    diff = abs(total_dur - duration_cap_s) if duration_cap_s > 0 else 0.0
    log.info("  Scene audio total: %.3fs  locked=%.3fs  diff=%.3fs",
             total_dur, duration_cap_s, diff)

    if duration_cap_s > 0 and diff > 1.0:
        log.error(
            "  ⚠ Audio total %.3fs differs from locked timeline %.3fs by %.3fs — "
            "check for missing/silent voice files",
            total_dur, duration_cap_s, diff,
        )

    # ── Step 2: Merge ─────────────────────────────────────────────────────────
    merged     = voice_dir / "merged_voice.m4a"
    normalized = voice_dir / "normalized_voice.aac"

    _merge(std_files, merged)

    merged_dur = _probe_duration(merged)
    log.info("  Merged audio: %.3fs", merged_dur)

    # ── Step 3: Normalize ─────────────────────────────────────────────────────
    _normalize(merged, normalized, duration_cap_s)

    final_dur = _probe_duration(normalized)
    log.info("  Normalized audio: %.3fs  (cap=%.3fs)", final_dur, duration_cap_s)
    return normalized


# ── Helpers ───────────────────────────────────────────────────────────────────

def _standardize(src: Path, out: Path) -> None:
    """Convert any TTS output to AAC 44.1 kHz stereo — no format surprises."""
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


def _normalize(src: Path, out: Path, duration_cap_s: float) -> None:
    dur = _probe_duration(src)
    fade_out_start = max(0.0, min(dur, duration_cap_s if duration_cap_s > 0 else dur) - 1.0)

    af_parts: list[str] = []

    if duration_cap_s > 0:
        af_parts.append(f"atrim=duration={duration_cap_s:.3f}")

    af_parts += [
        "loudnorm=I=-14:TP=-1.5:LRA=11",
        "afftdn=nf=-40",
        "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50",
        "afade=t=in:st=0:d=0.5",
    ]
    if fade_out_start > 0.5:
        af_parts.append(f"afade=t=out:st={fade_out_start:.3f}:d=1.0")

    _run(
        ["ffmpeg", "-y",
         "-i", str(src),
         "-af", ",".join(af_parts),
         "-c:a", "aac", "-b:a", "192k", "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         str(out)],
        "normalize",
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


def _run(cmd: list, label: str) -> None:
    log.debug("Audio [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        log.error("Audio [%s] FAILED:\n%s", label, res.stderr[-500:])
        raise RuntimeError(f"Audio processing failed: {label}")
