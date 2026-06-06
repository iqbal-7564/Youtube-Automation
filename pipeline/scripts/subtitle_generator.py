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

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _auto_font_adjust() -> int:
    try:
        p = Path(__file__).parent.parent / "logs" / "auto_fixes.json"
        if p.exists():
            return int(json.loads(p.read_text()).get("subtitle_font_adjust", 0))
    except Exception:
        pass
    return 0


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

    Subtitle timing is rebuilt from the actual locked voice window per scene
    (sc["start_ms"] → sc["end_ms"] - pad_ms) rather than from rescaled
    subtitle_lines timestamps, which eliminates accumulated rounding drift
    and guarantees subtitles are perfectly in sync with the voice audio.

    Words are chunked into groups of 4 and distributed evenly across the
    speech window. Each word highlights (\\kf fill) as the narrator speaks it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    profile   = timeline.get("profile", "standard")
    W         = timeline.get("width",  1920)
    H         = timeline.get("height", 1080)
    is_shorts = profile == "shorts"

    font_size  = (84 if is_shorts else 42) + _auto_font_adjust()
    # Kinetic Shorts: center screen (\an5). Standard: bottom (\an2, 80px margin)
    margin_v   = 0  if is_shorts else 80
    align_tag  = r"\an5" if is_shorts else r"\an2"
    fade_tag   = r"\fad(60,60)"  if is_shorts else r"\fad(150,150)"
    chunk_size = 2 if is_shorts else 4
    secondary  = "&H0000FFFF"   # yellow karaoke highlight — &HAABBGGRR

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
        f"Style: Default,Arial,{font_size},&H00FFFFFF,{secondary},"
        f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    events: list[str] = []
    for sc in timeline["scenes"]:
        if sc["segment_label"] == "CLOSE":
            continue

        # Rebuild timing from the actual locked voice window — not from
        # rescaled subtitle_lines which carry accumulated rounding errors.
        pad_ms       = sc.get("_voice_pad_ms", 300)
        speech_start = sc["start_ms"]
        speech_end   = max(speech_start + 500, sc["end_ms"] - pad_ms)
        speech_dur   = speech_end - speech_start

        # Collect all words from this scene's script text
        all_text = sc.get("script_text", "").strip()
        if not all_text:
            continue
        words = all_text.split()
        if not words:
            continue

        # Chunk into groups (2 words for kinetic Shorts, 4 for standard)
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        n      = len(chunks)
        ms_per = speech_dur // n

        for i, chunk in enumerate(chunks):
            c_start = speech_start + i * ms_per
            c_end   = (speech_start + (i + 1) * ms_per) if i < n - 1 else speech_end
            c_end   = max(c_end, c_start + 200)   # 200ms min for fast 2-word flashes

            dur_cs  = max(len(chunk), (c_end - c_start) // 10)
            base_cs = dur_cs // len(chunk)
            extra   = dur_cs - base_cs * len(chunk)

            karaoke = ""
            for j, word in enumerate(chunk):
                display = word.upper() if is_shorts else word
                wcs = base_cs + (1 if j < extra else 0)
                karaoke += f"{{\\kf{wcs}}}{display} "

            s = _ms_to_ass(c_start)
            e = _ms_to_ass(c_end)
            events.append(
                f"Dialogue: 0,{s},{e},Default,,0,0,0,,"
                f"{{{align_tag}{fade_tag}}}{karaoke.strip()}"
            )

    ass_path = out_dir / "full_video.ass"
    ass_path.write_text(header + "\n" + "\n".join(events), encoding="utf-8")
    log.info("ASS subtitles: %d dialogue lines → %s", len(events), ass_path.name)
    return ass_path
