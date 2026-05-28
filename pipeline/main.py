#!/usr/bin/env python3
"""
News Video Pipeline — Main Orchestrator (13 steps, sequential).
master_timeline.json is the single source of truth updated by each step.
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
_PIPELINE_DIR = Path(__file__).parent
_ROOT_DIR     = _PIPELINE_DIR.parent

# pipeline/scripts must be at index 0 — wins over any same-named module in root/scripts
sys.path.insert(0, str(_PIPELINE_DIR / "scripts"))
# root/scripts at index 1 — only used for notify.py and other helpers not in pipeline
sys.path.insert(1, str(_ROOT_DIR / "scripts"))

TEMP_DIR   = _PIPELINE_DIR / "temp"
OUTPUT_DIR = _PIPELINE_DIR / "output"
LOGS_DIR   = _PIPELINE_DIR / "logs"

for _d in [
    TEMP_DIR, TEMP_DIR / "voice", TEMP_DIR / "visuals",
    TEMP_DIR / "subtitles", TEMP_DIR / "scenes",
    OUTPUT_DIR, LOGS_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)

TIMELINE_PATH = TEMP_DIR / "master_timeline.json"

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("pipeline.main")

# ── Lazy imports (after sys.path is set) ──────────────────────────────────────
from topic_selector    import select_topic
from script_generator  import generate_script
from timeline_builder  import build_timeline
from voice_generator   import generate_voices
from scene_planner     import plan_scenes
from visual_fetcher    import fetch_visuals
from subtitle_generator import generate_subtitles
from video_assembler   import assemble_video
from audio_processor   import process_audio
from encoder           import encode_video
from quality_gate      import run_quality_gate
from uploader          import upload_video
from analytics         import log_result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save(timeline: dict) -> None:
    TIMELINE_PATH.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))


def _log_quality_failure(gate: dict, topic: dict) -> None:
    path     = LOGS_DIR / "quality_failures.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.append({
        "timestamp": datetime.utcnow().isoformat(),
        "topic":     topic.get("title"),
        "intent":    topic.get("intent"),
        **gate,
    })
    path.write_text(json.dumps(existing[-100:], indent=2))


def _notify(msg: str) -> None:
    try:
        from notify import notify_failure
        notify_failure("News Video Pipeline", msg)
    except Exception:
        pass


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline() -> bool:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log.info("=" * 65)
    log.info("NEWS VIDEO PIPELINE — START  %s", ts)
    log.info("=" * 65)

    try:
        # ── 1: Topic Selection ───────────────────────────────────────────────
        log.info("[1/13] Topic Selection")
        topic = select_topic(LOGS_DIR)
        if not topic:
            log.warning("No suitable topic found — aborting.")
            return False
        log.info("  [%s] %s", topic["intent"], topic["title"][:80])

        # ── 2: Script Generation ─────────────────────────────────────────────
        log.info("[2/13] Script Generation")
        script = generate_script(topic)
        log.info("  Segments: %d  Est. %ds",
                 len(script["segments"]), script["total_estimated_seconds"])

        # ── 3: Master Timeline Build ─────────────────────────────────────────
        log.info("[3/13] Timeline Build")
        timeline = build_timeline(script, topic["intent"])
        _save(timeline)
        log.info("  Scenes: %d  Duration: %.1fs  Profile: %s",
                 len(timeline["scenes"]),
                 timeline["total_duration_seconds"],
                 timeline["profile"])

        # ── 4: Voice Generation ──────────────────────────────────────────────
        log.info("[4/13] Voice Generation")
        timeline = generate_voices(timeline, TEMP_DIR / "voice")
        _save(timeline)
        log.info("  Actual duration: %.1fs", timeline["total_duration_seconds"])

        # ── 5: Scene Planning ────────────────────────────────────────────────
        log.info("[5/13] Scene Planning")
        timeline = plan_scenes(timeline, topic["intent"])
        _save(timeline)
        log.info("  Keywords assigned to %d scenes", len(timeline["scenes"]))

        # ── 6: Visual Fetch + Validation ─────────────────────────────────────
        log.info("[6/13] Visual Fetch")
        timeline = fetch_visuals(timeline, TEMP_DIR / "visuals")
        _save(timeline)
        log.info("  Visuals ready for %d scenes", len(timeline["scenes"]))

        # ── 7: Subtitle Generation ───────────────────────────────────────────
        log.info("[7/13] Subtitle Generation")
        generate_subtitles(timeline, TEMP_DIR / "subtitles")
        log.info("  SRT files written")

        # ── 8: Video Assembly ────────────────────────────────────────────────
        log.info("[8/13] Video Assembly")
        assembled = assemble_video(timeline, TEMP_DIR, topic["intent"])
        log.info("  Assembled: %s", assembled.name)

        # ── 9: Audio Processing ──────────────────────────────────────────────
        log.info("[9/13] Audio Processing")
        norm_audio = process_audio(TEMP_DIR / "voice", TEMP_DIR)
        log.info("  Normalized: %s", norm_audio.name)

        # ── 10: Encoding ─────────────────────────────────────────────────────
        log.info("[10/13] Encoding")
        profile     = timeline["profile"]
        output_path = OUTPUT_DIR / f"{topic['intent']}_{ts}_{profile}.mp4"
        encode_video(assembled, norm_audio, output_path, profile)
        log.info("  Output: %s  (%.1f MB)",
                 output_path.name,
                 output_path.stat().st_size / 1_048_576)

        # ── 11: Quality Gate ─────────────────────────────────────────────────
        log.info("[11/13] Quality Gate")
        gate = run_quality_gate(output_path, timeline, TEMP_DIR / "subtitles")
        if not gate["passed"]:
            log.error("  GATE FAILED: %s", gate["fail_reason"])
            _log_quality_failure(gate, topic)
            _notify(f"Quality gate failed: {gate['fail_reason']}")
            return False
        log.info("  All 7 checks passed")

        # ── 12: Upload + Metadata ────────────────────────────────────────────
        log.info("[12/13] Upload")
        thumb_path = OUTPUT_DIR / f"thumb_{ts}.jpg"
        video_id   = upload_video(output_path, thumb_path, script, topic, timeline, profile)
        if not video_id:
            log.error("  Upload failed — no video_id returned")
            return False
        log.info("  https://youtu.be/%s", video_id)

        # ── 13: Analytics ────────────────────────────────────────────────────
        log.info("[13/13] Analytics")
        log_result(video_id, topic, timeline, gate, profile, LOGS_DIR)

        log.info("=" * 65)
        log.info("PIPELINE COMPLETE — SUCCESS  video_id=%s", video_id)
        log.info("=" * 65)
        return True

    except Exception as exc:
        log.error("PIPELINE FAILED: %s", exc)
        log.error(traceback.format_exc())
        _notify(str(exc))
        return False


if __name__ == "__main__":
    sys.exit(0 if run_pipeline() else 1)
