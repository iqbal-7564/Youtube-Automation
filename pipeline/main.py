#!/usr/bin/env python3
"""
News Video Pipeline — Main Orchestrator (14 steps, sequential).
master_timeline.json is the single source of truth updated by each step.

Quality gate failure triggers up to 3 retry attempts with degraded renders:
  Attempt 1 — full render (normal)
  Attempt 2 — strip xfade transitions, re-assemble
  Attempt 3 — single title-card fallback (black + text)
If all 3 fail, the slot is logged and skipped with an alert.
"""

import json
import logging
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
_PIPELINE_DIR = Path(__file__).parent

sys.path.insert(0, str(_PIPELINE_DIR / "scripts"))

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

# ── Imports (after sys.path is set) ───────────────────────────────────────────
from topic_selector      import select_topic
from script_generator    import generate_script
from timeline_builder    import build_timeline
from voice_generator     import generate_voices
from scene_planner       import plan_scenes
from visual_fetcher      import fetch_visuals
from subtitle_generator  import generate_subtitles
from video_assembler     import assemble_video
from audio_processor     import process_audio
from encoder             import encode_video
from quality_gate        import run_quality_gate
from thumbnail_generator import generate_thumbnail
from uploader            import upload_video
from news_analytics      import log_result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _save(timeline: dict) -> None:
    TIMELINE_PATH.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))


def _log_quality_failure(gate: dict, topic: dict, attempt: int) -> None:
    path     = LOGS_DIR / "quality_failures.json"
    existing = json.loads(path.read_text()) if path.exists() else []
    existing.append({
        "timestamp": datetime.utcnow().isoformat(),
        "topic":     topic.get("title"),
        "intent":    topic.get("intent"),
        "attempt":   attempt,
        **gate,
    })
    path.write_text(json.dumps(existing[-100:], indent=2))


def _probe_duration(path: Path) -> float:
    """Return actual file duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _sync_timeline_to_assembled(timeline: dict, assembled: Path) -> None:
    """
    Update total_duration_seconds/ms in the timeline to match the assembled
    video's actual length. The assembler adds pre-roll, hook card, and end card
    on top of the content duration; without this sync the encoder cap and the
    quality gate both use the wrong expected value.
    """
    dur = _probe_duration(assembled)
    if dur > 0 and abs(dur - timeline["total_duration_seconds"]) > 0.1:
        log.info("  Timeline synced: %.2fs → %.2fs (assembler additions)",
                 timeline["total_duration_seconds"], dur)
        timeline["total_duration_seconds"] = round(dur, 2)
        timeline["total_duration_ms"]      = int(dur * 1000)


def _tts_degraded(timeline: dict) -> bool:
    return any(
        sc.get("tts_engine") in ("gtts", "silence")
        for sc in timeline.get("scenes", [])
    )


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline() -> bool:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log.info("=" * 65)
    log.info("NEWS VIDEO PIPELINE — START  %s", ts)
    log.info("=" * 65)

    try:
        # ── 1: Topic Selection ───────────────────────────────────────────────
        log.info("[1/14] Topic Selection")
        topic = select_topic(LOGS_DIR)
        if not topic:
            log.warning("No suitable topic found — aborting.")
            return False
        log.info("  [%s] %s", topic["intent"], topic["title"][:80])

        # ── 2: Script Generation ─────────────────────────────────────────────
        log.info("[2/14] Script Generation")
        script = generate_script(topic)
        log.info("  Segments: %d  Est. %ds",
                 len(script["segments"]), script["total_estimated_seconds"])

        # ── 3: Master Timeline Build ─────────────────────────────────────────
        log.info("[3/14] Timeline Build")
        timeline = build_timeline(script, topic["intent"])
        _save(timeline)
        log.info("  Scenes: %d  Duration: %.1fs  Profile: %s",
                 len(timeline["scenes"]),
                 timeline["total_duration_seconds"],
                 timeline["profile"])

        # ── 4: Voice Generation ──────────────────────────────────────────────
        log.info("[4/14] Voice Generation")
        timeline = generate_voices(timeline, TEMP_DIR / "voice")
        _save(timeline)
        log.info("  Actual duration: %.1fs", timeline["total_duration_seconds"])

        if _tts_degraded(timeline):
            log.warning("  ⚠  TTS DEGRADED: one or more scenes used gTTS/silence. "
                        "Check ELEVENLABS_API_KEY / edge-tts availability.")

        # ── 5: Scene Planning ────────────────────────────────────────────────
        log.info("[5/14] Scene Planning")
        timeline = plan_scenes(timeline, topic["intent"])
        _save(timeline)
        log.info("  Keywords assigned to %d scenes", len(timeline["scenes"]))

        # ── 6: Visual Fetch + Validation ─────────────────────────────────────
        log.info("[6/14] Visual Fetch")
        timeline = fetch_visuals(timeline, TEMP_DIR / "visuals")
        _save(timeline)
        log.info("  Visuals ready for %d scenes", len(timeline["scenes"]))

        # ── 7: Subtitle Generation ───────────────────────────────────────────
        log.info("[7/14] Subtitle Generation")
        generate_subtitles(timeline, TEMP_DIR / "subtitles")
        log.info("  SRT files written")

        # ── 8: Video Assembly ────────────────────────────────────────────────
        log.info("[8/14] Video Assembly")
        assembled = assemble_video(timeline, TEMP_DIR, topic["intent"])
        log.info("  Assembled: %s", assembled.name)

        # Sync timeline duration to assembled file (pre-roll + hook card + end
        # card are added by the assembler and are not in the original timeline).
        _sync_timeline_to_assembled(timeline, assembled)
        _save(timeline)

        # ── 9: Audio Processing ──────────────────────────────────────────────
        log.info("[9/14] Audio Processing")
        norm_audio = process_audio(TEMP_DIR / "voice", TEMP_DIR)
        log.info("  Normalized: %s", norm_audio.name)

        # ── 10: Encoding ─────────────────────────────────────────────────────
        log.info("[10/14] Encoding")
        profile     = timeline["profile"]
        output_path = OUTPUT_DIR / f"{topic['intent']}_{ts}_{profile}.mp4"
        encode_video(assembled, norm_audio, output_path, profile,
                     timeline["total_duration_seconds"])
        log.info("  Output: %s  (%.1f MB)",
                 output_path.name,
                 output_path.stat().st_size / 1_048_576)

        # ── 11: Quality Gate (with retry) ─────────────────────────────────────
        log.info("[11/14] Quality Gate")
        gate = None
        for attempt in range(1, 4):
            gate = run_quality_gate(output_path, timeline, TEMP_DIR / "subtitles")
            if gate["passed"]:
                break

            log.warning("  Gate failed (attempt %d/3): %s", attempt, gate["fail_reason"])
            _log_quality_failure(gate, topic, attempt)

            if attempt == 3:
                log.error("  All 3 gate attempts failed — skipping upload")
                return False

            # Attempt 2: re-assemble without xfade transitions
            if attempt == 1:
                log.info("  Retry: re-assembling without transitions …")
                for sc in timeline["scenes"]:
                    sc["transition"] = "cut"
                assembled = assemble_video(timeline, TEMP_DIR, topic["intent"])
                _sync_timeline_to_assembled(timeline, assembled)
                _save(timeline)
                encode_video(assembled, norm_audio, output_path, profile,
                             timeline["total_duration_seconds"])

            # Attempt 3: minimal title-card fallback
            elif attempt == 2:
                log.info("  Retry: minimal title-card fallback …")
                _title_card_fallback(output_path, topic, timeline, norm_audio, profile)

        assert gate is not None
        if not gate["passed"]:
            return False
        log.info("  All 10 checks passed")

        # ── 12: Thumbnail Generation ──────────────────────────────────────────
        log.info("[12/14] Thumbnail Generation")
        thumb_path = OUTPUT_DIR / f"thumb_{ts}.jpg"
        generate_thumbnail(timeline, script, TEMP_DIR / "visuals", thumb_path)

        # ── 13: Upload + Metadata ─────────────────────────────────────────────
        log.info("[13/14] Upload")
        video_id = upload_video(
            output_path, thumb_path, script, topic, timeline, profile,
            subtitles_dir=TEMP_DIR / "subtitles",
        )
        if not video_id:
            log.error("  Upload failed — no video_id returned")
            return False
        log.info("  https://youtu.be/%s", video_id)

        # ── 14: Analytics ─────────────────────────────────────────────────────
        log.info("[14/14] Analytics")
        log_result(video_id, topic, timeline, gate, profile, LOGS_DIR)

        log.info("=" * 65)
        log.info("PIPELINE COMPLETE — SUCCESS  video_id=%s", video_id)
        log.info("=" * 65)
        return True

    except Exception as exc:
        log.error("PIPELINE FAILED: %s", exc)
        log.error(traceback.format_exc())
        return False


def _title_card_fallback(
    output_path: Path,
    topic: dict,
    timeline: dict,
    audio_path: Path,
    profile: str,
) -> None:
    """Minimal fallback: black background + title text, full audio."""
    import subprocess
    W, H    = timeline["width"], timeline["height"]
    dur_s   = timeline["total_duration_seconds"]
    title   = topic["title"][:60].replace("'", "\\'").replace(":", "\\:")
    font    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    vf      = (f"drawtext=text='{title}':"
               f"fontfile='{font}':fontcolor=white:fontsize=56:"
               f"bordercolor=black:borderw=3:"
               f"x=(w-tw)/2:y=(h-th)/2")
    video_only = output_path.with_suffix(".fallback_v.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=0x0A0A1A:size={W}x{H}:rate=30",
         "-vf", vf, "-t", str(dur_s),
         "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30", "-an",
         str(video_only)],
        capture_output=True, timeout=120,
    )
    from encoder import encode_video
    encode_video(video_only, audio_path, output_path, profile, dur_s)


if __name__ == "__main__":
    sys.exit(0 if run_pipeline() else 1)
