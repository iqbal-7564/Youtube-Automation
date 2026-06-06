"""
Auto-generates royalty-free ambient background music for the 4 pipeline emotions.
Uses only Python stdlib (wave + math + array) — zero extra dependencies.
Output: pipeline/assets/music/{excited,mysterious,dramatic,neutral}.wav

Each track is a 60-second seamlessly looping ambient pad created from
layered sine waves at musical chord frequencies, with a slow tremolo
to give movement and prevent it from sounding like a test tone.
"""

import array
import logging
import math
import wave
from pathlib import Path

log = logging.getLogger(__name__)

_SAMPLE_RATE  = 44100
_DURATION_S   = 60      # seconds per track; long enough to loop without repeating audibly
_MASTER_VOL   = 0.18    # 0-1; kept quiet so it sits under voice (audio_processor drops it -20dB more)
_TREMOLO_RATE = 4.5     # Hz — slow amplitude shimmer, inaudible as a pitch
_FADE_S       = 2.5     # fade-in / fade-out at loop boundary for seamless looping

# (frequency_hz, relative_weight, start_phase_rad)
# Multiple layers per emotion build a chord/pad texture.
_EMOTION_CHORDS: dict[str, list[tuple[float, float, float]]] = {
    # C major — bright, energetic, optimistic
    "excited": [
        ( 98.00, 0.40, 0.00),   # G2   deep bass pulse
        (196.00, 0.30, 0.10),   # G3   bass octave
        (261.63, 0.35, 0.20),   # C4   root
        (329.63, 0.25, 0.40),   # E4   major third
        (392.00, 0.20, 0.60),   # G4   fifth
        (523.25, 0.12, 0.80),   # C5   sparkle octave
    ],
    # A natural minor — dark, tense, suspenseful
    "mysterious": [
        (110.00, 0.45, 0.00),   # A2   deep bass
        (220.00, 0.35, 0.15),   # A3   root
        (261.63, 0.28, 0.40),   # C4   minor third
        (329.63, 0.22, 0.70),   # E4   fifth
        (392.00, 0.15, 0.90),   # G4   flat seventh — adds minor-7 colour
        (146.83, 0.10, 0.50),   # D3   tension note
    ],
    # A power chord — heavy, urgent, cinematic
    "dramatic": [
        ( 55.00, 0.50, 0.00),   # A1   sub-bass rumble
        (110.00, 0.45, 0.00),   # A2   bass
        (220.00, 0.35, 0.20),   # A3   octave
        (164.81, 0.25, 0.50),   # E3   fifth
        (329.63, 0.18, 0.70),   # E4   high fifth
        (174.61, 0.10, 0.30),   # F3   added tension
    ],
    # C major pad — calm, warm, background
    "neutral": [
        ( 65.41, 0.40, 0.00),   # C2   gentle sub
        (130.81, 0.38, 0.10),   # C3   root
        (196.00, 0.28, 0.30),   # G3   fifth
        (261.63, 0.22, 0.50),   # C4   octave
        (329.63, 0.15, 0.70),   # E4   major third
        (392.00, 0.10, 0.90),   # G4   high fifth
    ],
}

# Tremolo rates differ slightly per emotion to reinforce the mood
_TREMOLO_BY_EMOTION: dict[str, float] = {
    "excited":    6.0,   # faster shimmer — energetic feel
    "mysterious": 3.0,   # very slow pulse — eerie
    "dramatic":   4.0,   # medium — tension without jitter
    "neutral":    2.5,   # barely noticeable — relaxed
}


def _make_samples(layers: list[tuple[float, float, float]],
                  tremolo_hz: float,
                  duration_s: int) -> list[int]:
    n = duration_s * _SAMPLE_RATE
    total_w = sum(w for _, w, _ in layers)
    fade_n  = int(_FADE_S * _SAMPLE_RATE)
    out     = []

    for i in range(n):
        t = i / _SAMPLE_RATE

        # Sum layered sine waves
        raw = sum(
            w * math.sin(2 * math.pi * freq * t + phase)
            for freq, w, phase in layers
        )
        raw /= total_w  # normalise to -1..+1

        # Slow tremolo — amplitude shimmer for musicality
        tremolo = 1.0 - 0.12 * (1 - math.cos(2 * math.pi * tremolo_hz * t)) / 2

        # Loop-boundary fade so the track loops without a click
        fade = 1.0
        if i < fade_n:
            fade = i / fade_n
        elif i > n - fade_n:
            fade = (n - i) / fade_n

        sample = raw * tremolo * fade * _MASTER_VOL
        out.append(max(-32767, min(32767, int(sample * 32767))))

    return out


def generate_music(output_dir: Path) -> None:
    """Generate one WAV file per emotion in output_dir. Skips existing files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for emotion, layers in _EMOTION_CHORDS.items():
        out_path = output_dir / f"{emotion}.wav"
        if out_path.exists():
            log.debug("Music already exists, skipping: %s", out_path.name)
            continue

        log.info("Generating background music: %s", out_path.name)
        tremolo_hz = _TREMOLO_BY_EMOTION.get(emotion, _TREMOLO_RATE)
        samples    = _make_samples(layers, tremolo_hz, _DURATION_S)

        with wave.open(str(out_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)   # 16-bit PCM
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(array.array("h", samples).tobytes())

        kb = out_path.stat().st_size // 1024
        log.info("  Saved %s (%d KB, %ds)", out_path.name, kb, _DURATION_S)
