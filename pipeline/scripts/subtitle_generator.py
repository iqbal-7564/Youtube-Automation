"""
STEP 7 — Subtitle Generation

Reads subtitle_lines directly from master timeline — no re-estimation.
Writes one SRT file per scene to temp/subtitles/sub_{scene_id}.srt.
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

    for sc in timeline["scenes"]:
        path = out_dir / f"sub_{sc['scene_id']}.srt"

        if sc["segment_label"] == "CLOSE" or not sc.get("subtitle_lines"):
            path.write_text("", encoding="utf-8")
            continue

        lines   = sc["subtitle_lines"]
        sc_end  = sc["end_ms"]
        srt: list[str] = []

        for idx, ln in enumerate(lines, start=1):
            start_ms = ln["start_ms"]
            end_ms   = min(ln["end_ms"], sc_end, video_end_ms)
            dur      = end_ms - start_ms

            # Enforce min 300 ms display time
            if dur < 300:
                end_ms = start_ms + 300

            srt += [
                str(idx),
                f"{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}",
                ln["text"],
                "",
            ]

        path.write_text("\n".join(srt), encoding="utf-8")
        log.debug("SRT scene %d: %d lines", sc["scene_id"], len(lines))

    log.info("SRT files written for %d scenes", len(timeline["scenes"]))
