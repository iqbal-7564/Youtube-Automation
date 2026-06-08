"""
CINEMATIC PLANNER — Director-level shot sequencing, suspense arc, pacing rhythm

Adds cinematic metadata to every scene after scene_planner:

  shot_type      WIDE / AERIAL / MEDIUM / CLOSE / EXTREME_CLOSE
  pacing         FAST_CUT / HOLD / SLOW_BUILD / IMPACT
  suspense_level 0.0–1.0 — drives motion preset intensity in video_assembler
  contrast_shot  True if this scene should visually contrast the previous

Director rules applied:
  1. Shot variety — never 3+ consecutive identical shot types
  2. Suspense arc — rises HOOK→TENSION→CORE, peaks at WOW, releases in PAYOFF
  3. Contrast rhythm — alternate wide/dynamic and close/intimate shots
  4. EXTREME_CLOSE reserved for WOW-marked scenes only
  5. PAYOFF always gets AERIAL or WIDE (visual release, breathing room)
  6. CLOSE scene always MEDIUM (personal, approachable outro)

Shot type → video_assembler motion preset affinity:
  WIDE / AERIAL  → slow_drift, pan_right, pan_left (low zoom, expansive)
  MEDIUM         → push_in, rise_up
  CLOSE          → reveal_pull, push_in (more zoom)
  EXTREME_CLOSE  → impact_zoom (maximum drama)
"""

import json
import logging
import random
from pathlib import Path

log = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent.parent / "logs"

# ── Shot sequence pools per segment label ─────────────────────────────────────
# Lists are cycled round-robin across scenes within that segment.
# EXTREME_CLOSE is reserved for WOW-marked scenes only (overridden below).

_SHOT_POOL: dict[str, list[str]] = {
    "HOOK":    ["WIDE", "CLOSE"],
    "TENSION": ["CLOSE", "MEDIUM", "EXTREME_CLOSE", "CLOSE"],
    "CORE":    ["MEDIUM", "CLOSE", "MEDIUM", "EXTREME_CLOSE", "AERIAL", "CLOSE"],
    "PAYOFF":  ["AERIAL", "WIDE"],
    "CLOSE":   ["MEDIUM"],
}

_PACING_POOL: dict[str, list[str]] = {
    "HOOK":    ["IMPACT", "FAST_CUT"],
    "TENSION": ["SLOW_BUILD", "FAST_CUT", "HOLD"],
    "CORE":    ["HOLD", "FAST_CUT", "HOLD", "IMPACT", "SLOW_BUILD", "FAST_CUT"],
    "PAYOFF":  ["SLOW_BUILD", "HOLD"],
    "CLOSE":   ["HOLD"],
}

# Suspense level per segment (base values — WOW marker spikes to 1.0)
_SUSPENSE_BASE: dict[str, float] = {
    "HOOK":    0.75,
    "TENSION": 0.85,
    "CORE":    0.60,
    "PAYOFF":  0.50,
    "CLOSE":   0.20,
}

# Motion preset affinity — cinematic planner overrides motion_emotion when
# a specific shot type demands a specific preset family
_SHOT_MOTION_OVERRIDE: dict[str, str] = {
    "WIDE":          "neutral",     # slow_drift or pan
    "AERIAL":        "neutral",     # slow_drift
    "MEDIUM":        "excited",     # push_in or rise_up
    "CLOSE":         "mysterious",  # reveal_pull or push_in
    "EXTREME_CLOSE": "dramatic",    # impact_zoom
}


def _load_retention_signal() -> str | None:
    """Read last retention signal from adaptive_params for shot adaptation."""
    try:
        p = _LOGS_DIR / "adaptive_params.json"
        if p.exists():
            return json.loads(p.read_text()).get("last_signal")
    except Exception:
        pass
    return None


def _weighted_shot(pool: list[str], label: str, retention_signal: str | None) -> str:
    """
    Weighted random selection within pool — same input no longer always produces
    same output. Weights shifted by retention signal from analytics.
    """
    if len(pool) == 1:
        return pool[0]

    # Base weights: first item 50%, second 30%, rest split evenly
    n = len(pool)
    weights = [0.5] + [0.3] + [(0.2 / max(n - 2, 1))] * max(n - 2, 0)
    weights = weights[:n]

    # Shift weights based on retention signal
    if retention_signal == "early_drop":
        # Early drop → more FAST_CUT pacing → prefer CLOSE/MEDIUM shots
        for i, shot in enumerate(pool):
            if shot in ("CLOSE", "MEDIUM"):
                weights[i] = min(weights[i] * 1.5, 0.9)
    elif retention_signal == "high_retention":
        # High retention → allow more AERIAL slow scenes
        for i, shot in enumerate(pool):
            if shot in ("AERIAL", "WIDE"):
                weights[i] = min(weights[i] * 1.4, 0.9)

    total = sum(weights)
    weights = [w / total for w in weights]
    return random.choices(pool, weights=weights, k=1)[0]


def plan_cinematics(timeline: dict) -> dict:
    """
    Add shot_type, pacing, suspense_level, and contrast_shot to each scene.
    Also overrides motion_emotion based on shot type for consistent preset selection.
    """
    scenes = timeline.get("scenes", [])
    profile   = timeline.get("profile", "standard")
    is_shorts = profile == "shorts"
    retention_signal = _load_retention_signal()
    pool_idx: dict[str, int] = {}
    prev_shot = None
    prev_prev_shot = None

    for sc in scenes:
        label    = sc.get("segment_label", "CORE")
        has_wow  = sc.get("has_wow", False)
        emotion  = sc.get("emotion", "neutral")
        dur_ms   = sc.get("duration_ms", 3000)

        if label == "CLOSE":
            sc["shot_type"]      = "MEDIUM"
            sc["pacing"]         = "HOLD"
            sc["suspense_level"] = 0.20
            sc["contrast_shot"]  = False
            sc["motion_emotion"] = "neutral"
            prev_prev_shot = prev_shot
            prev_shot = "MEDIUM"
            continue

        # Shorts HOOK: maximum visual shock — EXTREME_CLOSE + IMPACT, no exceptions.
        # Wide shots on the opening frame lose viewers in the first second.
        if label == "HOOK" and is_shorts:
            sc["shot_type"]      = "EXTREME_CLOSE"
            sc["pacing"]         = "IMPACT"
            sc["suspense_level"] = 1.0
            sc["contrast_shot"]  = False
            sc["motion_emotion"] = "dramatic"
            prev_prev_shot       = prev_shot
            prev_shot            = "EXTREME_CLOSE"
            continue

        pool   = _SHOT_POOL.get(label, ["MEDIUM"])
        p_pool = _PACING_POOL.get(label, ["HOLD"])
        idx    = pool_idx.get(label, 0)

        # Weighted random selection (not pure round-robin)
        shot   = _weighted_shot(pool, label, retention_signal)
        pacing = p_pool[idx % len(p_pool)]
        pool_idx[label] = idx + 1

        # EXTREME_CLOSE: allowed on WOW scenes OR dramatic emotion + high suspense
        base_suspense = _SUSPENSE_BASE.get(label, 0.60)
        if shot == "EXTREME_CLOSE" and not has_wow:
            if emotion == "dramatic" and base_suspense > 0.7:
                pass  # allow emotional override
            else:
                shot   = "CLOSE"
                pacing = "FAST_CUT"

        # Shot variety rule: avoid 3 consecutive identical shot types
        if shot == prev_shot == prev_prev_shot:
            alts = [s for s in pool if s != shot]
            if alts:
                shot = alts[0]

        # WOW marker: always spike to EXTREME_CLOSE + IMPACT + max suspense
        if has_wow:
            shot   = "EXTREME_CLOSE"
            pacing = "IMPACT"

        suspense = 1.0 if has_wow else base_suspense
        # Micro-oscillation: adds small jitter per scene for realistic retention curves
        suspense = round(
            min(1.0, max(0.0, suspense + random.uniform(-0.1, 0.1))), 2
        )

        # Duration-aware motion selection
        if dur_ms < 2000 and pacing == "FAST_CUT":
            sc["motion_preset_hint"] = "impact_zoom"
        elif dur_ms > 4000 and pacing == "HOLD":
            sc["motion_preset_hint"] = "slow_drift"

        # Contrast flag
        contrast = (
            shot in ("WIDE", "AERIAL") and prev_shot in ("CLOSE", "EXTREME_CLOSE")
        ) or (
            shot in ("CLOSE", "EXTREME_CLOSE") and prev_shot in ("WIDE", "AERIAL")
        )

        sc["shot_type"]      = shot
        sc["pacing"]         = pacing
        sc["suspense_level"] = suspense
        sc["contrast_shot"]  = contrast
        sc["motion_emotion"] = _SHOT_MOTION_OVERRIDE.get(shot, sc.get("motion_emotion", "neutral"))

        prev_prev_shot = prev_shot
        prev_shot      = shot

    log.info("Cinematics planned (%d scenes) — arc: HOOK→TENSION→CORE→PAYOFF→CLOSE",
             len(scenes))
    return timeline
