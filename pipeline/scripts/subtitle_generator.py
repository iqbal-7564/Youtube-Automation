"""
STEP 5 — Subtitle Generation  (moved before scene planning)

Subtitle lines in the timeline carry ABSOLUTE timestamps (position in the
full content timeline).  SRT files written here use RELATIVE timestamps
(scene-start = 0) so the subtitles filter applied to individual scene MP4s
shows text at the correct time within that clip.

Shorts profile: MarginV is placed at 75 % of frame height — clear of
YouTube's bottom-UI overlay (like / share / subscribe buttons).

generate_ass_subtitles() produces a single full-video ASS file with
karaoke word-fill timing (\\kf) so each word lights up as it is spoken.
The ASS file is burned into the final MP4 by the encoder (step 10).
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


def _ms_to_ass(ms: int) -> str:
    ms = max(0, ms)
    h,  ms = divmod(ms, 3_600_000)
    m,  ms = divmod(ms,    60_000)
    s,  ms = divmod(ms,     1_000)
    cs = ms // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


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

        written = 0
        skipped = 0
        for idx, ln in enumerate(lines, start=1):
            # Convert absolute timeline timestamps → relative to this scene
            rel_start = max(0, ln["start_ms"] - sc_start)
            rel_end   = min(ln["end_ms"] - sc_start, sc_dur)

            if rel_end <= rel_start:
                skipped += 1
                continue                     # subtitle falls outside scene window
            if rel_end - rel_start < 300:
                rel_end = rel_start + 300    # enforce minimum display time

            srt += [
                str(written + 1),
                f"{_ms_to_srt(rel_start)} --> {_ms_to_srt(rel_end)}",
                ln["text"],
                "",
            ]
            written += 1

        if skipped:
            log.warning("Scene %d: %d/%d subtitle line(s) fell outside scene window "
                        "— voice/subtitle mismatch detected",
                        sc["scene_id"], skipped, len(lines))

        path.write_text("\n".join(srt), encoding="utf-8")
        log.debug("SRT scene %d: %d lines written, %d skipped (marginV=%d)",
                  sc["scene_id"], written, skipped, margin_v)

    log.info("SRT files written for %d scenes (profile=%s, marginV=%d)",
             len(timeline["scenes"]), profile, margin_v)

    timeline["_subtitle_margin_v"] = margin_v


def generate_ass_subtitles(timeline: dict, out_dir: Path) -> Path:
    """Generate a single full-video ASS file with karaoke word-fill animation.

    Each subtitle line is split into words; timing is distributed evenly so
    each word highlights (\\kf fill) as the narrator speaks it.  The resulting
    .ass file is passed to the encoder to be burned into the final MP4.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    profile  = timeline.get("profile", "standard")
    W        = timeline.get("width",  1920)
    H        = timeline.get("height", 1080)
    is_shorts = profile == "shorts"

    font_size = 52 if is_shorts else 42
    margin_v  = 200 if is_shorts else 80
    # ASS colours are &HAABBGGRR (AA=alpha 00=opaque FF=transparent)
    secondary = "&H0000FFFF"   # yellow karaoke highlight

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Bold, BorderStyle=1 (outline+shadow), Outline=3, Alignment=2 (bottom-centre)
        f"Style: Default,Arial,{font_size},&H00FFFFFF,{secondary},"
        f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    events: list[str] = []
    for sc in timeline["scenes"]:
        if sc["segment_label"] == "CLOSE" or not sc.get("subtitle_lines"):
            continue
        for ln in sc.get("subtitle_lines", []):
            text = ln["text"].strip()
            if not text:
                continue
            start_ms = ln["start_ms"]
            end_ms   = ln["end_ms"]
            words    = text.split()
            if not words:
                continue
            # Distribute duration evenly across words (in centiseconds)
            total_cs = max(len(words), (end_ms - start_ms) // 10)
            base_cs  = total_cs // len(words)
            extra_cs = total_cs - base_cs * len(words)
            karaoke  = ""
            for i, word in enumerate(words):
                wcs = base_cs + (1 if i < extra_cs else 0)
                karaoke += f"{{\\kf{wcs}}}{word} "
            s = _ms_to_ass(start_ms)
            e = _ms_to_ass(end_ms)
            # \an2 = bottom-centre anchor; \fad = fade in/out 150ms
            events.append(
                f"Dialogue: 0,{s},{e},Default,,0,0,0,,{{\\an2\\fad(150,150)}}{karaoke.strip()}"
            )

    ass_path = out_dir / "full_video.ass"
    ass_path.write_text(header + "\n" + "\n".join(events), encoding="utf-8")
    log.info("ASS subtitles: %d dialogue lines → %s", len(events), ass_path.name)
    return ass_path
