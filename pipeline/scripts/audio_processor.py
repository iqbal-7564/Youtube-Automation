"""
STEP 9 — Audio Processing

Standardize → Merge → 3-Stage Normalize pipeline.

Normalization is split into 3 separate FFmpeg passes to prevent filter
chains from collapsing duration:

  Stage 1: merged AAC  → clean PCM WAV
           (forces stable waveform, removes AAC timestamp drift)

  Stage 2: clean WAV   → normalized WAV
           loudnorm + afftdn ONLY — no fades, no limiter, no -t

  Stage 3: probe REAL duration from normalized WAV
           → apply afade_in + afade_out + alimiter
           → encode to final AAC

Rule: loudnorm and afade must NEVER be in the same filter chain.
      loudnorm rebuilds timestamps; applying afade afterward uses the
      wrong reference and silently truncates 8-10 s of content.
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

    # ── Standardize ──────────────────────────────────────────────────────────
    std_dir = temp_dir / "voice_std"
    std_dir.mkdir(parents=True, exist_ok=True)

    std_files: list[Path] = []
    total_dur = 0.0
    for f in raw_files:
        std_f = std_dir / f.with_suffix(".m4a").name
        _standardize(f, std_f)
        dur = _probe(std_f)
        log.info("    %s → %.3fs", f.name, dur)
        total_dur += dur
        std_files.append(std_f)

    log.info("  Scene audio total: %.3fs  locked=%.3fs", total_dur, duration_cap_s)
    if duration_cap_s > 0 and abs(total_dur - duration_cap_s) > 1.0:
        log.warning("  ⚠ Audio total %.3fs differs from locked %.3fs by %.3fs",
                    total_dur, duration_cap_s, abs(total_dur - duration_cap_s))

    # ── Merge ─────────────────────────────────────────────────────────────────
    merged = voice_dir / "merged_voice.m4a"
    _merge(std_files, merged)
    merged_dur = _probe(merged)
    log.info("  Merged audio: %.3fs", merged_dur)

    # ── 3-Stage Normalization ─────────────────────────────────────────────────
    tmp_dir = temp_dir / "audio_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    normalized = voice_dir / "normalized_voice.aac"
    _normalize_3stage(merged, normalized, tmp_dir)

    norm_dur = _probe(normalized)
    log.info("  Normalized audio: %.3fs", norm_dur)

    if abs(norm_dur - merged_dur) > 0.5:
        raise RuntimeError(
            f"Normalization changed duration: "
            f"merged={merged_dur:.3f}s → normalized={norm_dur:.3f}s"
        )

    return normalized


def _normalize_3stage(src: Path, out: Path, tmp_dir: Path) -> None:
    """
    Stage 1: AAC → clean PCM WAV  (stable waveform, no filters)
    Stage 2: WAV → loudnorm + afftdn only  (no fades, no limiter)
    Stage 3: probe real duration → apply fades + limiter → final AAC
    """
    clean_wav = tmp_dir / "clean.wav"
    norm_wav  = tmp_dir / "normalized.wav"

    # ── Stage 1: decode to PCM ────────────────────────────────────────────────
    log.info("  Normalize stage 1: decode to PCM WAV …")
    _run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "pcm_s16le",
         str(clean_wav)],
        "s1-decode",
    )

    # ── Stage 2: loudnorm + noise gate ONLY (no fades, no limiter) ───────────
    log.info("  Normalize stage 2: loudnorm + afftdn …")
    _run(
        ["ffmpeg", "-y", "-i", str(clean_wav),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,afftdn=nf=-40",
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "pcm_s16le",
         str(norm_wav)],
        "s2-loudnorm",
    )

    # ── Stage 3: probe REAL duration → fades → limiter → final AAC ───────────
    real_dur = _probe(norm_wav)
    log.info("  Normalize stage 3: duration=%.3fs → fades + limiter → AAC …",
             real_dur)

    fade_in_start  = 0.0
    fade_out_start = max(0.5, real_dur - 1.0)

    _run(
        ["ffmpeg", "-y", "-i", str(norm_wav),
         "-af", (
             f"afade=t=in:st={fade_in_start:.3f}:d=0.5,"
             f"afade=t=out:st={fade_out_start:.3f}:d=1.0,"
             "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50"
         ),
         "-c:a", "aac", "-b:a", "192k",
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         str(out)],
        "s3-fade-limiter",
    )

    log.info("  Stage 3 cmd: fade_out_start=%.3fs", fade_out_start)


# ── Shared helpers ────────────────────────────────────────────────────────────

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


def _probe(path: Path) -> float:
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
