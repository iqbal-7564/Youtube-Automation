"""
STEP 3 — Master Timeline Build

CRITICAL: This is the single source of truth read by every subsequent step.
Built from script segments BEFORE voice generation.
Voice generator updates it with ACTUAL durations after generating audio.
"""

import logging

log = logging.getLogger(__name__)

_WPS = 2.8          # words per second (news pace)
_FPS = 30

# Transition per segment label (applied AFTER the scene)
_TRANSITIONS = {
    "HOOK":    "cut",
    "TENSION": "cut",
    "CORE":    "cut",
    "PAYOFF":  "cross-dissolve",
    "CLOSE":   "fade-to-black",
}

# Target scene length (seconds) per segment; 999 = single scene for full segment
_SCENE_INTERVAL = {
    "HOOK":    999,
    "TENSION": 6.0,
    "CORE":    4.5,
    "PAYOFF":  999,
    "CLOSE":   999,
}


def build_timeline(script: dict, intent: str = "") -> dict:
    scenes: list[dict] = []
    elapsed_ms  = 0
    scene_id    = 1

    for seg in script["segments"]:
        label    = seg["label"]
        text     = seg["text"].strip()
        words    = text.split()
        est_ms   = int(len(words) / _WPS * 1000)

        interval_s  = _SCENE_INTERVAL[label]
        n_scenes    = max(1, round((est_ms / 1000) / interval_s))
        base_dur_ms = est_ms // n_scenes

        for sc_idx in range(n_scenes):
            # Distribute words evenly across scenes in this segment
            wpsc   = max(1, len(words) // n_scenes)
            w_start = sc_idx * wpsc
            w_end   = (w_start + wpsc) if sc_idx < n_scenes - 1 else len(words)
            sc_text = " ".join(words[w_start:w_end])

            dur_ms = base_dur_ms if sc_idx < n_scenes - 1 else (est_ms - base_dur_ms * (n_scenes - 1))
            dur_ms = max(dur_ms, 1000)   # minimum 1 second per scene

            start_ms = elapsed_ms
            end_ms   = elapsed_ms + dur_ms

            scenes.append({
                "scene_id":       scene_id,
                "segment_label":  label,
                "start_ms":       start_ms,
                "end_ms":         end_ms,
                "duration_ms":    dur_ms,
                "script_text":    sc_text,
                "voice_start_ms": start_ms,
                "voice_end_ms":   end_ms,
                "subtitle_lines": _build_subtitle_lines(sc_text, start_ms, end_ms),
                "visual_keyword": "",
                "visual_file":    "",
                "clip_type":      "video",
                "clip_score":     0.0,
                "retry_count":    0,
                "transition":     _TRANSITIONS[label],
            })

            elapsed_ms += dur_ms
            scene_id   += 1

    total_s  = elapsed_ms / 1000
    profile  = "shorts"  if total_s <= 60 else "standard"
    W, H     = (1080, 1920) if profile == "shorts" else (1920, 1080)

    return {
        "total_duration_seconds": round(total_s, 2),
        "total_duration_ms":      elapsed_ms,
        "fps":                    _FPS,
        "profile":                profile,
        "width":                  W,
        "height":                 H,
        "intent":                 intent.upper(),
        "scenes":                 scenes,
    }


def _build_subtitle_lines(text: str, start_ms: int, end_ms: int) -> list[dict]:
    """Split text into ≤6-word subtitle lines with evenly distributed timing."""
    words   = text.split()
    chunks: list[str] = []
    buf: list[str]    = []

    for w in words:
        buf.append(w)
        if len(buf) >= 6:
            chunks.append(" ".join(buf))
            buf = []
    if buf:
        chunks.append(" ".join(buf))

    if not chunks:
        return []

    dur_ms     = max(end_ms - start_ms, 500)
    ms_per_ln  = max(500, dur_ms // len(chunks))
    result: list[dict] = []
    t = start_ms

    for i, chunk in enumerate(chunks):
        ln_start = t
        ln_end   = (t + ms_per_ln) if i < len(chunks) - 1 else end_ms
        ln_end   = max(ln_end, ln_start + 500)
        result.append({"text": chunk, "start_ms": ln_start, "end_ms": ln_end})
        t = ln_end

    return result
