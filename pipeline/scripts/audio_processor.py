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
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_STD_RATE = 44100
_STD_CH   = 2


def _auto_loudnorm_target() -> int:
    try:
        p = Path(__file__).parent.parent / "logs" / "auto_fixes.json"
        if p.exists():
            return int(json.loads(p.read_text()).get("loudnorm_target", -14))
    except Exception:
        pass
    return -14

def detect_audio_gaps(path: Path, max_gap_s: float = 2.0) -> list[float]:
    r = subprocess.run([
        "ffmpeg", "-i", str(path),
        "-af", f"silencedetect=noise=-40dB:d={max_gap_s}",
        "-f", "null", "-"
    ], capture_output=True, text=True)

    gaps = []
    for line in r.stderr.splitlines():
        if "silence_end" in line:
            try:
                end_s = float(line.split("silence_end:")[1].split("|")[0].strip())
                gaps.append(round(end_s, 2))
            except (IndexError, ValueError):
                continue
    return gaps
def process_audio(
    voice_dir: Path,
    temp_dir: Path,
    duration_cap_s: float = 0.0,
    scenes: list | None = None,
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

    # ── Gap check on voice track BEFORE music mix ────────────────────────────
    # Running silencedetect on the final mix (voice + music) produces false
    # positives from quiet music passages. Check the clean voice track only.
    gaps = detect_audio_gaps(normalized)
    if gaps:
        log.warning("  Audio gaps > 2s in voice track at %s — check scene boundaries", gaps)
    else:
        log.info("  Audio gap check passed — no gaps in voice track")

    # ── Optional: SFX mix (WOW impacts, hook tension, payoff reveal) ─────────
    assets_dir = Path(__file__).parent.parent / "assets"
    sfx_dir    = assets_dir / "sfx"
    if scenes:
        # Re-derive SFX timestamps from normalized duration to prevent drift
        # after normalization shifts scene durations
        actual_norm_dur = _probe(normalized)
        sfxed = _mix_sfx(normalized, sfx_dir, scenes, actual_norm_dur)
        if sfxed:
            normalized = sfxed

    # ── Optional: background music mix ───────────────────────────────────────
    music_dir = assets_dir / "music"
    # Always probe actual duration — never trust the passed parameter at this
    # stage since normalization may have shifted it slightly
    final_voice_dur = _probe(normalized)
    mixed = _mix_background_music(normalized, music_dir, final_voice_dur)
    if mixed:
        log.info("  Background music mixed: %s", mixed.name)

    return mixed or normalized
 


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
        _ln_target = _auto_loudnorm_target()
        loudnorm_af = (
            f"loudnorm=I={_ln_target}:TP=-1.5:LRA=11"
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
        loudnorm_af = f"loudnorm=I={_auto_loudnorm_target()}:TP=-1.5:LRA=11"

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
         "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50"
         # apad removed — stage 2 already padded to exact duration
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
             "-af", f"loudnorm=I={_auto_loudnorm_target()}:TP=-1.5:LRA=11:print_format=json",
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
    """Convert any TTS MP3 to consistent AAC 44.1 kHz stereo.

    apad=whole_dur preserves the exact source duration after AAC encoding.
    Without it, AAC frame boundary rounding drops up to ~50ms per file —
    across 58 scenes that accumulates to 2-3s of missing audio which fails
    the integrity check in main.py after 50 minutes of render work.
    """
    if out.exists() and out.stat().st_size > 1_000:
        return
    src_dur = _probe(src)
    _run(
        ["ffmpeg", "-y", "-i", str(src),
         "-af", f"apad=whole_dur={src_dur:.6f}",
         "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
         "-c:a", "aac", "-b:a", "192k",
         str(out)],
        f"std {src.name}",
    )


def _merge(files: list[Path], output: Path) -> None:
    """Concatenate standardized AAC files using concat demuxer (no resampling drift).

    All input files are already normalised to the same sample rate and channel
    count by _standardize(), so -c copy is safe and introduces zero drift.
    The old filter_complex concat with aresample=async=1 accumulated
    non-deterministic micro-drift across scenes that grew with scene count.
    """
    if len(files) == 1:
        import shutil
        shutil.copy(files[0], output)
        return

    # Write concat list file next to output
    concat_list = output.with_name("concat_list.txt")
    concat_list.write_text(
        "\n".join(f"file '{str(f).replace(chr(92), '/')}'" for f in files),
        encoding="utf-8",
    )

    _run(
        ["ffmpeg", "-y",
         "-f", "concat", "-safe", "0",
         "-i", str(concat_list),
         "-c", "copy",
         str(output)],
        "merge",
    )

    try:
        concat_list.unlink()
    except Exception:
        pass


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


def _mix_sfx(voice: Path, sfx_dir: Path, scenes: list, duration_s: float) -> Path | None:
    """
    Mix subtle sound effects into the voice track for WOW moments and
    segment transitions. SFX files live in pipeline/assets/sfx/:

        wow_impact.mp3      — played at each WOW-marked scene start
        hook_tension.mp3    — played at t=0 (HOOK intro build)
        transition.mp3      — played at CORE→PAYOFF boundary
        payoff_reveal.mp3   — played at PAYOFF start

    SFX are mixed quietly (-28 dB / volume=0.04) so they're felt, not heard.
    Returns None if sfx_dir is empty or files are missing (graceful skip).
    """
    if not sfx_dir.exists():
        return None

    # Build list of (time_s, sfx_file) events
    events: list[tuple[float, Path]] = []

    for sc in scenes:
        label     = sc.get("segment_label", "")
        has_wow   = sc.get("has_wow", False)
        start_s   = sc.get("start_ms", 0) / 1000.0

        if sc.get("scene_id") == 1:
            sfx = sfx_dir / "hook_tension.mp3"
            if sfx.exists():
                events.append((0.0, sfx))

        if has_wow:
            sfx = sfx_dir / "wow_impact.mp3"
            if sfx.exists():
                events.append((start_s, sfx))

        if label == "PAYOFF":
            sfx = sfx_dir / "payoff_reveal.mp3"
            if sfx.exists() and not any(t == start_s and f == sfx for t, f in events):
                events.append((start_s, sfx))

    if not events:
        return None

    # Build filter_complex: one delayed_sfx per event, amix everything
    out = voice.parent / f"sfx_{voice.stem}.m4a"
    inputs = ["-i", str(voice)]
    filter_parts = ["[0:a]volume=1.0[voice]"]
    mix_labels   = ["[voice]"]

    for i, (t_s, sfx_f) in enumerate(events):
        inputs += ["-i", str(sfx_f)]
        idx = i + 1
        label_out = f"[s{idx}]"
        filter_parts.append(
            f"[{idx}:a]volume=0.04,adelay={int(t_s * 1000)}|{int(t_s * 1000)}{label_out}"
        )
        mix_labels.append(label_out)

    n_inputs = len(mix_labels)
    mix_filter = (
        "".join(mix_labels) +
        f"amix=inputs={n_inputs}:duration=longest:dropout_transition=0[out]"
    )
    filter_parts.append(mix_filter)

    try:
        _run([
            "ffmpeg", "-y",
        ] + inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
            str(out),
        ], "sfx-mix")
        if out.exists() and out.stat().st_size > 10_000:
            log.info("  SFX mixed: %d events", len(events))
            return out
    except Exception as exc:
        log.debug("SFX mix failed (non-critical): %s", exc)

    return None


def _mix_background_music(voice: Path, music_dir: Path, duration_s: float) -> Path | None:
    """
    Mix background music under the voice track at low volume (-20 dB).

    Music files must be placed in pipeline/assets/music/ named by emotion:
        mysterious.mp3  excited.mp3  dramatic.mp3  neutral.mp3

    Any MP3/WAV/M4A file found there is used. If none exist, returns None
    and the pipeline continues without music — fully graceful fallback.

    The music is:
      • Stream-looped to fill the full voice duration
      • Lowpass filtered (12 kHz) so it never competes with voice clarity
      • Faded in over 1.5s and faded out over 2s
      • Mixed at weight 0.10 (≈ -20 dB under voice)
    """
    # Auto-generate ambient music if the folder is missing or empty
    existing = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.wav")) + list(music_dir.glob("*.m4a"))
    if not existing:
        try:
            from music_fetcher import generate_music
            generate_music(music_dir)
        except Exception as exc:
            log.debug("Auto music generation skipped: %s", exc)

    if not music_dir.exists():
        return None

    music_file: Path | None = None
    for ext in ("*.mp3", "*.wav", "*.m4a"):
        candidates = sorted(music_dir.glob(ext))
        if candidates:
            # Pick one deterministically by rotating through files
            import time
            music_file = candidates[int(time.time() / 3600) % len(candidates)]
            break

    if not music_file:
        return None

    out = voice.parent / f"voiced_music_{voice.stem}.m4a"
    fade_out_start = max(0.0, duration_s - 2.0)

    try:
        _run([
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(music_file),
            "-i", str(voice),
            "-filter_complex", (
                f"[0:a]aresample=44100,lowpass=f=12000,"
                f"atrim=0:{duration_s:.3f},"
                + (
                    "" if os.getenv("VIDEO_FORMAT", "").lower() == "shorts"
                    else f"afade=t=in:st=0:d=1.5,"
                ) +
                f"afade=t=out:st={fade_out_start:.3f}:d=2.0,"
                f"volume=0.10[music];"
                f"[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[out]"
            ),
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            "-ar", str(_STD_RATE), "-ac", str(_STD_CH),
            str(out),
        ], "music-mix")
        if out.exists() and out.stat().st_size > 10_000:
            return out
    except Exception as exc:
        log.warning("Background music mix failed — video will have no background music: %s", exc)

    return None


def _run(cmd: list, label: str) -> None:
    log.debug("Audio [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        log.error("Audio [%s] FAILED:\n%s", label, res.stderr[-500:])
        raise RuntimeError(f"Audio processing failed: {label}")
