#!/usr/bin/env python3
"""
News Video Pipeline — Main Orchestrator (14 steps, sequential).
master_timeline.json is the single source of truth.

Timeline is LOCKED after step 4 (voice generation).
No downstream step may change total_duration_ms / total_duration_seconds.

Correct step order (per production-grade requirements):
  1  topic_selector      — pick topic
  2  script_generator    — write script
  3  timeline_builder    — build timeline (estimated durations)
  4  voice_generator     — generate audio, LOCK real durations
  5  scene_planner       — assign visual keywords
  6  visual_fetcher      — download + trim visuals
  7  video_assembler     — render scenes (no subtitles burned in)
  8  subtitle_generator  — write SRT using LOCKED timings
  9  audio_processor     — normalise + fade audio
  10 encoder             — mux video + audio (cap = locked duration + 1s)
  11 quality_gate        — 10 checks
  12 thumbnail_generator — design thumbnail
  13 uploader            — upload video + captions + comment
  14 news_analytics      — log results

Quality gate failure triggers up to 3 retry attempts:
  Attempt 2 — re-assemble without xfade transitions
  Attempt 3 — title-card fallback video
"""

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import requests

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("pipeline.main")

from topic_selector      import select_topic
from script_generator    import generate_script
from timeline_builder    import build_timeline
from voice_generator     import generate_voices
from scene_planner       import plan_scenes
from cinematic_planner   import plan_cinematics
from visual_fetcher      import fetch_visuals
from video_assembler     import assemble_video
from subtitle_generator  import generate_subtitles, generate_ass_subtitles
from audio_processor     import process_audio
from encoder             import encode_video
from quality_gate        import run_quality_gate
from thumbnail_generator import generate_thumbnail
from ctr_optimizer       import optimize_ctr
from uploader            import upload_video
from news_analytics      import log_result, apply_adaptive_learning, predict_retention_risk, fetch_peak_hours, update_velocity_queue


def _check_youtube_token() -> bool:
    """
    Validate YouTube upload credentials and quota BEFORE any pipeline work begins.
    Saves a full render cycle if the token is expired or quota is exhausted.
    Returns False only on confirmed quota exhaustion or hard auth failure.
    Network errors pass through so transient issues don't block the pipeline.
    """
    client_id     = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        log.warning("PREFLIGHT: YouTube upload credentials not set — upload will fail")
        return True  # warn but don't block; _preflight() already logged this

    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=10,
        )
        d = r.json()
        if "access_token" not in d:
            err = d.get("error", "unknown")
            log.error(
                "PREFLIGHT: Token refresh failed (%s) — aborting pipeline to save API quota. "
                "Fix YOUTUBE_CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN secrets.", err,
            )
            return False

        token = d["access_token"]
        # 1-unit quota check: channels.list?part=id&mine=true
        q = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "id", "mine": "true"},
            timeout=10,
        )
        if q.status_code == 403:
            reason = (
                q.json().get("error", {})
                 .get("errors", [{}])[0]
                 .get("reason", "unknown")
            )
            if reason == "quotaExceeded":
                log.error(
                    "PREFLIGHT: YouTube API quota exhausted — aborting pipeline. "
                    "Quota resets at midnight Pacific time. "
                    "Consider adding a third GCP project for research API calls."
                )
                return False

        log.info("PREFLIGHT: YouTube token valid, quota available")
        return True

    except Exception as exc:
        log.warning("PREFLIGHT: Token check network error: %s — proceeding", exc)
        return True  # network glitch — don't block, let upload handle it


def check_circuit_breaker(threshold: int = 3) -> None:
    """
    Raise SystemExit if pipeline has failed N consecutive times within 24 hours.
    Prevents runaway API spend and CI minute burn on cascading failures.
    Reset by deleting logs/circuit_state.json or waiting 24 hours.
    """
    state_path = LOGS_DIR / "circuit_state.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text())
        fails = state.get("consecutive_full_failures", 0)
        if fails >= threshold:
            last_fail = state.get("last_failure_ts", 0)
            if time.time() - last_fail < 86400:
                raise SystemExit(
                    f"Circuit open: {fails} consecutive full failures. "
                    "Wait 24h or delete pipeline/logs/circuit_state.json to reset."
                )
    except SystemExit:
        raise
    except Exception as exc:
        log.debug("Circuit breaker check: %s", exc)


def _record_full_failure() -> None:
    """Increment consecutive failure counter. Called when a video fails all retries."""
    state_path = LOGS_DIR / "circuit_state.json"
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state["consecutive_full_failures"] = state.get("consecutive_full_failures", 0) + 1
        state["last_failure_ts"] = time.time()
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(state_path)
        log.warning("Circuit breaker: %d consecutive failure(s) recorded",
                    state["consecutive_full_failures"])
    except Exception as exc:
        log.debug("Record failure: %s", exc)


def _record_success() -> None:
    """Reset failure counter after a successful upload."""
    state_path = LOGS_DIR / "circuit_state.json"
    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"consecutive_full_failures": 0}, indent=2))
        tmp.replace(state_path)
    except Exception as exc:
        log.debug("Record success: %s", exc)


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


def _assert_audio_integrity(audio_path: Path, locked_s: float) -> None:
    """Fail fast if normalized audio is > 1 s shorter than locked timeline.

    Note: normalized audio MAY be slightly longer than locked_s (because
    accurate VBR scanning reveals more content than the original VBR header
    reported).  That is acceptable — the encoder's -shortest will align at
    the video end.  Only fail if audio is shorter (content was dropped).
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(audio_path)],
            capture_output=True, text=True, timeout=15,
        )
        actual = float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        actual = 0.0

    diff = locked_s - actual
    log.info("  Audio integrity: actual=%.3fs locked=%.3fs diff=%.3fs",
             actual, locked_s, diff)

    if diff > 1.0:
        raise RuntimeError(
            f"Audio merge lost {diff:.2f}s — actual={actual:.3f}s "
            f"locked={locked_s:.3f}s. Check voice_std/ files."
        )


def _tts_degraded(timeline: dict) -> bool:
    return any(
        sc.get("tts_engine") in ("gtts", "silence")
        for sc in timeline.get("scenes", [])
    )


def _preflight() -> None:
    """Log warnings for missing API keys before any work begins."""
    import os
    checks = [
        ("GROQ_API_KEY_1",        "Script/topic generation will use fallback"),
        ("ELEVENLABS_API_KEY",    "TTS will fall back to edge-tts/gTTS"),
        ("PEXELS_API_KEY",        "Pexels image fetch disabled — Pixabay only"),
        ("PIXABAY_API_KEY",       "Pixabay image fetch disabled — black clips likely"),
        ("YOUTUBE_CLIENT_ID",     "Upload will FAIL — YouTube credentials missing"),
        ("YOUTUBE_CLIENT_SECRET", "Upload will FAIL — YouTube credentials missing"),
        ("YOUTUBE_REFRESH_TOKEN", "Upload will FAIL — YouTube credentials missing"),
    ]
    for key, msg in checks:
        if not os.getenv(key, "").strip():
            log.warning("PREFLIGHT: %s not set — %s", key, msg)


def run_pipeline() -> bool:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log.info("=" * 65)
    log.info("NEWS VIDEO PIPELINE — START  %s", ts)
    log.info("=" * 65)

    # Guard 1: circuit breaker — abort immediately if N consecutive failures
    check_circuit_breaker()

    _preflight()

    # Guard 2: validate YouTube token + quota before burning any API calls or CI minutes
    if not _check_youtube_token():
        _record_full_failure()
        return False

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

        # ── 3: Timeline Build ────────────────────────────────────────────────
        log.info("[3/14] Timeline Build")
        timeline = build_timeline(script, topic["intent"])
        _save(timeline)
        log.info("  Scenes: %d  Est. %.1fs  Profile: %s",
                 len(timeline["scenes"]),
                 timeline["total_duration_seconds"],
                 timeline["profile"])

        # ── 4: Voice Generation — LOCKS timeline durations ───────────────────
        log.info("[4/14] Voice Generation")
        timeline = generate_voices(timeline, TEMP_DIR / "voice")
        _save(timeline)
        locked_duration_s = timeline["total_duration_seconds"]
        log.info("  Actual duration: %.3fs  ← LOCKED", locked_duration_s)

        if _tts_degraded(timeline):
            log.warning("  ⚠  TTS DEGRADED — check ELEVENLABS_API_KEY / edge-tts")

        # ── 5: Scene Planning ────────────────────────────────────────────────
        log.info("[5/14] Scene Planning")
        timeline = plan_scenes(timeline, topic["intent"])
        timeline = plan_cinematics(timeline)   # shot types, pacing, suspense arc
        _save(timeline)
        log.info("  Keywords assigned to %d scenes", len(timeline["scenes"]))

        # Pre-render retention risk prediction
        risk = predict_retention_risk(timeline)
        log.info("  Retention risk: %.2f  WOW moments: %d  weak scenes: %s",
                 risk["risk_score"], risk["wow_count"],
                 [w["scene"] for w in risk["weak_scenes"]])
        if risk["recommendations"]:
            for rec in risk["recommendations"]:
                log.warning("  Risk recommendation: %s", rec)

        # ── 6: Visual Fetch ──────────────────────────────────────────────────
        log.info("[6/14] Visual Fetch")
        timeline = fetch_visuals(timeline, TEMP_DIR / "visuals")
        _save(timeline)
        log.info("  Visuals ready for %d scenes", len(timeline["scenes"]))

        # ── 7: Video Assembly ────────────────────────────────────────────────
        log.info("[7/14] Video Assembly")
        assembled = assemble_video(timeline, TEMP_DIR, topic["intent"])
        log.info("  Assembled: %s  (locked_duration=%.3fs)",
                 assembled.name, locked_duration_s)

        # ── 8: Subtitle Generation (after assembly, uses locked timings) ─────
        log.info("[8/14] Subtitle Generation")
        generate_subtitles(timeline, TEMP_DIR / "subtitles")
        ass_file = generate_ass_subtitles(timeline, TEMP_DIR / "subtitles")
        log.info("  SRT + ASS files written (%d scenes)", len(timeline["scenes"]))

        # ── 9: Audio Processing ──────────────────────────────────────────────
        log.info("[9/14] Audio Processing")
        norm_audio = process_audio(
            TEMP_DIR / "voice", TEMP_DIR,
            duration_cap_s=timeline["total_duration_seconds"],
            scenes=timeline["scenes"],
        )
        log.info("  Normalized: %s", norm_audio.name)

        # Hard assertion: catch audio merge failures BEFORE the encoder.
        # If merged audio is more than 1s shorter than the locked timeline,
        # something was dropped during TTS concatenation — fail loudly here.
        _assert_audio_integrity(norm_audio, timeline["total_duration_seconds"])

        # ── 10: Encoding ─────────────────────────────────────────────────────
        log.info("[10/14] Encoding")
        profile     = timeline["profile"]
        output_path = OUTPUT_DIR / f"{topic['intent']}_{ts}_{profile}.mp4"
        # Pass LOCKED duration — encoder uses this as the hard cap.
        # timeline["total_duration_seconds"] must never change after step 4.
        encode_video(assembled, norm_audio, output_path, profile,
                     timeline["total_duration_seconds"], ass_path=ass_file)
        log.info("  Output: %s  (%.1f MB)",
                 output_path.name,
                 output_path.stat().st_size / 1_048_576)

        # ── 11: Quality Gate (up to 3 attempts) ──────────────────────────────
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
                _record_full_failure()
                return False

            if attempt == 1:
                log.info("  Retry: re-assembling without transitions …")
                for sc in timeline["scenes"]:
                    sc["transition"] = "cut"
                assembled = assemble_video(timeline, TEMP_DIR, topic["intent"])
                encode_video(assembled, norm_audio, output_path, profile,
                             timeline["total_duration_seconds"], ass_path=ass_file)

            elif attempt == 2:
                log.info("  Retry: title-card fallback …")
                _title_card_fallback(output_path, topic, timeline,
                                     norm_audio, profile)

        assert gate is not None
        if not gate["passed"]:
            return False
        log.info("  All 10 checks passed")

        # ── 12: Thumbnail ─────────────────────────────────────────────────────
        log.info("[12/14] Thumbnail Generation")
        thumb_path = OUTPUT_DIR / f"thumb_{ts}.jpg"

        # CTR optimizer: score title+headline synergy and pick best combination
        hook_text = next(
            (sc["script_text"] for sc in timeline["scenes"]
             if sc["segment_label"] == "HOOK"), ""
        )
        ctr = optimize_ctr(
            script.get("metadata", {}).get("title", topic["title"]),
            hook_text,
            topic["intent"],
        )
        log.info("  CTR score=%.2f synergy=%.2f  title='%s…'",
                 ctr["ctr_score"], ctr["synergy"], ctr["title"][:50])
        # Inject optimised title back into script metadata for uploader
        script.setdefault("metadata", {})["title"] = ctr["title"]

        generate_thumbnail(timeline, script, TEMP_DIR / "visuals", thumb_path)

        # ── 13: Upload ────────────────────────────────────────────────────────
        log.info("[13/14] Upload")
        video_id = upload_video(
            output_path, thumb_path, script, topic, timeline, profile,
            subtitles_dir=TEMP_DIR / "subtitles",
        )
        if not video_id:
            log.error("  Upload failed — no video_id returned")
            _record_full_failure()
            return False
        log.info("  https://youtu.be/%s", video_id)

        # ── 14: Analytics ─────────────────────────────────────────────────────
        log.info("[14/14] Analytics")
        log_result(video_id, topic, timeline, gate, profile, LOGS_DIR)

        # Velocity clustering: check if any recent video is performing above average
        # and queue related topics for the next pipeline run
        update_velocity_queue(LOGS_DIR)

        # Apply adaptive learning — evolve pipeline parameters from retention signal
        hints = gate.get("hints", {})
        if hints.get("retention_signal"):
            apply_adaptive_learning(hints, LOGS_DIR)
            log.info("  Adaptive learning: signal=%s  params updated",
                     hints["retention_signal"])

        _record_success()
        log.info("=" * 65)
        log.info("PIPELINE COMPLETE — SUCCESS  video_id=%s", video_id)
        log.info("=" * 65)
        return True

    except Exception as exc:
        log.error("PIPELINE FAILED: %s", exc)
        log.error(traceback.format_exc())
        _record_full_failure()
        return False


def _title_card_fallback(
    output_path: Path,
    topic: dict,
    timeline: dict,
    audio_path: Path,
    profile: str,
) -> None:
    W, H  = timeline["width"], timeline["height"]
    dur_s = timeline["total_duration_seconds"]
    title = topic["title"][:60].replace("'", "\\'").replace(":", "\\:")
    font  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    vf    = (f"drawtext=text='{title}':"
             f"fontfile='{font}':fontcolor=white:fontsize=56:"
             f"bordercolor=black:borderw=3:x=(w-tw)/2:y=(h-th)/2")
    video_only = output_path.with_suffix(".fallback_v.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=0x0A0A1A:size={W}x{H}:rate=30",
         "-vf", vf, "-t", str(dur_s),
         "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30", "-an",
         str(video_only)],
        capture_output=True, timeout=120,
    )
    encode_video(video_only, audio_path, output_path, profile, dur_s)


if __name__ == "__main__":
    sys.exit(0 if run_pipeline() else 1)
