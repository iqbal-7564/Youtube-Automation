"""
STEP 13 — Analytics

Phase 1 (active): Logs per-video result to pipeline/logs/video_results.json.

Phase 2 (passive — run separately after 30 days of data):
  Polls YouTube Analytics API, stores metrics, computes per-category
  performance weights written to performance_history.json.
  topic_selector.py reads these weights to prioritise well-performing categories.

Feedback signals used:
  avg_view_pct < 40%  → shorten hook
  avg_view_pct > 70%  → lock current script structure
  retention_drop < 8s → TENSION segment not working
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def log_result(
    video_id: str,
    topic: dict,
    timeline: dict,
    gate: dict,
    profile: str,
    logs_dir: Path,
) -> None:
    path    = logs_dir / "video_results.json"
    results = json.loads(path.read_text()) if path.exists() else []

    scores = [sc.get("clip_score", 0.0) for sc in timeline["scenes"]
              if sc.get("clip_score", 0) > 0]
    avg_clip = round(sum(scores) / len(scores), 3) if scores else 0.0

    hook_text = next(
        (sc["script_text"] for sc in timeline["scenes"]
         if sc["segment_label"] == "HOOK"),
        "",
    )

    engines = list({sc.get("tts_engine", "") for sc in timeline["scenes"]} - {""})

    results.append({
        "video_id":               video_id,
        "intent":                 topic["intent"],
        "title":                  topic["title"][:100],
        "hook_text":              hook_text[:120],
        "total_duration_seconds": timeline["total_duration_seconds"],
        "scene_count":            len(timeline["scenes"]),
        "avg_clip_score":         avg_clip,
        "quality_gate_passed":    gate["passed"],
        "uploaded_at":            datetime.utcnow().isoformat(),
        "profile":                profile,
        "tts_engines":            engines,
    })

    path.write_text(json.dumps(results[-200:], indent=2, ensure_ascii=False))
    log.info("  Logged result for video_id=%s", video_id)


# ── Phase 2: YouTube Analytics polling ────────────────────────────────────────

def fetch_analytics_feedback(logs_dir: Path) -> dict:
    """
    Polls YouTube Analytics for recent videos.
    Updates video_results.json with metrics.
    Writes performance_history.json keyed by category.
    Returns feedback hints for script_generator.
    """
    results_path = logs_dir / "video_results.json"
    data_path    = logs_dir / "analytics_data.json"
    perf_path    = logs_dir / "performance_history.json"

    if not results_path.exists():
        return {}

    results = json.loads(results_path.read_text())
    if not results:
        return {}

    token = _token()
    if not token:
        log.warning("Analytics: could not get token")
        return {}

    updated: list[dict] = []
    for entry in results[-30:]:
        vid = entry.get("video_id")
        if not vid or entry.get("analytics_fetched"):
            continue
        stats = _fetch_stats(vid, token)
        if stats:
            entry.update(stats)
            # Fetch scene-level retention curve
            curve = _fetch_retention_curve(vid, token)
            if curve:
                # We don't have the full timeline here — store raw curve for
                # external analysis; scene mapping requires timeline context
                entry["retention_curve_points"] = len(curve)
                entry["retention_at_25pct"] = next(
                    (p["watch_ratio"] * 100 for p in curve
                     if abs(p["ratio"] - 0.25) < 0.05), None)
                entry["retention_at_50pct"] = next(
                    (p["watch_ratio"] * 100 for p in curve
                     if abs(p["ratio"] - 0.50) < 0.05), None)
                entry["retention_at_75pct"] = next(
                    (p["watch_ratio"] * 100 for p in curve
                     if abs(p["ratio"] - 0.75) < 0.05), None)
                # Find the biggest single drop-off point
                if len(curve) >= 2:
                    drops = [
                        (curve[i]["ratio"],
                         curve[i - 1]["watch_ratio"] - curve[i]["watch_ratio"])
                        for i in range(1, len(curve))
                    ]
                    worst = max(drops, key=lambda d: d[1])
                    entry["biggest_drop_at_pct"] = round(worst[0] * 100, 1)
                    entry["biggest_drop_size"]   = round(worst[1] * 100, 2)
                    if worst[1] > 0.05:
                        log.info("  Retention: biggest drop at %.0f%% of video (%s)",
                                 worst[0] * 100, vid)
            entry["analytics_fetched"] = True
            updated.append(entry)

    if updated:
        existing = json.loads(data_path.read_text()) if data_path.exists() else []
        existing.extend(updated)
        data_path.write_text(json.dumps(existing[-500:], indent=2))
        results_path.write_text(json.dumps(results[-200:], indent=2))
        log.info("Analytics updated for %d videos", len(updated))

    hints = _feedback_hints(results)
    _write_performance_history(results, perf_path)
    return hints


def _fetch_retention_curve(video_id: str, token: str) -> list[dict]:
    """
    Fetch the audience retention curve (elapsedVideoTimeRatio vs audienceWatchRatio).
    Returns list of {ratio: float, watch_ratio: float} sorted by ratio.
    Empty list if unavailable.
    """
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "ids":        "channel==MINE",
                "dimensions": "elapsedVideoTimeRatio",
                "filters":    f"video=={video_id}",
                "metrics":    "audienceWatchRatio",
                "startDate":  "2020-01-01",
                "endDate":    today,
            },
            timeout=15,
        )
        if r.ok:
            rows = r.json().get("rows", [])
            return [{"ratio": float(row[0]), "watch_ratio": float(row[1])}
                    for row in rows if len(row) >= 2]
    except Exception as exc:
        log.debug("Retention curve %s: %s", video_id, exc)
    return []


def _analyze_scene_retention(curve: list[dict], timeline: dict) -> dict:
    """
    Map audience retention curve to per-scene retention percentages.
    Returns {scene_id: avg_retention_pct, ..., "drop_scenes": [scene_ids]}.
    """
    if not curve or not timeline.get("scenes"):
        return {}

    total_ms = timeline["total_duration_ms"]
    result: dict[str, object] = {}
    drop_scenes: list[int] = []

    for sc in timeline["scenes"]:
        start_r = sc["start_ms"] / total_ms
        end_r   = sc["end_ms"]   / total_ms
        # Average audienceWatchRatio for points within this scene's window
        pts = [p["watch_ratio"] for p in curve
               if start_r <= p["ratio"] < end_r]
        if pts:
            avg = round(sum(pts) / len(pts) * 100, 1)
            result[str(sc["scene_id"])] = avg
            # Flag scenes with retention < 70% as drop points
            if avg < 70.0:
                drop_scenes.append(sc["scene_id"])

    result["drop_scenes"] = drop_scenes
    return result


def _fetch_stats(video_id: str, token: str) -> dict:
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "ids":        "channel==MINE",
                "dimensions": "video",
                "filters":    f"video=={video_id}",
                "metrics":    "views,averageViewDuration,averageViewPercentage,likes",
                "startDate":  "2020-01-01",
                "endDate":    today,
            },
            timeout=15,
        )
        if r.ok:
            rows = r.json().get("rows", [])
            if rows:
                row = rows[0]
                return {
                    "views_48h":    int(row[1]) if len(row) > 1 else 0,
                    "avg_view_pct": float(row[3]) if len(row) > 3 else 0.0,
                    "likes":        int(row[4]) if len(row) > 4 else 0,
                }
    except Exception as exc:
        log.debug("Analytics fetch %s: %s", video_id, exc)
    return {}


def _feedback_hints(results: list) -> dict:
    recent = [r for r in results if r.get("avg_view_pct") is not None][-5:]
    if not recent:
        return {}

    avg_ret = sum(r["avg_view_pct"] for r in recent) / len(recent)
    hints: dict = {"avg_retention_pct": round(avg_ret, 1)}

    if avg_ret < 40:
        hints["hook_adjustment"] = "shorten_hook"
        hints["hook_note"]       = "hook not retaining viewers — shorten by 1s"
    elif avg_ret > 70:
        hints["template_lock"] = True
        hints["template_note"] = "script structure performing well — keep"

    # Retention curve signals
    curve_recent = [r for r in recent if r.get("biggest_drop_at_pct") is not None]
    if curve_recent:
        avg_drop_pos = sum(r["biggest_drop_at_pct"] for r in curve_recent) / len(curve_recent)
        hints["avg_biggest_drop_at_pct"] = round(avg_drop_pos, 1)
        if avg_drop_pos < 25:
            hints["retention_signal"] = "early_drop"
            hints["retention_note"]   = "viewers leave in first 25% — hook or TENSION too slow"
        elif avg_drop_pos < 50:
            hints["retention_signal"] = "mid_drop"
            hints["retention_note"]   = "viewers leave mid-video — CORE is losing them"
        else:
            hints["retention_signal"] = "late_drop"
            hints["retention_note"]   = "good early retention — PAYOFF or CLOSE is weak"

    return hints


def _write_performance_history(results: list, perf_path: Path) -> None:
    """Aggregate avg_view_pct by category and write performance_history.json."""
    by_cat: dict[str, list[float]] = {}
    for r in results:
        cat = r.get("intent", "")
        pct = r.get("avg_view_pct")
        if cat and pct is not None:
            by_cat.setdefault(cat, []).append(float(pct))

    history: dict[str, dict] = {}
    existing = json.loads(perf_path.read_text()) if perf_path.exists() else {}
    history.update(existing)

    for cat, vals in by_cat.items():
        if not vals:
            continue
        avg = round(sum(vals) / len(vals), 2)
        history[cat] = {
            "avg_retention_pct": avg,
            "sample_count":      len(vals),
            "updated_at":        datetime.utcnow().isoformat(),
        }

    perf_path.write_text(json.dumps(history, indent=2))
    log.info("Performance history updated for %d categories", len(history))


def _token() -> str | None:
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":     os.environ.get("YOUTUBE_CLIENT_ID"),
                "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET"),
                "refresh_token": os.environ.get("YOUTUBE_REFRESH_TOKEN"),
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        return r.json().get("access_token")
    except Exception:
        return None
