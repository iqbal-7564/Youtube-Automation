"""
STEP 3 — Master Timeline Build

CRITICAL: This is the single source of truth read by every subsequent step.
Built from script segments BEFORE voice generation.
Voice generator updates it with ACTUAL durations after generating audio.

SHORTS PSYCHOLOGY:
  Shorts viewers decide in 1-2 seconds. Hook must be hyper-fast.
  Maximum hook scene: 2 500 ms. Pattern interruption every 3-4 scenes.
  Ultra-short TENSION intervals force constant novelty.

AUDIENCE PERSONA DWELL TIMES:
  Different categories have different optimal pacing.
  SPACE/SCIENCE: viewers want more detail → longer dwell
  ANIMALS/NATURE: emotional, fast → shorter dwell
  HISTORY/CULTURE: dramatic narration → moderate-long dwell
  GEOGRAPHY/OCEAN: visual-led → moderate dwell

COMPLEXITY-BASED minimum dwell times are further adjusted per persona:
  simple   → persona_min × 0.8
  moderate → persona_min × 1.0
  complex  → persona_min × 1.3
"""

import logging

log = logging.getLogger(__name__)

_WPS = 2.8          # words per second (news pace)
_FPS = 30

# Transition applied AFTER the scene ends
_TRANSITIONS = {
    "HOOK":    "cut",
    "TENSION": "cut",
    "CORE":    "cut",
    "PAYOFF":  "cross-dissolve",
    "CLOSE":   "fade-to-black",
}

# Target scene length (seconds) per segment for STANDARD profile
_SCENE_INTERVAL_STANDARD = {
    "HOOK":    999,
    "TENSION": 6.0,
    "CORE":    4.5,
    "PAYOFF":  999,
    "CLOSE":   999,
}

# Shorts: hyper-short intervals to force constant novelty + pattern interruption
_SCENE_INTERVAL_SHORTS = {
    "HOOK":    999,   # single hook scene, but dwell time capped below
    "TENSION": 4.5,   # shorter TENSION splits force 2 quick scenes
    "CORE":    3.5,   # ultra-short CORE scenes keep pacing aggressive
    "PAYOFF":  999,
    "CLOSE":   999,
}

# Base minimum dwell time (ms) per category — audience persona
_PERSONA_BASE_MS: dict[str, dict[str, int]] = {
    "SPACE":     {"simple": 3_000, "moderate": 5_000, "complex": 7_000},
    "SCIENCE":   {"simple": 3_000, "moderate": 5_000, "complex": 7_000},
    "HISTORY":   {"simple": 3_500, "moderate": 5_500, "complex": 7_500},
    "CULTURE":   {"simple": 3_500, "moderate": 5_500, "complex": 7_500},
    "ANIMALS":   {"simple": 2_000, "moderate": 3_500, "complex": 5_000},
    "NATURE":    {"simple": 2_000, "moderate": 3_500, "complex": 5_000},
    "GEOGRAPHY": {"simple": 2_500, "moderate": 4_000, "complex": 5_500},
    "OCEAN":     {"simple": 2_500, "moderate": 4_000, "complex": 5_500},
}
_DEFAULT_PERSONA_MS = {"simple": 3_000, "moderate": 4_500, "complex": 6_000}

# Shorts cap: hook scene never exceeds this regardless of TTS length
_SHORTS_HOOK_CAP_MS = 2_500

# Global emotional arc per narrative template.
# Overrides LLM-assigned per-segment emotion to ensure the full-video
# emotional journey is coherent and intentional.
_EMOTIONAL_ARC: dict[str, dict[str, str]] = {
    "classic": {
        "HOOK":    "excited",     # high energy capture
        "TENSION": "mysterious",  # pull into mystery
        "CORE":    "neutral",     # informational delivery
        "PAYOFF":  "dramatic",    # emotional peak
        "CLOSE":   "excited",     # leave on high energy
    },
    "mystery": {
        "HOOK":    "mysterious",  # open with unanswered question
        "TENSION": "dramatic",    # deepen the dread/curiosity
        "CORE":    "mysterious",  # sustained tension
        "PAYOFF":  "excited",     # revelation energy
        "CLOSE":   "neutral",     # calm after revelation
    },
    "shock_first": {
        "HOOK":    "dramatic",    # bold impossible claim
        "TENSION": "excited",     # challenge the disbelief energetically
        "CORE":    "neutral",     # methodical proof
        "PAYOFF":  "dramatic",    # implication hits hard
        "CLOSE":   "excited",     # tease even more
    },
    "reverse": {
        "HOOK":    "dramatic",    # stunning outcome stated
        "TENSION": "mysterious",  # how is this possible?
        "CORE":    "neutral",     # unwrap the cause chain
        "PAYOFF":  "excited",     # original cause revealed
        "CLOSE":   "mysterious",  # another hidden pattern exists
    },
}


def build_timeline(script: dict, intent: str = "") -> dict:
    import os
    intent_upper = intent.upper()
    persona_ms   = _PERSONA_BASE_MS.get(intent_upper, _DEFAULT_PERSONA_MS)

    # VIDEO_FORMAT env var takes priority; fall back to word-count estimate
    video_format = os.getenv("VIDEO_FORMAT", "").lower()
    if video_format == "shorts":
        is_shorts_est = True
    elif video_format in ("standard", "long"):
        is_shorts_est = False
    else:
        # Auto-detect from script word count
        total_words   = sum(len(s["text"].split()) for s in script["segments"])
        est_total_s   = total_words / _WPS
        is_shorts_est = est_total_s <= 65

    scene_interval = _SCENE_INTERVAL_SHORTS if is_shorts_est else _SCENE_INTERVAL_STANDARD

    scenes: list[dict] = []
    elapsed_ms = 0
    scene_id   = 1

    for seg in script["segments"]:
        label      = seg["label"]
        text       = seg["text"].strip()
        emotion    = seg.get("emotion",    "neutral")
        complexity = seg.get("complexity", "simple")
        words      = text.split()
        est_ms     = int(len(words) / _WPS * 1000)

        interval_s = scene_interval[label]
        n_scenes   = max(1, round((est_ms / 1000) / interval_s))
        base_dur_ms = est_ms // n_scenes

        # Persona-based minimum dwell, adjusted by complexity
        base_min = persona_ms.get(complexity, 3_000)
        min_dur_ms = base_min

        for sc_idx in range(n_scenes):
            wpsc    = max(1, len(words) // n_scenes)
            w_start = sc_idx * wpsc
            w_end   = (w_start + wpsc) if sc_idx < n_scenes - 1 else len(words)
            sc_text = " ".join(words[w_start:w_end])

            dur_ms = base_dur_ms if sc_idx < n_scenes - 1 \
                     else (est_ms - base_dur_ms * (n_scenes - 1))
            dur_ms = max(dur_ms, min_dur_ms)

            # Shorts: cap HOOK scene to prevent over-long openers
            if label == "HOOK" and is_shorts_est:
                dur_ms = min(dur_ms, _SHORTS_HOOK_CAP_MS)

            start_ms = elapsed_ms
            end_ms   = elapsed_ms + dur_ms

            # Detect WOW marker in script text for downstream intensity spike
            has_wow = "[WOW]" in sc_text
            sc_text_clean = sc_text.replace("[WOW]", "").strip()

            scenes.append({
                "scene_id":        scene_id,
                "segment_label":   label,
                "start_ms":        start_ms,
                "end_ms":          end_ms,
                "duration_ms":     dur_ms,
                "script_text":     sc_text_clean,
                "emotion":         emotion,
                "complexity":      complexity,
                "voice_start_ms":  start_ms,
                "voice_end_ms":    end_ms,
                "subtitle_lines":  _build_subtitle_lines(sc_text_clean, start_ms, end_ms),
                "visual_keyword":  "",
                "visual_keywords": [],
                "visual_file":     "",
                "clip_type":       "video",
                "clip_score":      0.0,
                "retry_count":     0,
                "focus_region":    "center",
                "motion_emotion":  emotion,
                "has_wow":         has_wow,
                "transition":      _TRANSITIONS[label],
                "tts_engine":      "",
            })

            elapsed_ms += dur_ms
            scene_id   += 1

    # Apply global emotional arc — overrides LLM per-segment emotions for
    # a coherent full-video emotional journey
    narrative_template = script.get("narrative_template", "classic")
    arc = _EMOTIONAL_ARC.get(narrative_template, _EMOTIONAL_ARC["classic"])
    for sc in scenes:
        label = sc["segment_label"]
        if label in arc:
            sc["emotion"]       = arc[label]
            sc["motion_emotion"] = arc[label]

    total_s = elapsed_ms / 1000
    profile = "shorts"  if total_s <= 60 else "standard"
    W, H    = (1080, 1920) if profile == "shorts" else (1920, 1080)

    return {
        "total_duration_seconds": round(total_s, 2),
        "total_duration_ms":      elapsed_ms,
        "fps":                    _FPS,
        "profile":                profile,
        "width":                  W,
        "height":                 H,
        "intent":                 intent_upper,
        "pacing_profile":         intent_upper or "DEFAULT",
        "narrative_template":     script.get("narrative_template", "classic"),
        "scenes":                 scenes,
    }


def _build_subtitle_lines(text: str, start_ms: int, end_ms: int) -> list[dict]:
    """Split text into ≤4-word subtitle chunks with evenly distributed timing."""
    words  = text.split()
    chunks: list[str] = []
    buf:    list[str] = []

    for w in words:
        buf.append(w)
        if len(buf) >= 4:
            chunks.append(" ".join(buf))
            buf = []
    if buf:
        chunks.append(" ".join(buf))

    if not chunks:
        return []

    dur_ms    = max(end_ms - start_ms, 500)
    ms_per_ln = max(500, dur_ms // len(chunks))
    result: list[dict] = []
    t = start_ms

    for i, chunk in enumerate(chunks):
        ln_start = t
        ln_end   = (t + ms_per_ln) if i < len(chunks) - 1 else end_ms
        ln_end   = max(ln_end, ln_start + 500)
        result.append({"text": chunk, "start_ms": ln_start, "end_ms": ln_end})
        t = ln_end

    return result
