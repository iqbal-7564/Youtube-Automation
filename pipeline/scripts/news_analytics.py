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
import re
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


# Schema: (type, min, max, default)
_ADAPTIVE_SCHEMA: dict[str, tuple] = {
    "hook_cap_ms":        (int,   500,  3000, 2500),
    "tension_interval_s": (float, 1.0,  8.0,  4.5),
    "core_interval_s":    (float, 1.0,  8.0,  3.5),
}


def _validate_adaptive_params(params: dict) -> dict:
    """Return params with invalid/missing keys replaced by defaults."""
    for key, (typ, lo, hi, default) in _ADAPTIVE_SCHEMA.items():
        val = params.get(key)
        if val is None or not isinstance(val, (int, float)) or not (lo <= val <= hi):
            if val is not None:
                log.warning("adaptive_params[%s]=%r invalid — using default %s",
                            key, val, default)
            params[key] = default
    return params


def _save_adaptive_params(params: dict, path) -> None:
    """Atomic write: write to .tmp then rename to prevent partial-write corruption."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(params, indent=2))
    tmp.replace(path)


def _load_adaptive_params(path) -> dict:
    defaults = {k: v[3] for k, v in _ADAPTIVE_SCHEMA.items()}
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text())
        return _validate_adaptive_params(raw)
    except json.JSONDecodeError:
        log.error("adaptive_params.json is corrupt — using defaults")
        return defaults


def apply_adaptive_learning(hints: dict, logs_dir: Path) -> dict:
    """
    Translate retention signals into concrete parameter adjustments.
    Writes adaptive_params.json which timeline_builder and script_generator
    read on the next run to automatically evolve their behaviour.

    Parameters are adjusted conservatively (small steps) so the system
    doesn't over-correct on a single bad video.
    """
    params_path = logs_dir / "adaptive_params.json"
    params: dict = _load_adaptive_params(params_path)

    signal = hints.get("retention_signal")
    avg_ret = hints.get("avg_retention_pct", 50.0)

    if signal == "early_drop":
        # Viewers leave in first 25% — hook/tension is too slow or dull
        params["hook_cap_ms"]       = max(1500, params.get("hook_cap_ms", 2500) - 150)
        params["tension_interval_s"]= max(3.0,  params.get("tension_interval_s", 4.5) - 0.3)
        params["hook_note"]         = "auto-shortened hook and tension intervals"
        log.info("Adaptive: early_drop — tightened hook cap to %dms", params["hook_cap_ms"])

    elif signal == "mid_drop":
        # Viewers leave in CORE — scenes too long, pacing too slow
        params["core_interval_s"]   = max(2.5, params.get("core_interval_s", 3.5) - 0.25)
        params["core_note"]         = "auto-shortened CORE scene intervals"
        log.info("Adaptive: mid_drop — CORE interval reduced to %.2fs", params["core_interval_s"])

    elif signal == "late_drop":
        # Good early retention but PAYOFF/CLOSE is weak
        params["payoff_tighten"]    = True
        params["late_note"]         = "auto-flag: PAYOFF/CLOSE structure needs work"
        log.info("Adaptive: late_drop — flagged PAYOFF/CLOSE for review")

    if avg_ret > 70:
        # System is working — lock current parameters
        params["template_lock"] = True
        params["lock_note"]     = "retention above 70% — preserving current parameters"
        log.info("Adaptive: high retention %.1f%% — parameters locked", avg_ret)
    elif avg_ret <= 70 and params.get("template_lock"):
        # Performance dropped below threshold — release the parameter lock
        params.pop("template_lock", None)
        params.pop("lock_note", None)
        log.info("Adaptive: retention dropped to %.1f%% — parameter lock released", avg_ret)

    params["updated_at"] = datetime.utcnow().isoformat()
    params["last_signal"] = signal or "none"
    params["last_avg_retention"] = avg_ret

    _save_adaptive_params(params, params_path)
    log.info("Adaptive params written to %s", params_path.name)
    return params


def predict_retention_risk(timeline: dict) -> dict:
    """
    Pre-render retention risk scoring — estimates likely drop-off points
    BEFORE the video is published, based on scene complexity and emotional arc.

    Returns {risk_score: 0.0-1.0, weak_scenes: [...], recommendations: [...]}

    Risk factors per scene:
      - High complexity in short scene: viewer overwhelmed → leaves
      - Consecutive same-emotion scenes: emotional monotony → boredom
      - Long CORE scenes without WOW markers: attention decay
      - Sudden emotion drop after peak: jarring, breaks flow
    """
    scenes  = timeline.get("scenes", [])
    if not scenes:
        return {"risk_score": 0.0, "weak_scenes": [], "recommendations": []}

    total_risk  = 0.0
    weak_scenes = []
    recs        = []
    prev_emotion = None
    consecutive_neutral = 0

    for sc in scenes:
        label      = sc.get("segment_label", "CORE")
        complexity = sc.get("complexity", "simple")
        emotion    = sc.get("emotion", "neutral")
        dur_ms     = sc.get("duration_ms", 3000)
        has_wow    = sc.get("has_wow", False)
        scene_id   = sc["scene_id"]
        scene_risk = 0.0

        # Risk 1: complex scene too short (viewer can't absorb it)
        if complexity == "complex" and dur_ms < 3500:
            scene_risk += 0.15
            weak_scenes.append({"scene": scene_id, "reason": "complex content, scene too short"})

        # Risk 2: emotional monotony (3+ consecutive neutral scenes)
        if emotion == "neutral":
            consecutive_neutral += 1
        else:
            consecutive_neutral = 0
        if consecutive_neutral >= 3:
            scene_risk += 0.20
            if scene_id not in [w["scene"] for w in weak_scenes]:
                weak_scenes.append({"scene": scene_id, "reason": "emotional monotony — 3+ neutral scenes"})

        # Risk 3: long CORE scene without WOW marker
        if label == "CORE" and dur_ms > 6000 and not has_wow:
            scene_risk += 0.18
            weak_scenes.append({"scene": scene_id, "reason": "long CORE scene, no WOW spike"})

        # Risk 4: sudden drop from dramatic/excited → neutral
        if prev_emotion in ("dramatic", "excited") and emotion == "neutral":
            scene_risk += 0.10

        total_risk  += scene_risk
        prev_emotion = emotion

    # Normalise: risk per scene averaged
    avg_risk = min(total_risk / max(len(scenes), 1), 1.0)

    # Generate recommendations
    if avg_risk > 0.4:
        recs.append("High retention risk — consider shortening complex CORE scenes")
    if consecutive_neutral >= 3:
        recs.append("Too many consecutive neutral-emotion scenes — inject dramatic or excited scene")
    wow_count = sum(1 for sc in scenes if sc.get("has_wow"))
    if wow_count == 0:
        recs.append("No WOW-marked moments — script may lack a clear peak surprise")
    if wow_count > 2:
        recs.append("Multiple WOW markers — ensure they are spaced, not clustered")

    return {
        "risk_score":      round(avg_risk, 3),
        "weak_scenes":     weak_scenes[:5],
        "recommendations": recs,
        "wow_count":       wow_count,
    }


def _write_performance_history(results: list, perf_path: Path) -> None:
    """Aggregate avg_view_pct by category AND sub-topic seed, write both history files."""
    by_cat:     dict[str, list[float]] = {}
    by_subtopic: dict[str, list[float]] = {}

    for r in results:
        cat  = r.get("intent", "")
        pct  = r.get("avg_view_pct")
        seed = r.get("seed", "")
        if cat and pct is not None:
            by_cat.setdefault(cat, []).append(float(pct))
        if seed and pct is not None:
            import re as _re
            key = _re.sub(r"[^a-z0-9]", "_", seed.lower().strip())[:40]
            by_subtopic.setdefault(key, []).append(float(pct))

    # Category-level history
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

    # Sub-topic level history
    subtopic_path = perf_path.parent / "subtopic_history.json"
    sub_existing: dict[str, dict] = {}
    if subtopic_path.exists():
        try:
            sub_existing = json.loads(subtopic_path.read_text())
        except Exception:
            pass
    for key, vals in by_subtopic.items():
        if not vals:
            continue
        avg = round(sum(vals) / len(vals), 2)
        sub_existing[key] = {
            "avg_retention_pct": avg,
            "sample_count":      len(vals),
            "updated_at":        datetime.utcnow().isoformat(),
        }
    subtopic_path.write_text(json.dumps(sub_existing, indent=2))
    log.info("Sub-topic history updated for %d seeds", len(by_subtopic))


# ── Publish Time Algorithm ────────────────────────────────────────────────────

def fetch_peak_hours(logs_dir: Path) -> dict:
    """
    Fetches hourly view distribution from YouTube Analytics (last 28 days).
    Identifies the top 3 peak hours (UTC) and writes peak_hours.json.
    main.py reads this to align uploads to peak audience windows.
    """
    token = _token()
    if not token:
        return {}

    try:
        from datetime import timedelta
        today = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d")

        r = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "ids":        "channel==MINE",
                "dimensions": "hour",
                "metrics":    "views",
                "startDate":  start,
                "endDate":    today,
            },
            timeout=15,
        )
        if not r.ok:
            log.debug("Peak hours API: HTTP %d", r.status_code)
            return {}

        rows = r.json().get("rows", [])
        if not rows:
            return {}

        hourly       = {int(row[0]): int(row[1]) for row in rows if len(row) >= 2}
        sorted_hours = sorted(hourly.items(), key=lambda x: x[1], reverse=True)
        peak_hours   = sorted([h for h, _ in sorted_hours[:3]])

        data = {
            "peak_hours":   peak_hours,
            "hourly_views": hourly,
            "updated_at":   datetime.utcnow().isoformat(),
        }
        (logs_dir / "peak_hours.json").write_text(json.dumps(data, indent=2))
        log.info("Peak hours (UTC): %s", peak_hours)
        return data

    except Exception as exc:
        log.debug("Peak hours fetch: %s", exc)
        return {}


# ── Topic Velocity Clustering ─────────────────────────────────────────────────

def update_velocity_queue(logs_dir: Path) -> None:
    """
    Checks recent video 48h performance against channel average.
    When a video exceeds 2x the average, generates 3-4 related topic seeds
    and writes them to velocity_queue.json for the next pipeline run.
    topic_selector.py reads this queue with highest priority.
    """
    results_path = logs_dir / "video_results.json"
    queue_path   = logs_dir / "velocity_queue.json"

    if not results_path.exists():
        return

    results    = json.loads(results_path.read_text())
    views_list = [r.get("views_48h", 0) for r in results if r.get("views_48h", 0) > 0]

    if len(views_list) < 3:
        log.info("Velocity check: not enough analytics data yet (%d videos)", len(views_list))
        return

    avg_views = sum(views_list) / len(views_list)
    threshold = avg_views * 2.0

    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=72)).isoformat()

    hot = [
        r for r in results
        if r.get("uploaded_at", "") >= cutoff
        and r.get("views_48h", 0) >= threshold
        and not r.get("velocity_queued")
    ]

    if not hot:
        log.info("Velocity check: no hot videos (avg=%.0f, threshold=%.0f)", avg_views, threshold)
        return

    now    = datetime.utcnow()
    cutoff = now.timestamp() - 72 * 3600

    existing = json.loads(queue_path.read_text()) if queue_path.exists() else []
    # Evict stale entries (72h TTL) before appending new seeds
    queue = [
        e for e in existing
        if e.get("ts", cutoff + 1) >= cutoff
    ]

    for video in hot:
        cat   = video.get("intent", "SCIENCE")
        title = video.get("title", "")
        ratio = video["views_48h"] / avg_views
        log.info("Velocity HIT [%s] '%.50s' — %.0f views (%.1fx avg)",
                 cat, title, video["views_48h"], ratio)

        related = _generate_related_seeds(cat, title)
        for seed in related:
            queue.append({
                "category":     cat,
                "seed":         seed,
                "source_title": title[:80],
                "source_views": int(video["views_48h"]),
                "queued_at":    now.isoformat(),
                "ts":           now.timestamp(),
                "priority":     "high",
            })

        # Build topic cluster chain from viral video for returning viewers
        _build_topic_cluster(cat, title, logs_dir)
        video["velocity_queued"] = True

    queue_path.write_text(json.dumps(queue[-50:], indent=2))
    results_path.write_text(json.dumps(results[-200:], indent=2))
    log.info("Velocity queue: %d hot videos → %d seeds queued", len(hot), len(queue))


def _build_topic_cluster(category: str, source_title: str, logs_dir: Path) -> None:
    """
    When a video hits 2x average views, generate a 4-video cluster chain
    and store it in topic_clusters.json.
    Chain example: Ancient Egypt → Pyramids → Lost Technology → Hidden Chambers
    """
    keys = [os.environ.get("GROQ_API_KEY_1", "").strip(),
            os.environ.get("GROQ_API_KEY_2", "").strip()]
    for key in keys:
        if not key:
            continue
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{
                        "role": "system",
                        "content": (
                            "You generate topic cluster chains for YouTube content. "
                            "Return ONLY a JSON array of 4 topic strings in sequence order. "
                            "Each topic should naturally follow from the previous, building "
                            "viewer curiosity across a series."
                        ),
                    }, {
                        "role": "user",
                        "content": (
                            f"Category: {category}\n"
                            f"Viral video: {source_title}\n"
                            "Generate a 4-topic cluster chain. Start from the viral topic "
                            "and create 3 follow-up topics that deepen the story naturally."
                        ),
                    }],
                    "temperature": 0.7,
                    "max_tokens": 200,
                },
                timeout=15,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    chain = json.loads(m.group())
                    if isinstance(chain, list) and len(chain) >= 2:
                        clusters_path = logs_dir / "topic_clusters.json"
                        existing = json.loads(clusters_path.read_text()) if clusters_path.exists() else []
                        existing.append({
                            "category":     category,
                            "source_title": source_title[:80],
                            "chain":        [str(t) for t in chain[:4]],
                            "current_idx":  0,
                            "created_at":   datetime.utcnow().isoformat(),
                        })
                        clusters_path.write_text(json.dumps(existing[-20:], indent=2))
                        log.info("Topic cluster created for '%s': %s",
                                 source_title[:40], chain[:4])
                        return
        except Exception as exc:
            log.debug("Topic cluster generation: %s", exc)


def _generate_related_seeds(category: str, source_title: str) -> list[str]:
    """Uses Groq to generate 4 related topic seeds from a hot video's title."""
    keys = [os.environ.get("GROQ_API_KEY_1", "").strip(),
            os.environ.get("GROQ_API_KEY_2", "").strip()]
    for key in keys:
        if not key:
            continue
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{
                        "role": "system",
                        "content": (
                            "You generate related YouTube topic seeds. "
                            "Return ONLY a JSON array of 4 short topic phrases (5-10 words each). "
                            "Each must be closely related but NOT identical to the source. "
                            'Example: ["neutron stars collapse explained", "dark matter mystery revealed"]'
                        ),
                    }, {
                        "role": "user",
                        "content": (
                            f"Category: {category}\n"
                            f"Hot video: {source_title}\n"
                            "Generate 4 related seeds that would appeal to the same audience."
                        ),
                    }],
                    "temperature": 0.8,
                    "max_tokens":  200,
                },
                timeout=15,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    seeds = json.loads(m.group())
                    if isinstance(seeds, list):
                        return [str(s) for s in seeds[:4] if s]
        except Exception as exc:
            log.debug("Related seeds: %s", exc)
    return []


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
