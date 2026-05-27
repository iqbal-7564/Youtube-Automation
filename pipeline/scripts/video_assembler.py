"""
STEP 8 — Video Assembly (FFmpeg)

Per-scene rendering (visual + subtitles + brand overlays) → individual MP4s
Then concat with transitions (xfade for dissolve/fade, concat demuxer for cuts).
Output is VIDEO-ONLY (no audio). Audio is merged during encoding (Step 10).

Brand overlays (all non-CLOSE scenes):
  TOP-LEFT    : "VM" pill (channel logo substitute)
  BOTTOM-LEFT : "VisionaryMinds" channel name
  TOP-RIGHT   : Intent label pill (coloured)

CLOSE scene: full black + centered text, no external visual needed.
Safe zones respected for YouTube Shorts UI overlap.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_CHANNEL   = "VisionaryMinds"
_TAGLINE   = "Stay Informed"

_INTENT_COLOR = {
    "WAR":      "0x8B0000",
    "DISASTER": "0xCC4400",
    "POLITICS": "0x003D99",
    "ECONOMY":  "0x006633",
    "SPORTS":   "0x4B0082",
}
_INTENT_LABEL = {
    "WAR":      "BREAKING",
    "DISASTER": "DISASTER",
    "POLITICS": "POLITICS",
    "ECONOMY":  "ECONOMY",
    "SPORTS":   "SPORTS",
}

# DejaVu fonts shipped with fonts-dejavu on Ubuntu
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def assemble_video(timeline: dict, temp_dir: Path, intent: str) -> Path:
    visuals_dir   = temp_dir / "visuals"
    subtitles_dir = temp_dir / "subtitles"
    scenes_dir    = temp_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    W, H     = timeline["width"], timeline["height"]
    profile  = timeline["profile"]
    font_sz  = 52 if profile == "shorts" else 44

    i_upper = intent.upper()
    i_label = _INTENT_LABEL.get(i_upper, "WORLD NEWS")
    i_color = _INTENT_COLOR.get(i_upper, "0x222222")

    scene_outputs: list[tuple[Path, dict]] = []

    for sc in timeline["scenes"]:
        out = scenes_dir / f"scene_{sc['scene_id']}_output.mp4"
        dur_s = sc["duration_ms"] / 1000

        try:
            if sc.get("clip_type") == "close" or sc.get("visual_keyword") == "CLOSE":
                _render_close(sc, out, W, H, dur_s)
            else:
                vis  = visuals_dir / sc.get("visual_file", "_missing")
                sub  = subtitles_dir / f"sub_{sc['scene_id']}.srt"
                _render_scene(vis, sub, out, W, H, dur_s,
                              sc.get("clip_type", "video"),
                              sc["segment_label"],
                              i_label, i_color, font_sz)
        except Exception as exc:
            log.warning("Scene %d render error: %s — using black fill",
                        sc["scene_id"], exc)
            _black_fill(out, W, H, dur_s)

        if not (out.exists() and out.stat().st_size > 500):
            log.warning("Scene %d output missing — black fill", sc["scene_id"])
            _black_fill(out, W, H, dur_s)

        scene_outputs.append((out, sc))

    assembled = temp_dir / "assembled_video.mp4"
    _concat(scene_outputs, assembled)
    return assembled


# ── Per-scene renderers ───────────────────────────────────────────────────────

def _render_scene(vis: Path, sub: Path, out: Path, W: int, H: int,
                  dur_s: float, clip_type: str, seg_label: str,
                  i_label: str, i_color: str, font_sz: int) -> None:

    vf_parts: list[str] = []

    # 1. Scale + crop to target dimensions
    vf_parts.append(
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1"
    )

    # 2. Ken Burns for static images
    if clip_type == "image":
        frames = max(int(dur_s * 30), 30)
        if seg_label in ("HOOK", "TENSION"):
            z_expr = "min(zoom+0.001,1.5)"
        else:
            z_expr = "if(eq(on\\,1)\\,1.5\\,max(zoom-0.001\\,1.0))"
        vf_parts.append(
            f"zoompan=z='{z_expr}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30"
        )

    # 3. Subtitles
    if sub.exists() and sub.stat().st_size > 5:
        safe = str(sub.resolve()).replace("\\", "/")
        # Escape colon after drive letter on Windows (no-op on Linux)
        if len(safe) >= 2 and safe[1] == ":":
            safe = safe[0] + "\\:" + safe[2:]
        margin_v = max(120, int(H * 0.12))
        font_arg  = f":fontsdir={_font_dir()}" if _font_dir() else ""
        vf_parts.append(
            f"subtitles='{safe}'{font_arg}:"
            f"force_style='FontName=DejaVu Sans Bold,"
            f"FontSize={font_sz},"
            f"PrimaryColour=&HFFFFFF,"
            f"OutlineColour=&H000000,"
            f"Outline=3,"
            f"Alignment=2,"
            f"MarginV={margin_v}'"
        )

    # 4. Brand: "VM" logo pill (top-left)
    vf_parts.append(
        f"drawtext=text='VM':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"box=1:boxcolor=0x1A73E8@0.85:boxborderw=14:"
        f"x=42:y=42"
    )

    # 5. Channel name (bottom-left)
    mb = max(60, int(H * 0.05))
    vf_parts.append(
        f"drawtext=text='{_CHANNEL}':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"bordercolor=black:borderw=2:"
        f"x=42:y=h-{mb}-th"
    )

    # 6. Intent label pill (top-right)
    vf_parts.append(
        f"drawtext=text=' {i_label} ':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=24:"
        f"box=1:boxcolor={i_color}@0.92:boxborderw=10:"
        f"x=w-tw-50:y=42"
    )

    vf = ",".join(vf_parts)
    cmd = _base_cmd(vis, out, dur_s, clip_type, W, H)
    cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)]
    _run(cmd, f"scene→{out.name}")


def _render_close(sc: dict, out: Path, W: int, H: int, dur_s: float) -> None:
    vf = (
        f"drawtext=text='{_CHANNEL}':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=72:"
        f"x=(w-tw)/2:y=(h-th)/2-70,"

        f"drawtext=text='{_TAGLINE}':"
        f"fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.65:fontsize=36:"
        f"x=(w-tw)/2:y=(h-th)/2+40,"

        f"drawtext=text='Follow for Live Updates':"
        f"fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.75:fontsize=30:"
        f"x=(w-tw)/2:y=(h-th)/2+100"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0A0A0A:size={W}x{H}:rate=30",
        "-vf", vf,
        "-t", str(dur_s),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30", "-an",
        str(out),
    ]
    _run(cmd, f"CLOSE→{out.name}")


def _black_fill(out: Path, W: int, H: int, dur_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:size={W}x{H}:rate=30",
         "-t", str(dur_s),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)],
        capture_output=True, timeout=30,
    )


# ── Concat with transitions ───────────────────────────────────────────────────

def _concat(scene_files: list[tuple[Path, dict]], assembled: Path) -> None:
    if not scene_files:
        raise RuntimeError("No scene files to concat")

    if len(scene_files) == 1:
        shutil.copy(scene_files[0][0], assembled)
        return

    # Merge pairs that have dissolve/fade-to-black transitions, rest use concat
    segments = _apply_transitions(scene_files, assembled.parent)

    if len(segments) == 1:
        shutil.copy(segments[0], assembled)
        return

    # Concat demuxer for remaining cut-joined segments
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
        trans = sc_a.get("transition", "cut")

        if i + 1 < len(scene_files) and trans in ("cross-dissolve", "fade-to-black"):
            path_b, _ = scene_files[i + 1]
            dur       = 0.15 if trans == "cross-dissolve" else 0.30
            xf_type   = "fade" if trans == "cross-dissolve" else "fadeblack"
            merged    = work_dir / f"xfade_{i}_{i+1}.mp4"
            _xfade(path_a, path_b, dur, xf_type, merged)
            result.append(merged)
            i += 2
        else:
            result.append(path_a)
            i += 1

    return result


def _xfade(a: Path, b: Path, dur: float, xf_type: str, out: Path) -> None:
    offset = max(0.0, _duration(a) - dur)
    _run(
        ["ffmpeg", "-y",
         "-i", str(a), "-i", str(b),
         "-filter_complex",
         f"[0:v][1:v]xfade=transition={xf_type}:duration={dur:.3f}:offset={offset:.3f}[v]",
         "-map", "[v]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-an",
         str(out)],
        f"xfade {a.name}+{b.name}",
    )


# ── Utilities ─────────────────────────────────────────────────────────────────

def _base_cmd(vis: Path, out: Path, dur_s: float,
              clip_type: str, W: int, H: int) -> list[str]:
    if clip_type == "image":
        return ["ffmpeg", "-y", "-loop", "1", "-i", str(vis), "-t", str(dur_s)]
    if clip_type == "black" or not vis.exists():
        return ["ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=black:size={W}x{H}:rate=30", "-t", str(dur_s)]
    return ["ffmpeg", "-y", "-i", str(vis), "-t", str(dur_s)]


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
