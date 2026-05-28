"""
STEP 8 — Video Assembly (FFmpeg)

Per-scene rendering (visual + subtitles + brand overlays) → individual MP4s
Then concat with transitions → assembled_video.mp4 (video-only, no audio).

Smooth-playback additions:
  • 0.5 s pre-roll black frame   — eliminates hard buffering cut at start
  • 20 s end card (standard only)— clean surface for YouTube end-screen elements
  • Shorts hook card (1.5 s)     — designed first frame readable without audio

Transitions:
  • Shorts              → always cut (fast cuts perform better for short-form)
  • Same-section scenes → 0.3 s cross-dissolve
  • CORE→PAYOFF         → 0.5 s fade-to-black (major narrative shift)
  • PAYOFF→CLOSE        → 0.3 s fade-to-black

Directed Ken Burns:
  • focus_region drives pan/zoom direction so motion feels intentional

Brand overlays (all non-CLOSE scenes):
  TOP-LEFT    : "VM" pill (channel logo substitute)
  BOTTOM-LEFT : "MindBlownFacts" channel name
  TOP-RIGHT   : Intent label pill (coloured)
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
    "SPACE":     "0x1A0A6B",
    "SCIENCE":   "0x0055AA",
    "HISTORY":   "0x6B3A00",
    "ANIMALS":   "0x1A5C00",
    "NATURE":    "0x005C1A",
    "GEOGRAPHY": "0x006666",
    "OCEAN":     "0x004080",
    "CULTURE":   "0x7A3500",
}
_INTENT_LABEL = {k: k for k in _INTENT_COLOR}

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

_PRE_ROLL_S  = 0.5    # black frame at very start
_END_CARD_S  = 20.0   # branded end card for standard profile
_HOOK_CARD_S = 1.5    # Shorts silent hook card


def assemble_video(timeline: dict, temp_dir: Path, intent: str) -> Path:
    visuals_dir   = temp_dir / "visuals"
    subtitles_dir = temp_dir / "subtitles"
    scenes_dir    = temp_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    W, H      = timeline["width"], timeline["height"]
    profile   = timeline["profile"]
    is_shorts = profile == "shorts"
    font_sz   = 52 if is_shorts else 44
    margin_v  = timeline.get("_subtitle_margin_v", max(60, int(H * 0.06)))

    i_upper = intent.upper()
    i_label = _INTENT_LABEL.get(i_upper, "FACTS")
    i_color = _INTENT_COLOR.get(i_upper, "0x0055AA")

    scene_outputs: list[tuple[Path, dict]] = []

    # ── Pre-roll black frame ──────────────────────────────────────────────────
    preroll = scenes_dir / "scene_preroll.mp4"
    _black_fill(preroll, W, H, _PRE_ROLL_S)
    # Dummy scene dict — no transition prefix
    scene_outputs.append((preroll, {"segment_label": "_preroll", "transition": "cut"}))

    # ── Shorts hook card ─────────────────────────────────────────────────────
    if is_shorts:
        hook_text = next(
            (sc["script_text"] for sc in timeline["scenes"] if sc["segment_label"] == "HOOK"),
            "",
        )
        if hook_text:
            hook_card = scenes_dir / "scene_hook_card.mp4"
            _render_hook_card(hook_card, W, H, hook_text, _HOOK_CARD_S)
            scene_outputs.append((hook_card, {"segment_label": "_hook_card", "transition": "cut"}))

    # ── Regular scenes ────────────────────────────────────────────────────────
    for sc in timeline["scenes"]:
        out     = scenes_dir / f"scene_{sc['scene_id']}_output.mp4"
        dur_s   = sc["duration_ms"] / 1000
        focus   = sc.get("focus_region", "center")

        try:
            if sc.get("clip_type") == "close" or sc.get("visual_keyword") == "CLOSE":
                _render_close(sc, out, W, H, dur_s)
            else:
                vis = visuals_dir / sc.get("visual_file", "_missing")
                sub = subtitles_dir / f"sub_{sc['scene_id']}.srt"
                _render_scene(vis, sub, out, W, H, dur_s,
                              sc.get("clip_type", "video"),
                              sc["segment_label"],
                              i_label, i_color, font_sz, margin_v, focus)
        except Exception as exc:
            log.warning("Scene %d render error: %s — using black fill",
                        sc["scene_id"], exc)
            _black_fill(out, W, H, dur_s)

        if not (out.exists() and out.stat().st_size > 500):
            log.warning("Scene %d output missing — black fill", sc["scene_id"])
            _black_fill(out, W, H, dur_s)

        scene_outputs.append((out, sc))

    # ── End card (standard only) ──────────────────────────────────────────────
    if not is_shorts:
        end_card = scenes_dir / "scene_end_card.mp4"
        _render_end_card(end_card, W, H, _END_CARD_S)
        scene_outputs.append((end_card, {"segment_label": "_end_card", "transition": "fade-to-black"}))

    assembled = temp_dir / "assembled_video.mp4"
    _concat(scene_outputs, assembled, is_shorts)
    return assembled


# ── Per-scene renderers ───────────────────────────────────────────────────────

def _render_scene(vis: Path, sub: Path, out: Path, W: int, H: int,
                  dur_s: float, clip_type: str, seg_label: str,
                  i_label: str, i_color: str, font_sz: int,
                  margin_v: int, focus: str) -> None:

    vf_parts: list[str] = []

    vf_parts.append(
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1"
    )

    if clip_type == "image":
        frames = max(int(dur_s * 30), 30)
        z_expr, x_expr, y_expr = _ken_burns_expr(focus, seg_label, frames)
        vf_parts.append(
            f"zoompan=z='{z_expr}':d={frames}:"
            f"x='{x_expr}':y='{y_expr}':s={W}x{H}:fps=30"
        )

    if sub.exists() and sub.stat().st_size > 5:
        safe = str(sub.resolve()).replace("\\", "/")
        if len(safe) >= 2 and safe[1] == ":":
            safe = safe[0] + "\\:" + safe[2:]
        font_arg = f":fontsdir={_font_dir()}" if _font_dir() else ""
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

    vf_parts.append(
        f"drawtext=text='VM':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"box=1:boxcolor=0x1A73E8@0.85:boxborderw=14:"
        f"x=42:y=42"
    )

    mb = max(60, int(H * 0.05))
    vf_parts.append(
        f"drawtext=text='{_CHANNEL}':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=28:"
        f"bordercolor=black:borderw=2:"
        f"x=42:y=h-{mb}-th"
    )

    vf_parts.append(
        f"drawtext=text=' {i_label} ':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=24:"
        f"box=1:boxcolor={i_color}@0.92:boxborderw=10:"
        f"x=w-tw-50:y=42"
    )

    vf  = ",".join(vf_parts)
    cmd = _base_cmd(vis, out, dur_s, clip_type, W, H)
    cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out)]
    _run(cmd, f"scene→{out.name}")


def _render_hook_card(out: Path, W: int, H: int, hook_text: str, dur_s: float) -> None:
    """Shorts-only: full-screen text card for silent-autoplay viewers."""
    safe_text = hook_text[:80].replace("'", "\\'").replace(":", "\\:")
    font_sz   = 64 if H > W else 48
    vf = (
        f"drawtext=text='{safe_text}':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize={font_sz}:"
        f"bordercolor=black:borderw=3:"
        f"x=(w-tw)/2:y=(h-th)/2:"
        f"line_spacing=10"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0A0A1A:size={W}x{H}:rate=30",
        "-vf", vf,
        "-t", str(dur_s),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30", "-an",
        str(out),
    ]
    _run(cmd, "hook_card")


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

        f"drawtext=text='Follow for Daily World Facts':"
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


def _render_end_card(out: Path, W: int, H: int, dur_s: float) -> None:
    """20-second branded end card for standard videos (end-screen elements attach here)."""
    vf = (
        f"drawtext=text='{_CHANNEL}':"
        f"fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=80:"
        f"x=(w-tw)/2:y=(h-th)/2-90,"

        f"drawtext=text='{_TAGLINE}':"
        f"fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.70:fontsize=42:"
        f"x=(w-tw)/2:y=(h-th)/2+10,"

        f"drawtext=text='Subscribe for more mind-blowing facts':"
        f"fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.80:fontsize=32:"
        f"x=(w-tw)/2:y=(h-th)/2+90"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x080810:size={W}x{H}:rate=30",
        "-vf", vf,
        "-t", str(dur_s),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30", "-an",
        str(out),
    ]
    _run(cmd, "end_card")


def _black_fill(out: Path, W: int, H: int, dur_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"color=c=black:size={W}x{H}:rate=30",
         "-t", str(dur_s),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)],
        capture_output=True, timeout=30,
    )


# ── Concat with transitions ───────────────────────────────────────────────────

def _concat(scene_files: list[tuple[Path, dict]], assembled: Path, is_shorts: bool) -> None:
    if not scene_files:
        raise RuntimeError("No scene files to concat")

    if len(scene_files) == 1:
        shutil.copy(scene_files[0][0], assembled)
        return

    # Shorts: always cut — no xfade
    if is_shorts:
        segments = [p for p, _ in scene_files]
    else:
        segments = _apply_transitions(scene_files, assembled.parent)

    # Validate every segment before handing to ffmpeg
    expected_total = 0.0
    for p, sc in scene_files:
        dur = _duration(p)
        expected_total += dur
        if not p.exists() or p.stat().st_size < 500:
            log.error("Segment missing/empty: %s", p.name)
        else:
            log.debug("Segment %s: %.3fs  %.1f KB", p.name, dur,
                      p.stat().st_size / 1024)
    log.info("  Concat: %d segments, expected total %.2fs", len(segments), expected_total)

    if len(segments) == 1:
        shutil.copy(segments[0], assembled)
        return

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


def _apply_transitions(scene_files: list[tuple[Path, dict]], work_dir: Path) -> list[Path]:
    result: list[Path] = []
    i = 0
    while i < len(scene_files):
        path_a, sc_a = scene_files[i]
        label_a = sc_a.get("segment_label", "")

        # Determine transition type based on narrative position
        if i + 1 < len(scene_files):
            _, sc_b    = scene_files[i + 1]
            label_b    = sc_b.get("segment_label", "")
            trans_type = _resolve_transition(label_a, label_b)
        else:
            trans_type = "cut"

        if i + 1 < len(scene_files) and trans_type != "cut":
            path_b, _ = scene_files[i + 1]
            if trans_type == "fade-to-black":
                dur, xf = 0.50, "fadeblack"
            else:
                dur, xf = 0.30, "fade"
            merged = work_dir / f"xfade_{i}_{i+1}.mp4"
            try:
                _xfade(path_a, path_b, dur, xf, merged)
                result.append(merged)
            except Exception as exc:
                log.warning("xfade failed (%s+%s): %s — using cuts", path_a.name, path_b.name, exc)
                result.append(path_a)
                result.append(path_b)
            i += 2
        else:
            result.append(path_a)
            i += 1

    return result


def _resolve_transition(label_a: str, label_b: str) -> str:
    """Return transition type for the cut from scene A to scene B."""
    # Pre/post synthetic scenes: always cut
    if label_a.startswith("_") or label_b.startswith("_"):
        return "cut"
    # Major narrative boundaries → fade-to-black
    if (label_a == "CORE" and label_b == "PAYOFF") or \
       (label_a == "PAYOFF" and label_b == "CLOSE"):
        return "fade-to-black"
    # Different sections → short cross-dissolve
    if label_a != label_b:
        return "cross-dissolve"
    # Same section → cut for speed
    return "cut"


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


# ── Ken Burns helpers ─────────────────────────────────────────────────────────

def _ken_burns_expr(focus: str, seg_label: str, frames: int) -> tuple[str, str, str]:
    """Return (z_expr, x_expr, y_expr) for zoompan based on focus region."""
    zoom_in  = "min(zoom+0.001,1.5)"
    zoom_out = "if(eq(on\\,1)\\,1.5\\,max(zoom-0.001\\,1.0))"

    # HOOK and TENSION zoom in (excitement); rest zoom out (resolution feel)
    if seg_label in ("HOOK", "TENSION"):
        z = zoom_in
    else:
        z = zoom_out

    # Pan direction driven by focus region
    if focus == "left":
        x = "iw/2-(iw/zoom/2)+on*0.3"
        y = "ih/2-(ih/zoom/2)"
    elif focus == "right":
        x = "iw/2-(iw/zoom/2)-on*0.3"
        y = "ih/2-(ih/zoom/2)"
    elif focus == "top":
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)+on*0.3"
    elif focus == "bottom":
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)-on*0.3"
    else:
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    return z, x, y


# ── Utilities ─────────────────────────────────────────────────────────────────

def _base_cmd(vis: Path, out: Path, dur_s: float,
              clip_type: str, W: int, H: int) -> list[str]:
    if clip_type == "image":
        return ["ffmpeg", "-y", "-loop", "1", "-i", str(vis), "-t", str(dur_s)]
    if clip_type == "black" or not vis.exists():
        return ["ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=black:size={W}x{H}:rate=30", "-t", str(dur_s)]
    # Loop video so clips shorter than dur_s are cycled to fill the scene.
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
