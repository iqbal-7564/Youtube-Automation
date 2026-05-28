"""
STEP 7 — Video Assembly (FFmpeg)

Per-scene rendering (visual + brand overlays) → individual MP4s
Then concat with transitions → assembled_video.mp4 (video-only, no audio).

Assembly duration == timeline total (locked after voice generation).
No pre-roll / hook-card / end-card extras are added here — those would
push assembly duration past the locked timeline value and break the
encoder cap.  Subtitles are NOT burned in; they are generated separately
(step 8) and uploaded as a YouTube caption track.

Scene visual clips are stream-looped (-stream_loop -1) so a short downloaded
clip always fills the full scene duration without truncating the assembly.

Transitions:
  • Shorts              → always cut
  • Same-section scenes → 0.3 s cross-dissolve
  • CORE→PAYOFF         → 0.5 s fade-to-black
  • PAYOFF→CLOSE        → 0.3 s fade-to-black

Brand overlays (all non-CLOSE scenes):
  TOP-LEFT    : "VM" pill
  BOTTOM-LEFT : channel name
  TOP-RIGHT   : intent label pill
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_CHANNEL  = "MindBlownFacts"
_TAGLINE  = "Discover Your World"

_INTENT_COLOR = {
    "SPACE":     "0x1A0A6B", "SCIENCE":   "0x0055AA",
    "HISTORY":   "0x6B3A00", "ANIMALS":   "0x1A5C00",
    "NATURE":    "0x005C1A", "GEOGRAPHY": "0x006666",
    "OCEAN":     "0x004080", "CULTURE":   "0x7A3500",
}
_INTENT_LABEL = {k: k for k in _INTENT_COLOR}

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def assemble_video(timeline: dict, temp_dir: Path, intent: str) -> Path:
    visuals_dir = temp_dir / "visuals"
    scenes_dir  = temp_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    W, H      = timeline["width"], timeline["height"]
    profile   = timeline["profile"]
    is_shorts = profile == "shorts"

    i_upper = intent.upper()
    i_label = _INTENT_LABEL.get(i_upper, "FACTS")
    i_color = _INTENT_COLOR.get(i_upper, "0x0055AA")

    scene_outputs: list[tuple[Path, dict]] = []

    for sc in timeline["scenes"]:
        out   = scenes_dir / f"scene_{sc['scene_id']}_output.mp4"
        dur_s = sc["duration_ms"] / 1000          # always from LOCKED timeline
        focus = sc.get("focus_region", "center")

        try:
            if sc.get("clip_type") == "close" or sc.get("visual_keyword") == "CLOSE":
                _render_close(sc, out, W, H, dur_s)
            else:
                vis = visuals_dir / sc.get("visual_file", "_missing")
                _render_scene(vis, out, W, H, dur_s,
                              sc.get("clip_type", "video"),
                              sc["segment_label"],
                              i_label, i_color, focus)
        except Exception as exc:
            log.warning("Scene %d render error: %s — fallback", sc["scene_id"], exc)
            _branded_fill(out, W, H, dur_s, i_label, i_color)

        if not (out.exists() and out.stat().st_size > 500):
            log.warning("Scene %d output missing — fallback", sc["scene_id"])
            _branded_fill(out, W, H, dur_s, i_label, i_color)

        scene_outputs.append((out, sc))

    assembled = temp_dir / "assembled_video.mp4"
    _concat(scene_outputs, assembled, is_shorts)
    return assembled


# ── Per-scene renderers ───────────────────────────────────────────────────────

def _render_scene(vis: Path, out: Path, W: int, H: int,
                  dur_s: float, clip_type: str, seg_label: str,
                  i_label: str, i_color: str, focus: str) -> None:

    vf_parts: list[str] = []

    vf_parts.append(
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1"
    )

    if clip_type == "image":
        frames = max(int(dur_s * 30), 30)
        z_expr, x_expr, y_expr = _ken_burns_expr(focus, seg_label)
        vf_parts.append(
            f"zoompan=z='{z_expr}':d={frames}:"
            f"x='{x_expr}':y='{y_expr}':s={W}x{H}:fps=30"
        )

    # Brand overlays
    vf_parts.append(
        f"drawtext=text='VM':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"box=1:boxcolor=0x1A73E8@0.85:boxborderw=14:x=42:y=42"
    )
    mb = max(60, int(H * 0.05))
    vf_parts.append(
        f"drawtext=text='{_CHANNEL}':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"bordercolor=black:borderw=2:x=42:y=h-{mb}-th"
    )
    vf_parts.append(
        f"drawtext=text=' {i_label} ':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=24:"
        f"box=1:boxcolor={i_color}@0.92:boxborderw=10:x=w-tw-50:y=42"
    )

    vf  = ",".join(vf_parts)
    cmd = _base_cmd(vis, dur_s, clip_type, W, H)
    cmd += ["-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)]
    _run(cmd, f"scene→{out.name}")


def _render_close(sc: dict, out: Path, W: int, H: int, dur_s: float) -> None:
    vf = (
        f"drawtext=text='{_CHANNEL}':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=72:x=(w-tw)/2:y=(h-th)/2-70,"
        f"drawtext=text='{_TAGLINE}':fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.65:fontsize=36:x=(w-tw)/2:y=(h-th)/2+40,"
        f"drawtext=text='Follow for Daily World Facts':fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.75:fontsize=30:x=(w-tw)/2:y=(h-th)/2+100"
    )
    _run(["ffmpeg", "-y",
          "-f", "lavfi", "-i", f"color=c=0x0A0A0A:size={W}x{H}:rate=30",
          "-vf", vf, "-t", str(dur_s),
          "-c:v", "libx264", "-preset", "fast", "-crf", "18",
          "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)],
         f"CLOSE→{out.name}")


def _branded_fill(out: Path, W: int, H: int, dur_s: float,
                  i_label: str, i_color: str) -> None:
    """Branded gradient fill — replaces pure black for visual quality."""
    vf = (
        f"drawtext=text=' {i_label} ':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=36:"
        f"box=1:boxcolor={i_color}@0.70:boxborderw=16:"
        f"x=(w-tw)/2:y=(h-th)/2"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=0x08080F:size={W}x{H}:rate=30",
         "-vf", vf, "-t", str(dur_s),
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)],
        capture_output=True, timeout=30,
    )


# ── Concat with transitions ───────────────────────────────────────────────────

def _concat(scene_files: list[tuple[Path, dict]], assembled: Path,
            is_shorts: bool) -> None:
    if not scene_files:
        raise RuntimeError("No scene files to concat")

    if len(scene_files) == 1:
        shutil.copy(scene_files[0][0], assembled)
        return

    if is_shorts:
        segments = [p for p, _ in scene_files]
    else:
        segments = _apply_transitions(scene_files, assembled.parent)

    if len(segments) == 1:
        shutil.copy(segments[0], assembled)
        return

    # Validate + log every segment before concat
    total_expected = 0.0
    for p, sc in scene_files:
        d = _duration(p)
        total_expected += d
        if not p.exists() or p.stat().st_size < 500:
            log.error("  Segment missing/empty: %s", p.name)
        else:
            log.debug("  Segment %s: %.3fs  %.0f KB",
                      p.name, d, p.stat().st_size / 1024)
    log.info("  Concat: %d segments (from %d scenes), expected total %.2fs",
             len(segments), len(scene_files), total_expected)

    lst = assembled.parent / "concat_list.txt"
    lst.write_text(
        "\n".join(f"file '{str(p).replace(chr(92), '/')}'" for p in segments),
        encoding="utf-8",
    )
    _run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(lst),
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-an",
         str(assembled)],
        "final concat",
    )


def _apply_transitions(
    scene_files: list[tuple[Path, dict]], work_dir: Path
) -> list[Path]:
    result: list[Path] = []
    i = 0
    while i < len(scene_files):
        path_a, sc_a = scene_files[i]
        label_a = sc_a.get("segment_label", "")

        trans_type = "cut"
        if i + 1 < len(scene_files):
            _, sc_b  = scene_files[i + 1]
            label_b  = sc_b.get("segment_label", "")
            trans_type = _resolve_transition(label_a, label_b)

        if i + 1 < len(scene_files) and trans_type != "cut":
            path_b, _ = scene_files[i + 1]
            dur, xf   = (0.50, "fadeblack") if trans_type == "fade-to-black" \
                        else (0.30, "fade")
            merged = work_dir / f"xfade_{i}_{i+1}.mp4"
            try:
                _xfade(path_a, path_b, dur, xf, merged)
                result.append(merged)
            except Exception as exc:
                log.warning("xfade %s+%s failed: %s — using cut",
                            path_a.name, path_b.name, exc)
                result.append(path_a)
                result.append(path_b)
            i += 2
        else:
            result.append(path_a)
            i += 1
    return result


def _resolve_transition(label_a: str, label_b: str) -> str:
    if label_a.startswith("_") or label_b.startswith("_"):
        return "cut"
    if (label_a == "CORE" and label_b == "PAYOFF") or \
       (label_a == "PAYOFF" and label_b == "CLOSE"):
        return "fade-to-black"
    if label_a != label_b:
        return "cross-dissolve"
    return "cut"


def _xfade(a: Path, b: Path, dur: float, xf_type: str, out: Path) -> None:
    offset = max(0.0, _duration(a) - dur)
    _run(
        ["ffmpeg", "-y", "-i", str(a), "-i", str(b),
         "-filter_complex",
         f"[0:v][1:v]xfade=transition={xf_type}:duration={dur:.3f}:offset={offset:.3f}[v]",
         "-map", "[v]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)],
        f"xfade {a.name}+{b.name}",
    )


# ── Ken Burns ─────────────────────────────────────────────────────────────────

def _ken_burns_expr(focus: str, seg_label: str) -> tuple[str, str, str]:
    z = "min(zoom+0.001,1.5)" if seg_label in ("HOOK", "TENSION") \
        else "if(eq(on\\,1)\\,1.5\\,max(zoom-0.001\\,1.0))"
    if focus == "left":
        x, y = "iw/2-(iw/zoom/2)+on*0.3", "ih/2-(ih/zoom/2)"
    elif focus == "right":
        x, y = "iw/2-(iw/zoom/2)-on*0.3", "ih/2-(ih/zoom/2)"
    elif focus == "top":
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)+on*0.3"
    elif focus == "bottom":
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)-on*0.3"
    else:
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return z, x, y


# ── Utilities ─────────────────────────────────────────────────────────────────

def _base_cmd(vis: Path, dur_s: float, clip_type: str,
              W: int, H: int) -> list[str]:
    if clip_type == "image":
        return ["ffmpeg", "-y", "-loop", "1", "-i", str(vis), "-t", str(dur_s)]
    if clip_type in ("black", "branded") or not vis.exists():
        return ["ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x08080F:size={W}x{H}:rate=30", "-t", str(dur_s)]
    # -stream_loop -1 so short clips cycle to fill the full scene duration
    return ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(vis), "-t", str(dur_s)]


def _duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(json.loads(r.stdout)["format"].get("duration", 0))
    except Exception:
        return 0.0


def _font_dir() -> str:
    import os
    d = "/usr/share/fonts/truetype/dejavu"
    return d if os.path.isdir(d) else ""


def _run(cmd: list, label: str = "ffmpeg") -> None:
    log.debug("FFmpeg [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if res.returncode != 0:
        log.error("FFmpeg [%s] FAILED:\n%s", label, res.stderr[-600:])
        raise RuntimeError(f"FFmpeg failed: {label}")
