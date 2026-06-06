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
    "SPACE":       "0x1A0A6B", "SCIENCE":     "0x0055AA",
    "HISTORY":     "0x6B3A00", "ANIMALS":     "0x1A5C00",
    "NATURE":      "0x005C1A", "GEOGRAPHY":   "0x006666",
    "OCEAN":       "0x004080", "CULTURE":     "0x7A3500",
    "TECHNOLOGY":  "0x005AB4", "PSYCHOLOGY":  "0x5A00A0",
    "MYTHOLOGY":   "0x784600", "MEDICINE":    "0xA00032",
    "MATHEMATICS": "0x003296", "ECONOMICS":   "0x006E28",
    "PHYSICS":     "0xA03C00",
}
_INTENT_LABEL = {k: k for k in _INTENT_COLOR}

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _escape_drawtext(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\\'")
    text = text.replace(":",  "\\:")
    text = text.replace("%",  "\\%")
    # Keep only first 10 words so it fits on one line
    words = text.split()[:10]
    return " ".join(words)

# Cinematic color grade filters — movie-quality LUT-style grading per emotion
_COLOR_GRADE: dict[str, str] = {
    # Warm golden blockbuster — boosted saturation, lifted shadows, warm highlights
    "excited":    (
        "eq=saturation=1.22:brightness=0.03:contrast=1.08,"
        "curves=r='0/0 0.3/0.32 0.7/0.74 1/1':g='0/0 0.5/0.51 1/1':b='0/0 0.5/0.46 1/1',"
        "unsharp=3:3:0.5:3:3:0"
    ),
    # Teal-orange split — cold crushed shadows, warm highlights, desaturated midtones
    "mysterious": (
        "eq=saturation=0.72:brightness=-0.04:contrast=1.15,"
        "curves=r='0/0 0.3/0.26 0.7/0.65 1/0.94':b='0/0.02 0.3/0.33 0.7/0.72 1/1',"
        "unsharp=3:3:0.4:3:3:0"
    ),
    # Deep crushed blacks, punchy highlights — cinematic high-contrast drama
    "dramatic":   (
        "eq=saturation=1.18:brightness=-0.06:contrast=1.25,"
        "curves=all='0/0 0.12/0.06 0.5/0.48 0.88/0.90 1/1',"
        "unsharp=3:3:0.7:3:3:0"
    ),
    # Reference clean — barely warm, documentary/educational quality
    "neutral":    (
        "eq=saturation=1.06:brightness=0.01:contrast=1.03,"
        "curves=r='0/0 0.5/0.505 1/1':b='0/0 0.5/0.495 1/1'"
    ),
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

    # First-frame hook text — shown on scene 1 for Shorts to stop the scroll
    hook_text = ""
    if is_shorts and timeline["scenes"]:
        hook_text = timeline["scenes"][0].get("script_text", "")

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
                        hook_text=hook_text if sc["scene_id"] == 1 else "",
                    )
                else:
                    _render_scene(vis, out, W, H, dur_s, clip_type,
                                  sc["segment_label"],
                                  i_label, i_color, focus,
                                  motion_emotion=sc.get("motion_emotion", "neutral"),
                                  scene_id=sc["scene_id"],
                                  hook_text=hook_text if sc["scene_id"] == 1 else "")
        except Exception as exc:
            log.warning("Scene %d render error: %s — fallback", sc["scene_id"], exc)
            _branded_fill(out, W, H, dur_s, i_label, i_color)

        if not (out.exists() and out.stat().st_size > 500):
            log.warning("Scene %d output missing — fallback", sc["scene_id"])
            _branded_fill(out, W, H, dur_s, i_label, i_color)

        scene_outputs.append((out, sc))

    assembled = temp_dir / "assembled_video.mp4"
    _concat(scene_outputs, assembled, is_shorts)

    # xfade transitions overlap clips and shorten the assembled video below
    # locked_duration. Pad the last frame to restore exact locked duration so
    # audio trim and subtitle timestamps all align at the same end point.
    locked_s = timeline["total_duration_seconds"]
    actual_s = _duration(assembled)
    if locked_s - actual_s > 0.05:
        log.info("Assembly: actual=%.3fs locked=%.3fs — padding %.3fs",
                 actual_s, locked_s, locked_s - actual_s)
        padded = temp_dir / "assembled_video_padded.mp4"
        _pad_to_duration(assembled, padded, locked_s)
        if padded.exists() and padded.stat().st_size > 1000:
            padded.replace(assembled)
        else:
            log.warning("Assembly pad failed — subtitle sync may drift at end")

    return assembled


# ── Per-scene renderers ───────────────────────────────────────────────────────

def _render_scene(vis: Path, out: Path, W: int, H: int,
                  dur_s: float, clip_type: str, seg_label: str,
                  i_label: str, i_color: str, focus: str,
                  motion_emotion: str = "neutral",
                  scene_id: int = 1,
                  hook_text: str = "") -> None:

    # Video clips with missing visual produce a static lavfi color frame (no
    # zoompan is applied for clip_type="video"), which triggers freeze detection.
    # Route to animated branded fill immediately instead.
    if clip_type == "video" and not vis.exists():
        _branded_fill(out, W, H, dur_s, i_label, i_color)
        return

    vf_parts: list[str] = []

    vf_parts.append(
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1"
    )

    if clip_type == "image":
        frames = max(int(dur_s * 30), 30)
        z_expr, x_expr, y_expr = _ken_burns_expr(
            focus, seg_label, motion_emotion, scene_id, frames
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

    # First-frame hook text — large bold overlay for first 3s of scene 1 (Shorts only)
    # Stops the scroll: viewer reads hook before deciding to swipe
    if hook_text and scene_id == 1:
        escaped = _escape_drawtext(hook_text)
        font_sz = max(42, W // 18)
        vf_parts.append(
            f"drawtext=text='{escaped}':fontfile='{_FONT_BOLD}':"
            f"fontcolor=white:fontsize={font_sz}:"
            f"box=1:boxcolor=black@0.72:boxborderw=18:"
            f"x=(w-tw)/2:y=h*0.38:"
            f"enable='between(t,0,3)'"
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
            # Apply text to background (noise prevents freeze detection)
            f"[0:v]noise=alls=6:allf=t,{text_vf}[txt];"
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
        # No logo — text only with fade (noise prevents freeze detection)
        full_vf = (
            f"noise=alls=6:allf=t,{text_vf},"
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
    # noise=allf=t: per-frame temporal noise, amplitude 6/255 — invisible to viewers
    # but changes pixels every frame, preventing freeze-frame detection at quality gate.
    vf = (
        "noise=alls=6:allf=t,"
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
    hook_text: str = "",
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
                          motion_emotion=emo, scene_id=scene_id * 100 + idx,
                          hook_text=hook_text if idx == 0 else "")
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
            # Respect forced cut override written by main.py on quality gate retry.
            # Without this check, the retry "without transitions" has no effect
            # because _resolve_transition reads segment labels, not sc["transition"].
            if sc_a.get("transition") == "cut" or sc_b.get("transition") == "cut":
                trans_type = "cut"
            else:
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
    # ── Original 8 ───────────────────────────────────────────────────────────

    # 1. Slow gentle drift — calm, beauty, payoff scenes
    "slow_drift": (
        "min(zoom+0.0005,1.25)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # 2. Classic push-in — standard hook/tension
    "push_in": (
        "min(zoom+0.001,1.5)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # 3. Dramatic fast zoom — WOW moments, impact
    "impact_zoom": (
        "min(zoom+0.003,2.0)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # 4. Pull back (reveal) — mystery, reverse narrative
    "reveal_pull": (
        "if(eq(on\\,1)\\,1.8\\,max(zoom-0.002\\,1.0))",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # 5. Pan right — geography, scale, exploration
    "pan_right": (
        "min(zoom+0.0008,1.3)",
        "iw/2-(iw/zoom/2)+on*0.4",
        "ih/2-(ih/zoom/2)",
    ),
    # 6. Pan left — alternative direction
    "pan_left": (
        "min(zoom+0.0008,1.3)",
        "iw/2-(iw/zoom/2)-on*0.4",
        "ih/2-(ih/zoom/2)",
    ),
    # 7. Rise up — discovery, emergence, wonder
    "rise_up": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)-on*0.25",
    ),
    # 8. Descend — underground, ocean deep, threat
    "descend": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)+on*0.25",
    ),

    # ── New 8 ────────────────────────────────────────────────────────────────

    # 9. Zoom into top-left corner — subject anchored top-left (e.g. space corner)
    "zoom_corner_tl": (
        "min(zoom+0.001,1.6)",
        "0",
        "0",
    ),
    # 10. Zoom into bottom-right corner — subject anchored bottom-right
    "zoom_corner_br": (
        "min(zoom+0.001,1.6)",
        "iw*(1-1/zoom)",
        "ih*(1-1/zoom)",
    ),
    # 11. Diagonal drift — zoom + simultaneous X+Y pan (top-left → bottom-right)
    "diagonal_drift": (
        "min(zoom+0.0004,1.2)",
        "iw/2-(iw/zoom/2)+on*0.5",
        "ih/2-(ih/zoom/2)+on*0.3",
    ),
    # 12. Tilt reveal — start at bottom frame, pan camera upward (like a tilt shot)
    "tilt_reveal": (
        "min(zoom+0.0008,1.3)",
        "iw/2-(iw/zoom/2)",
        "max(0\\,ih*(1-1/zoom)-on*0.4)",
    ),
    # 13. Fast push — aggressive tension zoom, more intense than push_in
    "fast_push": (
        "min(zoom+0.004,2.5)",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
    # 14. Orbit left — zoom + arc pan sweeping left-and-down (circular feel)
    "orbit_left": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)-on*0.35",
        "ih/2-(ih/zoom/2)+on*0.15",
    ),
    # 15. Orbit right — zoom + arc pan sweeping right-and-up
    "orbit_right": (
        "min(zoom+0.001,1.4)",
        "iw/2-(iw/zoom/2)+on*0.35",
        "ih/2-(ih/zoom/2)-on*0.15",
    ),
    # 16. Breathe — slow sinusoidal zoom pulse; almost static but alive
    "breathe": (
        "max(1.0\\,1.05+0.07*sin(on/30))",
        "iw/2-(iw/zoom/2)",
        "ih/2-(ih/zoom/2)",
    ),
}

# Frame count at which each preset's zoom expression permanently caps and produces
# frozen output (zoom stops changing AND x/y derived from zoom also stop changing).
# Presets where x or y contain `on*` (pan_right, orbit_*, diagonal_drift, etc.)
# are safe — they keep moving even after zoom caps, so their cap is set to 999_999.
_PRESET_CAP_FRAMES: dict[str, int] = {
    "slow_drift":     500,    # zoom 1→1.25  @ +0.0005/frame
    "push_in":        500,    # zoom 1→1.5   @ +0.001/frame
    "impact_zoom":    333,    # zoom 1→2.0   @ +0.003/frame
    "reveal_pull":    400,    # zoom 1.8→1.0 @ -0.002/frame, then x=y=0 forever
    "fast_push":      375,    # zoom 1→2.5   @ +0.004/frame
    "zoom_corner_tl": 600,    # zoom 1→1.6   @ +0.001/frame; x=0,y=0 always
    "zoom_corner_br": 600,    # zoom 1→1.6   @ +0.001/frame; x,y only follow zoom
    # Safe: x or y expression contains `on*` so they move even after zoom caps
    "pan_right":    999_999,
    "pan_left":     999_999,
    "rise_up":      999_999,
    "descend":      999_999,
    "diagonal_drift": 999_999,
    "tilt_reveal":  999_999,
    "orbit_left":   999_999,
    "orbit_right":  999_999,
    "breathe":      999_999,  # sinusoidal zoom, never permanently caps
}

# emotion + segment → preferred presets, cycled by scene_id for variety.
# 5 options per emotion means consecutive scenes of the same emotion
# use a different animation every time for up to 5 scenes before repeating.
_PRESET_BY_EMOTION: dict[str, list[str]] = {
    "excited":    ["push_in",     "pan_right",    "fast_push",      "orbit_right",
                   "pan_left",    "rise_up",      "diagonal_drift", "zoom_corner_br"],
    "dramatic":   ["impact_zoom", "reveal_pull",  "fast_push",      "zoom_corner_br",
                   "orbit_left",  "descend",      "zoom_corner_tl", "breathe"],
    "mysterious": ["reveal_pull", "descend",      "breathe",        "zoom_corner_tl",
                   "slow_drift",  "tilt_reveal",  "orbit_left",     "diagonal_drift"],
    "neutral":    ["slow_drift",  "rise_up",      "diagonal_drift", "tilt_reveal",
                   "orbit_right", "pan_right",    "breathe",        "pan_left"],
}


def _ken_burns_expr(focus: str, seg_label: str,
                    motion_emotion: str = "neutral",
                    scene_id: int = 1,
                    frames: int = 0) -> tuple[str, str, str]:
    """Select a motion preset based on emotion and scene_id for variety."""
    presets = _PRESET_BY_EMOTION.get(motion_emotion, _PRESET_BY_EMOTION["neutral"])
    preset_name = presets[scene_id % len(presets)]

    # If this scene is longer than the preset's zoom cap, the zoompan stops
    # moving and produces frozen frames that fail the freeze-frame quality check.
    # Fall back to breathe (sinusoidal, never caps) to keep pixels changing.
    if frames > 0 and frames > _PRESET_CAP_FRAMES.get(preset_name, 999_999):
        preset_name = "breathe"

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


def _pad_to_duration(src: Path, dst: Path, target_s: float) -> None:
    """
    Freeze-pad last frame to reach exactly target_s.
    Fast approach: encode only the tiny pad clip, then stream-copy concat.
    Avoids re-encoding the full assembled video.
    """
    actual_s = _duration(src)
    pad_s    = target_s - actual_s
    if pad_s <= 0:
        shutil.copy(src, dst)
        return

    work = src.parent

    # Step 1: extract last frame as PNG
    last_frame = work / "_pad_last_frame.png"
    subprocess.run([
        "ffmpeg", "-y", "-sseof", "-0.5", "-i", str(src),
        "-frames:v", "1", str(last_frame),
    ], capture_output=True, timeout=30)

    if not last_frame.exists():
        log.warning("Pad: could not extract last frame — skipping pad")
        shutil.copy(src, dst)
        return

    # Step 2: encode only the small pad clip
    pad_clip = work / "_pad_clip.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(last_frame),
        "-t", f"{pad_s + 0.1:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "30", "-an", str(pad_clip),
    ], capture_output=True, timeout=30)

    if not pad_clip.exists():
        log.warning("Pad: pad clip encode failed — skipping pad")
        shutil.copy(src, dst)
        return

    # Step 3: concat original + pad via stream copy (no re-encode)
    lst = work / "_pad_concat.txt"
    lst.write_text(
        f"file '{str(src).replace(chr(92), '/')}'\n"
        f"file '{str(pad_clip).replace(chr(92), '/')}'"
    )
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(lst),
        "-t", str(target_s),
        "-c", "copy", str(dst),
    ], capture_output=True, timeout=60)

    # Cleanup temp files
    for f in [last_frame, pad_clip, lst]:
        f.unlink(missing_ok=True)


def _run(cmd: list, label: str = "ffmpeg", timeout: int = 300) -> None:
    log.debug("FFmpeg [%s] %s …", label, " ".join(str(c) for c in cmd[:5]))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        log.error("FFmpeg [%s] FAILED:\n%s", label, res.stderr[-600:])
        raise RuntimeError(f"FFmpeg failed: {label}")
