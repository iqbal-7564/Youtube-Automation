"""
STEP 9 — Audio Processing

Standardize → Merge → 3-Stage Normalize pipeline.

Stage 2 uses TWO-PASS loudnorm to prevent the single-pass streaming mode
from truncating the final seconds of long audio files.

  Pass 1 (analysis): ffmpeg reads the entire file and prints loudnorm
                     stats as JSON to stderr.  No output file.
  Pass 2 (apply):    ffmpeg applies loudnorm with linear=true and the
                     measured values.  Linear mode is a single-sample
                     gain operation with zero buffering — always
                     duration-preserving regardless of ffmpeg version.

  After loudnorm, afftdn may drop a few samples at the FFT boundary.
  apad=whole_dur=<clean_dur> pads any missing tail back to the exact
  source length so Stage 3 always receives the full waveform.

Stage 3 appends apad=whole_dur=<real_dur> after alimiter to flush
alimiter's lookahead buffer before EOF (some ffmpeg versions drop the
buffered tail silently).  Output is M4A so ffprobe reads duration from
the container header rather than estimating from bitrate.

Rules:
  • loudnorm and afade must NEVER share a filter chain.
  • afade start time must always be read from the ACTUAL Stage 2 output.
  • No -t, no -shortest, no atrim in any normalization pass.
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
        log.warning(
            "  ⚠ Audio total %.3fs differs from locked %.3fs by %.3fs",
            total_dur, duration_cap_s, abs(total_dur - duration_cap_s),
        )

    # ── Merge ─────────────────────────────────────────────────────────────────
    merged = voice_dir / "merged_voice.m4a"
    _merge(std_files, merged)
    merged_dur = _probe(merged)
    log.info("  Merged audio: %.3fs", merged_dur)

    # ── 3-Stage Normalization ─────────────────────────────────────────────────
    tmp_dir = temp_dir / "audio_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    normalized = voice_dir / "normalized_voice.m4a"
    _normalize_3stage(merged, normalized, tmp_dir)

    norm_dur = _probe(normalized)
    log.info("  Normalized audio: %.3fs", norm_dur)

    # Duration must not shrink by more than 0.5 s (codec frame rounding is fine)
    if merged_dur - norm_dur > 0.5:
        raise RuntimeError(
            f"Normalization changed duration: "
            f"merged={merged_dur:.3f}s → normalized={norm_dur:.3f}s"
        )

    return normalized


# ── 3-stage normalization ─────────────────────────────────────────────────────

def _normalize_3stage(src: Path, out: Path, tmp_dir: Path) -> None:
    clean_wav = tmp_dir / "clean.wav"
    norm_wav  = tmp_dir / "normalized.wav"

    # ── Stage 1: decode to clean PCM WAV ─────────────────────────────────────
    log.info("  Normalize stage 1: decode to PCM WAV …")
    _run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "pcm_s16le",
         str(clean_wav)],
        "s1-decode",
    )
    clean_dur = _probe(clean_wav)
    log.info("  Stage 1 output: %.3fs", clean_dur)

    # ── Stage 2: two-pass loudnorm + afftdn + apad ────────────────────────────
    # Pass 1: measure integrated loudness stats (no output file)
    log.info("  Normalize stage 2a: loudnorm pass-1 (measure) …")
    stats = _loudnorm_measure(clean_wav)

    # Pass 2: apply loudnorm as linear gain (duration-preserving by definition)
    #         + afftdn noise reduction
    #         + apad to restore any samples dropped by afftdn's FFT latency
    log.info("  Normalize stage 2b: loudnorm pass-2 (apply linear) + afftdn + apad …")

    if stats:
        loudnorm_af = (
            f"loudnorm=I=-14:TP=-1.5:LRA=11"
            f":measured_I={stats.get('input_i', '-70.0')}"
            f":measured_TP={stats.get('input_tp', '-70.0')}"
            f":measured_LRA={stats.get('input_lra', '0.0')}"
            f":measured_thresh={stats.get('input_thresh', '-80.0')}"
            f":offset={stats.get('target_offset', '0.0')}"
            f":linear=true"
        )
        log.info("  Two-pass loudnorm: I=%s TP=%s LRA=%s",
                 stats.get('input_i'), stats.get('input_tp'), stats.get('input_lra'))
    else:
        # Fallback: single-pass loudnorm (may still truncate, but apad repairs it)
        log.warning("  loudnorm stats parse failed — using single-pass fallback")
        loudnorm_af = "loudnorm=I=-14:TP=-1.5:LRA=11"

    _run(
        ["ffmpeg", "-y", "-i", str(clean_wav),
         "-af", f"{loudnorm_af},afftdn=nf=-40,apad=whole_dur={clean_dur:.6f}",
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "pcm_s16le",
         str(norm_wav)],
        "s2-apply",
    )

    # Read REAL duration from Stage 2 output — this is the authoritative value
    real_dur = _probe(norm_wav)
    log.info("  Stage 2 output: %.3fs (clean_dur was %.3fs)", real_dur, clean_dur)

    if clean_dur > 0 and abs(real_dur - clean_dur) > 0.5:
        log.warning(
            "  Stage 2 duration mismatch: clean=%.3fs norm_wav=%.3fs — "
            "apad may not have compensated fully",
            clean_dur, real_dur,
        )

    # ── Stage 3: fades + limiter → final AAC ─────────────────────────────────
    # fade_out_start is computed from norm_wav's ACTUAL duration.
    # It is never assumed or carried over from an earlier variable.
    fade_out_start = max(0.5, real_dur - 1.0)
    log.info(
        "  Normalize stage 3: fades (in@0s, out@%.3fs) + limiter → AAC …",
        fade_out_start,
    )

    _run(
        ["ffmpeg", "-y", "-i", str(norm_wav),
         "-af", (
             f"afade=t=in:st=0.000:d=0.500,"
             f"afade=t=out:st={fade_out_start:.3f}:d=1.000,"
             "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50,"
             f"apad=whole_dur={real_dur:.6f}"
         ),
         "-c:a", "aac", "-b:a", "192k",
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         str(out)],
        "s3-fades",
    )


def _loudnorm_measure(path: Path) -> dict | None:
    """
    Pass 1 of two-pass loudnorm: run ffmpeg with print_format=json and
    parse the loudnorm stats from stderr.

    Returns a dict with keys: input_i, input_tp, input_lra, input_thresh,
    target_offset.  Returns None if parsing fails (caller falls back to
    single-pass mode).
    """
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostats", "-i", str(path),
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        combined = r.stderr + r.stdout
        # The JSON block is the last { ... } in the output
        brace_start = combined.rfind("{")
        brace_end   = combined.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            data = json.loads(combined[brace_start:brace_end])
            # Verify it has the keys we need
            if "input_i" in data:
                return data
    except Exception as exc:
        log.debug("loudnorm measure error: %s", exc)
    return None


# ── Shared helpers ────────────────────────────────────────────────────────────

def _standardize(src: Path, out: Path) -> None:
    """Convert any TTS MP3 to consistent AAC 44.1 kHz stereo."""
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
    """Concatenate standardized AAC files using filter_complex concat."""
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
    """Return file duration in seconds via ffprobe (format-level read)."""
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
