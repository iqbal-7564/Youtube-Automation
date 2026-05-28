"""
STEP 9 — Audio Processing

Merges all per-scene voice files, then applies:
  1. Loudness normalisation  → -14 LUFS  (YouTube standard)
  2. Noise gate              → afftdn
  3. Peak limiter            → -1.0 dBFS ceiling
  4. Fade in  0.5 s at start (eliminates hard audio cut on buffering)
  5. Fade out 1.0 s at end   (clean finish before end card)

Output: temp/voice/normalized_voice.aac
"""

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def process_audio(voice_dir: Path, temp_dir: Path) -> Path:
    files = sorted(
        voice_dir.glob("voice_*.mp3"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not files:
        raise RuntimeError(f"No voice_*.mp3 files in {voice_dir}")

    log.info("  Merging %d voice segments", len(files))

    merged     = voice_dir / "merged_voice.mp3"
    normalized = voice_dir / "normalized_voice.aac"

    _merge(files, merged)
    _normalize(merged, normalized)

    return normalized


def _merge(files: list[Path], output: Path) -> None:
    if len(files) == 1:
        shutil.copy(files[0], output)
        return

    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]

    n             = len(files)
    concat_inputs = "".join(f"[{i}:a]" for i in range(n))
    concat_filter = f"{concat_inputs}concat=n={n}:v=0:a=1[outa]"

    _run(
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", concat_filter,
            "-map", "[outa]",
            "-c:a", "libmp3lame", "-q:a", "2",
            "-ar", "44100", "-ac", "2",
            str(output),
        ],
        "merge",
    )


def _normalize(src: Path, out: Path) -> None:
    # Probe duration so fade-out can be placed accurately
    dur = _probe_duration(src)
    fade_out_start = max(0.0, dur - 1.0)

    af_parts = [
        "loudnorm=I=-14:TP=-1.5:LRA=11",
        "afftdn=nf=-40",
        "alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=50",
        "afade=t=in:st=0:d=0.5",
    ]
    if fade_out_start > 0:
        af_parts.append(f"afade=t=out:st={fade_out_start:.3f}:d=1.0")

    _run(
        ["ffmpeg", "-y",
         "-i", str(src),
         "-af", ",".join(af_parts),
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
         str(out)],
        "normalize+fade",
    )


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        import json
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _run(cmd: list, label: str) -> None:
    log.debug("Audio [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        log.error("Audio [%s] FAILED:\n%s", label, res.stderr[-500:])
        raise RuntimeError(f"Audio processing failed: {label}")
