"""
STEP 9 — Audio Processing

Merges all per-scene voice files (with 150 ms silence between them),
then applies:
  1. Loudness normalisation  → -14 LUFS  (YouTube standard)
  2. Noise gate              → afftdn
  3. Peak limiter            → -1.0 dBFS ceiling

Output: temp/voice/normalized_voice.aac
This file is merged with the assembled video in Step 10 (encoder).
"""

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_SILENCE_MS = 150   # padding between segments


def process_audio(voice_dir: Path, temp_dir: Path) -> Path:
    files = sorted(
        voice_dir.glob("voice_*.mp3"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not files:
        raise RuntimeError(f"No voice_*.mp3 files in {voice_dir}")

    log.info("  Merging %d voice segments (+%dms padding each)", len(files), _SILENCE_MS)

    merged     = voice_dir / "merged_voice.mp3"
    normalized = voice_dir / "normalized_voice.aac"

    _merge(files, merged)
    _normalize(merged, normalized)

    return normalized


# ── Merge with silence padding ────────────────────────────────────────────────

def _merge(files: list[Path], output: Path) -> None:
    if len(files) == 1:
        shutil.copy(files[0], output)
        return

    # Build filter_complex: interleave 150ms silence between each segment
    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]

    filter_parts: list[str] = []
    all_labels:   list[str] = []

    for i in range(len(files)):
        all_labels.append(f"[{i}:a]")
        if i < len(files) - 1:
            lbl = f"[sil{i}]"
            filter_parts.append(
                f"aevalsrc=0:channel_layout=mono:sample_rate=44100"
                f":duration={_SILENCE_MS / 1000}{lbl}"
            )
            all_labels.append(lbl)

    n = len(all_labels)
    filter_parts.append(f"{''.join(all_labels)}concat=n={n}:v=0:a=1[outa]")

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", ";".join(filter_parts),
           "-map", "[outa]",
           "-c:a", "libmp3lame", "-q:a", "2",
           str(output)]
    )
    _run(cmd, "merge+pad")


# ── Normalise → gate → limit ──────────────────────────────────────────────────

def _normalize(src: Path, out: Path) -> None:
    af = (
        "loudnorm=I=-14:TP=-1.5:LRA=11,"
        "afftdn=nf=-40,"
        "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50"
    )
    _run(
        ["ffmpeg", "-y",
         "-i", str(src),
         "-af", af,
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
         str(out)],
        "normalize+limit",
    )


def _run(cmd: list, label: str) -> None:
    log.debug("Audio [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        log.error("Audio [%s] FAILED:\n%s", label, res.stderr[-500:])
        raise RuntimeError(f"Audio processing failed: {label}")
