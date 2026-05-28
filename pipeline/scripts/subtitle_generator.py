"""
STEP 5 — Subtitle Generation  (moved before scene planning)

Subtitle lines in the timeline carry ABSOLUTE timestamps (position in the
full content timeline).  SRT files written here use RELATIVE timestamps
(scene-start = 0) so the subtitles filter applied to individual scene MP4s
shows text at the correct time within that clip.

Shorts profile: MarginV is placed at 75 % of frame height — clear of
YouTube's bottom-UI overlay (like / share / subscribe buttons).
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _ms_to_srt(ms: int) -> str:
    ms   = max(0, ms)
    h,  ms = divmod(ms, 3_600_000)
    m,  ms = divmod(ms,    60_000)
    s,  ms = divmod(ms,     1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_subtitles(timeline: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = timeline.get("profile", "standard")
    H       = timeline.get("height", 1080)

    if profile == "shorts":
        margin_v = int(H * 0.75)
    else:
        margin_v = max(60, int(H * 0.06))

    for sc in timeline["scenes"]:
        path = out_dir / f"sub_{sc['scene_id']}.srt"

        if sc["segment_label"] == "CLOSE" or not sc.get("subtitle_lines"):
            path.write_text("", encoding="utf-8")
            continue

        lines    = sc["subtitle_lines"]
        sc_start = sc["start_ms"]   # absolute scene start in full timeline
        sc_dur   = sc["duration_ms"]
        srt: list[str] = []

        for idx, ln in enumerate(lines, start=1):
            # Convert absolute timeline timestamps → relative to this scene
            rel_start = max(0, ln["start_ms"] - sc_start)
            rel_end   = min(ln["end_ms"] - sc_start, sc_dur)

            if rel_end <= rel_start:
                continue                     # subtitle falls outside scene window
            if rel_end - rel_start < 300:
                rel_end = rel_start + 300    # enforce minimum display time

            srt += [
                str(idx),
                f"{_ms_to_srt(rel_start)} --> {_ms_to_srt(rel_end)}",
                ln["text"],
                "",
            ]

        path.write_text("\n".join(srt), encoding="utf-8")
        log.debug("SRT scene %d: %d lines (relative, marginV=%d)",
                  sc["scene_id"], len(lines), margin_v)

    log.info("SRT files written for %d scenes (profile=%s, marginV=%d)",
             len(timeline["scenes"]), profile, margin_v)

    timeline["_subtitle_margin_v"] = margin_v
