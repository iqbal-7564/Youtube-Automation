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
  TOP-LEFT    : logo (pipeline/assets/logo.png) — falls back to "VM" pill
  BOTTOM-LEFT : channel name
  TOP-RIGHT   : intent label pill
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_CHANNEL   = "MindBlownFacts"
_TAGLINE   = "Discover Your World"
_LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

_INTENT_COLOR = {
    "SPACE":     "0x1A0A6B", "SCIENCE":   "0x0055AA",
    "HISTORY":   "0x6B3A00", "ANIMALS":   "0x1A5C00",
    "NATURE":    "0x005C1A", "GEOGRAPHY": "0x006666",
    "OCEAN":     "0x004080", "CULTURE":   "0x7A3500",
}
_INTENT_LABEL = {k: k for k in _INTENT_COLOR}

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Emotion-based color grade filters applied per scene for cinematic look
_COLOR_GRADE: dict[str, str] = {
    "excited":    "eq=saturation=1.18:brightness=0.02:contrast=1.05,"
                  "curves=r='0/0 0.5/0.54 1/1':b='0/0 0.5/0.46 1/1'",   # warm, vibrant
    "mysterious": "eq=saturation=0.82:brightness=-0.03:contrast=1.08,"
                  "curves=r='0/0 0.5/0.46 1/1':b='0/0 0.5/0.54 1/1'",   # cool, desaturated
    "dramatic":   "eq=saturation=1.12:brightness=-0.04:contrast=1.18,"
                  "curves=all='0/0 0.25/0.2 0.75/0.8 1/1'",              # high contrast, punchy
    "neutral":    "eq=saturation=1.0:brightness=0.0:contrast=1.0",        # no grade
}


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
                clip_type = sc.get("clip_type", "video")

                # Use multi-image slideshow when extra images were fetched
                extra_names = sc.get("extra_visual_files", [])
                extras = [visuals_dir / n for n in extra_names
                          if (visuals_dir / n).exists()]
                if clip_type == "image" and extras and vis.exists():
                    vis_list = [vis] + extras
                    _render_slideshow(
                        vis_list, out, W, H, dur_s,
                        sc["segment_label"], i_label, i_color, focus,
                        motion_emotion=sc.get("motion_emotion", "neutral"),
                        scene_id=sc["scene_id"],
                    )
                else:
                    _render_scene(vis, out, W, H, dur_s, clip_type,
                                  sc["segment_label"],
                                  i_label, i_color, focus,
                                  motion_emotion=sc.get("motion_emotion", "neutral"),
                                  scene_id=sc["scene_id"])
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
                  i_label: str, i_color: str, focus: str,
                  motion_emotion: str = "neutral",
                  scene_id: int = 1) -> None:

    vf_parts: list[str] = []

    vf_parts.append(
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1"
    )

    if clip_type == "image":
        frames = max(int(dur_s * 30), 30)
        z_expr, x_expr, y_expr = _ken_burns_expr(
            focus, seg_label, motion_emotion, scene_id
        )
        vf_parts.append(
            f"zoompan=z='{z_expr}':d={frames}:"
            f"x='{x_expr}':y='{y_expr}':s={W}x{H}:fps=30"
        )

    # Emotion-based color grade for cinematic look
    grade = _COLOR_GRADE.get(motion_emotion, _COLOR_GRADE["neutral"])
    vf_parts.append(grade)

    # Vignette on dramatic/mysterious scenes — draws focus to center
    if motion_emotion in ("dramatic", "mysterious"):
        vf_parts.append("vignette=PI/4")

    # Brand overlays — intent pill top-right only (channel name removed per design update)
    # Logo image (top-left) is added via filter_complex overlay below.
    vf_parts.append(
        f"drawtext=text=' {i_label} ':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=24:"
        f"box=1:boxcolor={i_color}@0.92:boxborderw=10:x=w-tw-50:y=42"
    )

    base_cmd = _base_cmd(vis, dur_s, clip_type, W, H)
    logo     = _LOGO_PATH

    if logo.exists():
        logo_size = max(60, min(W // 13, 90))
        vf_chain  = ",".join(vf_parts)
        filter_cx = (
            f"[0:v]{vf_chain}[base];"
            f"[1:v]scale={logo_size}:{logo_size}:flags=lanczos[wm];"
            f"[base][wm]overlay=30:30:shortest=1[out]"
        )
        cmd = base_cmd + [
            "-loop", "1", "-i", str(logo),
            "-filter_complex", filter_cx,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]
    else:
        # No logo — fall back to "VM" text pill in top-left
        vf_parts.insert(1,
            f"drawtext=text='VM':fontfile='{_FONT_BOLD}':"
            f"fontcolor=white:fontsize=28:"
            f"box=1:boxcolor=0x1A73E8@0.85:boxborderw=14:x=42:y=42"
        )
        cmd = base_cmd + [
            "-vf", ",".join(vf_parts),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]

    _run(cmd, f"scene→{out.name}")


def _render_close(sc: dict, out: Path, W: int, H: int, dur_s: float) -> None:
    """
    Animated branded close scene:
      • Deep navy gradient background
      • Logo centered (large), fades in over 0.7s
      • Channel name bold white with blue glow border below logo
      • Tagline in light blue
      • CTA line at bottom
      • Full scene fades in at start, fades out at end
    """
    logo      = _LOGO_PATH
    fade_dur  = 0.7
    fade_out  = max(0.0, dur_s - fade_dur)

    # Proportional sizes
    name_sz = max(44, min(W // 10, 80))
    tag_sz  = max(28, min(W // 17, 48))
    cta_sz  = max(22, min(W // 22, 36))

    # Vertical layout: logo (top half) → name → tagline → CTA
    logo_size = max(120, min(W // 4, 220))
    logo_x    = (W - logo_size) // 2
    logo_y    = H // 2 - logo_size // 2 - (name_sz + tag_sz + 30)
    name_y    = logo_y + logo_size + 20
    tag_y     = name_y + name_sz + 12
    cta_y     = tag_y + tag_sz + 18

    # Text fade-in using alpha expression (t=video time in seconds)
    alpha_expr = f"if(lt(t\\,{fade_dur:.2f})\\,t/{fade_dur:.2f}\\,1)"

    text_vf = (
        # Glow layer — slightly larger, semi-transparent blue (creates glow effect)
        f"drawtext=text='{_CHANNEL}':fontfile='{_FONT_BOLD}':"
        f"fontcolor=0x2288FF@0.5:fontsize={name_sz + 4}:"
        f"alpha='{alpha_expr}':x=(w-tw)/2:y={name_y - 2},"
        # Main channel name — bold white
        f"drawtext=text='{_CHANNEL}':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize={name_sz}:"
        f"bordercolor=0x1A73E8:borderw=3:"
        f"alpha='{alpha_expr}':x=(w-tw)/2:y={name_y},"
        # Tagline — light blue
        f"drawtext=text='{_TAGLINE}':fontfile='{_FONT_REG}':"
        f"fontcolor=0x88CCFF:fontsize={tag_sz}:"
        f"bordercolor=black:borderw=1:"
        f"alpha='{alpha_expr}':x=(w-tw)/2:y={tag_y},"
        # CTA
        f"drawtext=text='Follow for Daily Mind-Blowing Facts':fontfile='{_FONT_REG}':"
        f"fontcolor=white@0.75:fontsize={cta_sz}:"
        f"alpha='{alpha_expr}':x=(w-tw)/2:y={cta_y}"
    )

    base = ["ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x030410:size={W}x{H}:rate=30",
            "-t", str(dur_s)]

    if logo.exists():
        filter_cx = (
            # Apply text to background
            f"[0:v]{text_vf}[txt];"
            # Scale logo and fade in its alpha channel
            f"[1:v]scale={logo_size}:{logo_size}:flags=lanczos,"
            f"fade=t=in:st=0:d={fade_dur:.2f}:alpha=1[logo];"
            # Overlay logo onto text
            f"[txt][logo]overlay={logo_x}:{logo_y}:shortest=1,"
            # Fade full scene in and out
            f"fade=t=in:st=0:d={fade_dur:.2f},"
            f"fade=t=out:st={fade_out:.3f}:d={fade_dur:.2f}[out]"
        )
        cmd = base + [
            "-loop", "1", "-i", str(logo),
            "-filter_complex", filter_cx,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]
    else:
        # No logo — text only with fade
        full_vf = (
            f"{text_vf},"
            f"fade=t=in:st=0:d={fade_dur:.2f},"
            f"fade=t=out:st={fade_out:.3f}:d={fade_dur:.2f}"
        )
        cmd = base + [
            "-vf", full_vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]

    _run(cmd, f"CLOSE→{out.name}")


def _branded_fill(out: Path, W: int, H: int, dur_s: float,
                  i_label: str, i_color: str) -> None:
    """Branded gradient fill — replaces pure black for visual quality."""
    vf = (
        f"drawtext=text=' {i_label} ':fontfile='{_FONT_BOLD}':"
        f"fontcolor=white:fontsize=36:"
        f"box=1:boxcolor={i_color}@0.70:boxborderw=16:"
        f"x=(w-tw)/2:y=(h-th)/2"
    )
    base = ["ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x08080F:size={W}x{H}:rate=30",
            "-t", str(dur_s)]
    logo = _LOGO_PATH
    if logo.exists():
        logo_size = max(60, min(W // 13, 90))
        filter_cx = (
            f"[0:v]{vf}[base];"
            f"[1:v]scale={logo_size}:{logo_size}:flags=lanczos[wm];"
            f"[base][wm]overlay=30:30:shortest=1[out]"
        )
        cmd = base + [
            "-loop", "1", "-i", str(logo),
            "-filter_complex", filter_cx,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]
    else:
        cmd = base + [
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
        ]
    subprocess.run(cmd, capture_output=True, timeout=30)


# ── Slideshow renderer (multiple images → animated crossfade sequence) ────────

def _render_slideshow(
    vis_list: list[Path], out: Path, W: int, H: int, dur_s: float,
    seg_label: str, i_label: str, i_color: str, focus: str,
    motion_emotion: str, scene_id: int,
) -> None:
    """Render 2-3 images as a Ken-Burns slideshow with crossfade transitions."""
    n      = len(vis_list)
    xf_dur = min(0.4, dur_s / (n * 4))        # crossfade never eats > 25% per clip
    per_img = dur_s / n + xf_dur              # each clip slightly longer for xfade overlap

    motions = list(_PRESET_BY_EMOTION.keys())
    sub_outs: list[Path] = []

    for idx, vis in enumerate(vis_list):
        sub_out = out.parent / f"slide_{scene_id}_{idx}.mp4"
        emo = motions[idx % len(motions)]
        try:
            _render_scene(vis, sub_out, W, H, per_img, "image", seg_label,
                          i_label, i_color, focus,
                          motion_emotion=emo, scene_id=scene_id * 100 + idx)
        except Exception as exc:
            log.warning("Slideshow sub-render %d failed: %s — fallback", idx, exc)
            _branded_fill(sub_out, W, H, per_img, i_label, i_color)
        if sub_out.exists() and sub_out.stat().st_size > 500:
            sub_outs.append(sub_out)

    if not sub_outs:
        raise RuntimeError("No slideshow sub-clips rendered")
    if len(sub_outs) == 1:
        shutil.copy(sub_outs[0], out)
        return

    inputs: list[str] = []
    for s in sub_outs:
        inputs += ["-i", str(s)]

    # Build xfade filter chain: [0][1]xfade→[v1]; [v1][2]xfade→[v2]; …
    parts: list[str] = []
    prev = "[0:v]"
    for i in range(1, len(sub_outs)):
        offset = (per_img - xf_dur) * i - xf_dur * (i - 1)
        label  = f"[v{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:"
            f"duration={xf_dur:.2f}:offset={max(0.0, offset):.2f}{label}"
        )
        prev = label

    cmd = (["ffmpeg", "-y"] + inputs + [
        "-filter_complex", ";".join(parts),
        "-map", prev,
        "-t", str(dur_s),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30", "-an", str(out),
    ])
    _run(cmd, f"slideshow→{out.name}", timeout=120)


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
    # All scene files are already libx264/yuv420p/30fps — stream-copy avoids
    # a full re-encode pass that would easily exceed the timeout on CI runners.
    _run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(lst),
         "-c", "copy",
         str(assembled)],
        "final concat",
        timeout=600,
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


# ── Motion presets ────────────────────────────────────────────────────────────
# Each preset is (zoom_expr, x_expr, y_expr) for zoompan filter.
# Varied presets prevent the "same zoom every video" audience fatigue.

_MOTION_PRESETS: dict[str, tuple[str, str, str]] = {
    # Slow gentle drift — calm, beauty, payoff scenes
    "slow_drift": (
        "min(zoom+0.0005,1.25)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # Classic push-in — standard hook/tension
    "push_in": (
        "min(zoom+0.001,1.5)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # Dramatic fast zoom — WOW moments, impact
    "impact_zoom": (
        "min(zoom+0.003,2.0)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # Pull back (reveal) — mystery, reverse narrative
    "reveal_pull": (
        "if(eq(on\\,1)\\,1.8\\,max(zoom-0.002\\,1.0))",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # Pan right — geography, scale, exploration
    "pan_right": (
        "min(zoom+0.0008,1.3)",
        "iw/2-(iw/zoom/2)+on*0.4",
        "ih/2-(ih/zoom/2)",
    ),
    # Pan left — alternative direction
    "pan_left": (
        "min(zoom+0.0008,1.3)",
        "iw/2-(iw/zoom/2)-on*0.4",
        "ih/2-(ih/zoom/2)",
    ),
    # Rise up — discovery, emergence, wonder
    "rise_up": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)-on*0.25",
    ),
    # Descend — underground, ocean deep, threat
    "descend": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)+on*0.25",
    ),
}

# emotion + segment → preferred preset(s), cycled by scene_id for variety
_PRESET_BY_EMOTION: dict[str, list[str]] = {
    "excited":    ["push_in",     "pan_right",   "pan_left"],
    "dramatic":   ["impact_zoom", "reveal_pull", "push_in"],
    "mysterious": ["reveal_pull", "descend",     "slow_drift"],
    "neutral":    ["slow_drift",  "rise_up",     "pan_right"],
}


def _ken_burns_expr(focus: str, seg_label: str,
                    motion_emotion: str = "neutral",
                    scene_id: int = 1) -> tuple[str, str, str]:
    """Select a motion preset based on emotion and scene_id for variety."""
    presets = _PRESET_BY_EMOTION.get(motion_emotion, _PRESET_BY_EMOTION["neutral"])
    preset_name = presets[scene_id % len(presets)]

    # Focus override: if focus_region is explicit, adjust x/y within the preset
    z, x, y = _MOTION_PRESETS[preset_name]
    if focus == "left":
        x = "iw/2-(iw/zoom/2)+on*0.4"
    elif focus == "right":
        x = "iw/2-(iw/zoom/2)-on*0.4"
    elif focus == "top":
        y = "ih/2-(ih/zoom/2)+on*0.3"
    elif focus == "bottom":
        y = "ih/2-(ih/zoom/2)-on*0.3"

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


def _run(cmd: list, label: str = "ffmpeg", timeout: int = 180) -> None:
    log.debug("FFmpeg [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        log.error("FFmpeg [%s] FAILED:\n%s", label, res.stderr[-600:])
        raise RuntimeError(f"FFmpeg failed: {label}")
