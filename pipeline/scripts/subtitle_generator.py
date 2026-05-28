"""
STEP 7 — Subtitle Generation

Reads subtitle_lines directly from master timeline — no re-estimation.
Writes one SRT file per scene to temp/subtitles/sub_{scene_id}.srt.

Shorts profile: MarginV is set to 75% of frame height from top so captions
land in the clear zone between the top UI bar and the bottom overlay buttons
(like/share/subscribe). Standard profile keeps captions at the bottom.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _ms_to_srt(ms: int) -> str:
    h,  ms = divmod(ms, 3_600_000)
    m,  ms = divmod(ms,    60_000)
    s,  ms = divmod(ms,     1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_subtitles(timeline: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    video_end_ms = timeline["total_duration_ms"]
    profile      = timeline.get("profile", "standard")
    H            = timeline.get("height", 1080)

    # Shorts: place captions at 75% from top (clear of bottom UI overlay)
    # Standard: place captions near bottom with safe margin
    if profile == "shorts":
        margin_v = int(H * 0.75)
    else:
        margin_v = max(60, int(H * 0.06))

    for sc in timeline["scenes"]:
        path = out_dir / f"sub_{sc['scene_id']}.srt"

        if sc["segment_label"] == "CLOSE" or not sc.get("subtitle_lines"):
            path.write_text("", encoding="utf-8")
            continue

        lines  = sc["subtitle_lines"]
        sc_end = sc["end_ms"]
        srt: list[str] = []

        for idx, ln in enumerate(lines, start=1):
            start_ms = ln["start_ms"]
            end_ms   = min(ln["end_ms"], sc_end, video_end_ms)
            dur      = end_ms - start_ms

            if dur < 300:
                end_ms = start_ms + 300

            srt += [
                str(idx),
                f"{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}",
                ln["text"],
                "",
            ]

        path.write_text("\n".join(srt), encoding="utf-8")
        log.debug("SRT scene %d: %d lines (marginV=%d)", sc["scene_id"], len(lines), margin_v)

    log.info("SRT files written for %d scenes (profile=%s, marginV=%d)",
             len(timeline["scenes"]), profile, margin_v)

    # Store margin_v in timeline so video_assembler can pick it up
    timeline["_subtitle_margin_v"] = margin_v
