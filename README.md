# MindBlownFacts — YouTube Automation Pipeline

Fully automated pipeline that selects a world-facts topic, writes a retention-psychology script, generates an emotion-tuned voiceover, assembles a branded video with logo overlay and animated close scene, and uploads it to YouTube. Runs on GitHub Actions three times a day — two Shorts and one long-form standard video.

---

## How it works

The pipeline runs **16 sequential steps** driven by a single `master_timeline.json` that every step reads and updates. Timeline durations are **locked after step 4** — no downstream step may change them.

| Step | Module | What it does |
|------|--------|-------------|
| 1 | `topic_selector` | Trend-aware topic selection via Groq (fetches viral angle hints per category); deduplicates against 12 months of history; selects category by performance weight |
| 2 | `script_generator` | 5-segment script in one of **4 rotating narrative structures** + one of **6 rotating hook formulas**; word count scales with `VIDEO_FORMAT`; marks `[WOW]` moments; generates CTR-psychology title |
| 3 | `timeline_builder` | Per-scene timeline with **global emotional arc** per narrative template; Shorts psychology (hook cap, tight CORE intervals); per-category audience persona dwell times; reads `adaptive_params.json` from previous retention signals |
| 4 | `voice_generator` | Per-scene MP3s with emotion-tuned TTS (edge-tts → ElevenLabs → gTTS → silence); 300ms inter-scene silence (600ms at CORE→PAYOFF); **locks timeline durations** |
| 5 | `scene_planner` | Semantic text analysis — 12 narrative trigger patterns map script text to emotional visual keywords; assigns `motion_emotion` tag per scene |
| 5b | `cinematic_planner` | Director-level shot sequencing (WIDE/AERIAL/MEDIUM/CLOSE/EXTREME\_CLOSE); pacing rhythm per scene; suspense arc peaks at WOW; shot variety rule prevents 3+ consecutive identical types |
| 6 | `visual_fetcher` | Tries all 3 ranked keywords before category fallbacks; portrait orientation enforced for Shorts |
| 7 | `video_assembler` | Renders each scene with brand overlays (logo top-left, channel name bottom-left, category pill top-right); **8 emotion+shot-driven motion presets**; animated close scene with logo fade-in + text glow |
| 8 | `subtitle_generator` | Per-scene SRT files; Shorts captions at 75% frame height (clear of YouTube UI) |
| 9 | `audio_processor` | **3-stage pipeline:** decode PCM → two-pass loudnorm −14 LUFS + afftdn → fades + alimiter + M4A; optional SFX mix (WOW impacts, hook tension, payoff reveal); optional background music at −20 dB |
| 10 | `encoder` | Stream-copies assembled video + AAC-encodes audio; `apad` extends audio to video length; `-shortest` aligns at video end |
| 11 | `quality_gate` | **10 hard checks** — all must pass before upload; up to 3 retry attempts on failure |
| 12 | `thumbnail_generator` + `ctr_optimizer` | Pillow-based 1280×720 thumbnail; CTR optimizer scores 9 title/headline combinations on curiosity gap, tension, specificity, novelty, and synergy — best pair used for upload |
| 13 | `uploader` | YouTube resumable upload; thumbnail; merged SRT captions; engagement comment; category playlist |
| 14 | `news_analytics` | Logs result; fetches retention curve; scores scene-level drop-off; writes `performance_history.json`; applies **adaptive learning** — evolves pipeline parameters automatically |

---

## Video formats

`VIDEO_FORMAT` environment variable controls script length, pacing, and output resolution.

| Format | Duration | Words | Resolution | Schedule |
|--------|----------|-------|-----------|----------|
| `shorts` | ~60 s | 130–180 | 1080 × 1920 | 07:00 + 17:00 UTC daily |
| `standard` | 3–5 min | 450–600 | 1920 × 1080 | 12:00 UTC daily |
| `long` | 7–10 min | 900–1200 | 1920 × 1080 | Manual dispatch only |

**Manual dispatch** — Actions → MindBlownFacts Video Pipeline → Run workflow:
- `intent_override` — force a category (SPACE / SCIENCE / HISTORY / ANIMALS / NATURE / GEOGRAPHY / OCEAN / CULTURE)
- `video_format` — `shorts` | `standard` | `long`

---

## Viral intelligence system

### Narrative templates — 4 rotating structures

Every video uses a different structural template so binge-viewers never feel a repetitive pattern.

| Template | Structure |
|----------|-----------|
| `classic` | Hook teases → tension builds mystery → core delivers facts → payoff resolves → close teases next |
| `mystery` | Open with unsolved mystery → withhold answer until the final reveal |
| `shock_first` | Lead with the most impossible-sounding fact → spend the rest of the video proving it |
| `reverse` | Start at the incredible outcome → work backward to reveal the hidden cause |

### Hook formula engine — 6 rotating formulas

Each video uses a different psychological capture mechanism in the first 1–2 seconds.

| Formula | Mechanism |
|---------|-----------|
| Impossibility | State a fact that sounds physically impossible. Let it hang. |
| Specific number | Use an exact, surprising number. Specificity = credibility. |
| Contradiction | Attack a widely-held belief. Instant curiosity gap. |
| Scale break | Make the comparison incomprehensible. Breaks mental models. |
| Tension gap | State something happened without explaining why. Open loop. |
| Forbidden knowledge | Frame the fact as something suppressed or never taught. |

4 templates × 6 hook formulas = **24 unique structural combinations** per rotation.

### Global emotional arc

Each narrative template drives a planned full-video emotion sequence. Overrides LLM-assigned emotions for coherent storytelling and correct TTS voice + motion preset selection.

| Template | HOOK | TENSION | CORE | PAYOFF | CLOSE |
|----------|------|---------|------|--------|-------|
| classic | excited | mysterious | neutral | dramatic | excited |
| mystery | mysterious | dramatic | mysterious | excited | neutral |
| shock\_first | dramatic | excited | neutral | dramatic | excited |
| reverse | dramatic | mysterious | neutral | excited | mysterious |

### Cinematic shot planning

`cinematic_planner` adds director-level shot metadata to every scene after `scene_planner`:

| Field | Values | Effect |
|-------|--------|--------|
| `shot_type` | WIDE / AERIAL / MEDIUM / CLOSE / EXTREME\_CLOSE | Selects motion preset family in video\_assembler |
| `pacing` | FAST\_CUT / HOLD / SLOW\_BUILD / IMPACT | Controls scene energy signature |
| `suspense_level` | 0.0 – 1.0 | Peaks at 1.0 on WOW-marked scenes (→ EXTREME\_CLOSE + IMPACT) |
| `contrast_shot` | True / False | Flags wide-after-close cuts for visual breathing room |

Shot variety rule: never 3+ consecutive identical shot types. PAYOFF always gets AERIAL/WIDE (visual release). WOW scenes always get EXTREME\_CLOSE + IMPACT.

### Visual emotion intelligence

`scene_planner` scans the actual script text for 12 narrative trigger patterns and prepends emotionally-matched visual keywords before static category banks.

| Trigger pattern | Visual override |
|----------------|----------------|
| died / extinct / destroyed / impact | Cinematic destruction, aftermath, ruins |
| discover / secret / hidden / first time | Discovery, light emergence, reveal |
| bigger / massive / trillion / scale | Aerial vast comparison, cosmic scale |
| terrif / deadly / predator / threat | Dark ominous cinematic, danger |
| ancient / prehistoric / million year | Archaeological ruins, prehistoric landscape |
| impossible / paradox / mind-blowing | Surreal dramatic, paradox contrast |
| underground / cave / deep sea / trench | Cave depth, underwater bioluminescence |
| beautiful / stunning / breathtaking | Cinematic wide, golden light landscape |
| speed / instant / lightning | Fast motion blur, velocity dynamic |
| evolv / survival / creature / species | Wildlife dramatic, nature wide |
| universe / cosmos / galaxy / black hole | Deep space nebula, cosmic dramatic |
| ocean / sea / wave / tsunami | Ocean wave cinematic, underwater dramatic |

### Motion presets — 8 emotion-driven presets

Rotated by shot type + scene index. No two consecutive scenes use the same motion.

| Preset | Shot affinity | Use case |
|--------|--------------|---------|
| `slow_drift` | WIDE, AERIAL | Calm, beauty, payoff |
| `push_in` | MEDIUM | Standard hook and tension |
| `impact_zoom` | EXTREME\_CLOSE | WOW moments, maximum drama |
| `reveal_pull` | CLOSE | Mystery, reverse narrative |
| `pan_right` / `pan_left` | MEDIUM | Geography, exploration, scale |
| `rise_up` | MEDIUM | Discovery, emergence |
| `descend` | CLOSE | Underground, deep ocean, threat |

---

## CTR optimizer

Before upload, `ctr_optimizer` generates up to 3 title variants and 3 thumbnail headline variants, scores every combination on 5 criteria, and injects the highest-scoring pair into the script metadata.

| Criterion | Weight | What it measures |
|-----------|--------|-----------------|
| Curiosity gap | 25% | Implies hidden/forbidden knowledge |
| Emotional tension | 20% | Creates anxiety to find out more |
| Specificity | 10% | Concrete numbers/facts beat vague claims |
| Novelty | 15% | Penalises overused phrases (shocking, amazing, etc.) |
| Synergy | 20% | Title + thumbnail tell different parts of the same story (20–50% word overlap is ideal) |

---

## Pre-render retention prediction

After scene planning (before any rendering), `predict_retention_risk` scores the timeline for likely drop-off points:

- Complex scenes too short → viewer overwhelmed
- 3+ consecutive neutral-emotion scenes → emotional monotony
- Long CORE scene without a WOW marker → attention decay
- Sudden emotion drop after a peak → jarring transition

Outputs `risk_score` (0–1), weak scene list, and actionable recommendations — all logged before a single frame is rendered.

---

## Adaptive learning

After each upload, `apply_adaptive_learning` translates retention signals into automatic parameter updates written to `logs/adaptive_params.json`. `timeline_builder` reads these on the next run.

| Signal | Automatic adjustment |
|--------|---------------------|
| `early_drop` (viewers leave before 25%) | Hook cap reduced by 150ms; tension interval tightened |
| `mid_drop` (viewers leave in CORE) | CORE scene interval reduced |
| `late_drop` (viewers leave after PAYOFF) | PAYOFF/CLOSE flagged for script review |
| Retention > 70% | All parameters locked — system is working |
| Retention drops below 70% | Lock released — system re-adapts |

---

## Animated close scene

The final scene of every video is a fully animated branded card:

- **Background** — Deep navy `#030410`
- **Logo** — Centered (220 px for 1080 px wide), fades in from transparent over 0.7 s
- **Channel name** — Bold white with blue glow layer + blue border (`#1A73E8`)
- **Tagline** — Light blue (`#88CCFF`)
- **CTA** — "Follow for Daily Mind-Blowing Facts"
- **Animation** — Full scene fade-in at start, fade-out at end

Falls back gracefully to text-only if `pipeline/assets/logo.png` is missing.

---

## Audio intelligence

### Background music

Drop royalty-free audio files in `pipeline/assets/music/`. Auto-detected, mixed at −20 dB under voice. Lowpass-filtered at 12 kHz (never competes with voice clarity). Faded in 1.5 s / out 2 s.

| File | Used for |
|------|---------|
| `mysterious.mp3` | Mystery / reverse narrative videos |
| `excited.mp3` | Classic / shock-first videos |
| `dramatic.mp3` | Dramatic reveals and WOW scenes |
| `neutral.mp3` | General fallback |

### Sound effects

Drop SFX files in `pipeline/assets/sfx/`. Mixed at −28 dB (felt, not heard). Gracefully skipped if directory is empty.

| File | When played |
|------|------------|
| `hook_tension.mp3` | At t=0 (opening of every video) |
| `wow_impact.mp3` | At each WOW-marked scene start |
| `payoff_reveal.mp3` | At PAYOFF segment start |

---

## Quality gate — 10 checks

All 10 must pass before upload. Failures trigger up to **3 retry attempts**:
- Attempt 2 — re-assemble without xfade transitions
- Attempt 3 — minimal title-card fallback video
- After 3 failures — slot skipped, logged to `quality_failures.json`

| Check | Threshold |
|-------|----------|
| `file_integrity` | Container valid, moov at start, size > 100 KB |
| `resolution` | Exact match to profile spec (1080×1920 or 1920×1080) + 30 fps |
| `duration` | Within ± 2.5 s of locked timeline total |
| `audio_sync` | A/V stream length diff within ± 0.3 s |
| `audio_level` | Integrated loudness −14 LUFS ± 2 |
| `subtitles` | No entry < 300 ms; overflow clamped silently |
| `freeze_frame` | No freeze > 500 ms (3+ identical consecutive pts values) |
| `voice_quality` | WARNING only — does not block upload |
| `dropped_frames` | No more than 3 frames with irregular timing (> 20% deviation from 30 fps) |
| `audio_gaps` | No silence gap > 2.0 s (inter-scene silence ~1.1–1.8 s by design) |

---

## Topic categories

`SPACE · SCIENCE · HISTORY · ANIMALS · NATURE · GEOGRAPHY · OCEAN · CULTURE`

Selected by **performance weight** — categories with higher average retention are preferred. Deduplication runs against 12 months of history. `_fetch_trending_hints()` calls Groq at run start to get one viral angle hint per category — injected into every topic expansion prompt.

---

## Voice quality

Engine priority per scene: **edge-tts → ElevenLabs → gTTS → silence**

| Emotion | ElevenLabs stability | Style | edge-tts rate |
|---------|---------------------|-------|--------------|
| excited | 0.35 | 0.70 | +5% |
| mysterious | 0.85 | 0.10 | −10% |
| dramatic | 0.55 | 0.45 | −5% |
| neutral | 0.75 | 0.00 | −5% |

---

## Brand assets

| Path | Purpose |
|------|---------|
| `pipeline/assets/logo.png` | Channel logo — PNG with transparency. Top-left overlay on all scenes, bottom-left on thumbnails. Graceful text fallback if missing. |
| `pipeline/assets/music/*.mp3` | Background music. Named by emotion. Auto-detected, skipped if empty. |
| `pipeline/assets/sfx/*.mp3` | Sound effects. Placed at timed scene events. Skipped if empty. |

---

## Schedule

| UTC | Cron | `VIDEO_FORMAT` | Output |
|-----|------|---------------|--------|
| 07:00 | `0 7 * * *` | `shorts` | ~60 s vertical Shorts (1080×1920) |
| 12:00 | `0 12 * * *` | `standard` | 3–5 min landscape (1920×1080) |
| 17:00 | `0 17 * * *` | `shorts` | ~60 s vertical Shorts (1080×1920) |

The 12:00 UTC job also triggers an **analytics refresh** that pulls YouTube retention data, updates `performance_history.json`, and applies adaptive learning for the next run.

---

## Repository secrets

| Secret | Purpose |
|--------|---------|
| `GROQ_API_KEY_1` / `GROQ_API_KEY_2` | Script + topic generation (Groq LLM) |
| `ELEVENLABS_API_KEY` | Premium TTS voice (optional — falls back to edge-tts) |
| `PEXELS_API_KEY` | Stock footage / photos |
| `PIXABAY_API_KEY` | Stock footage / photos (fallback) |
| `YOUTUBE_CLIENT_ID` | YouTube Data API OAuth |
| `YOUTUBE_CLIENT_SECRET` | YouTube Data API OAuth |
| `YOUTUBE_REFRESH_TOKEN` | Requires scopes: `youtube`, `youtube.force-ssl`, `youtube.upload` |

---

## Local setup

```bash
# System deps (Ubuntu / Debian)
sudo apt-get install ffmpeg fonts-dejavu fonts-liberation

# Python deps
pip install -r requirements.txt

# Shorts (~60 s) — default
python pipeline/main.py

# Standard long-form (3–5 min)
VIDEO_FORMAT=standard python pipeline/main.py

# Long video (7–10 min)
VIDEO_FORMAT=long python pipeline/main.py

# Force a category
VIDEO_FORMAT=standard INTENT_OVERRIDE=SPACE python pipeline/main.py
```

Outputs land in `pipeline/output/`. Logs go to `pipeline/logs/`.

---

## Project structure

```
pipeline/
  main.py                      # Orchestrator — 16 steps, 3-attempt quality retry
  assets/
    logo.png                   # Channel logo (PNG with transparency)
    music/
      mysterious.mp3           # Background music — drop royalty-free files here
      excited.mp3
      dramatic.mp3
      neutral.mp3
    sfx/
      hook_tension.mp3         # Sound effects — drop royalty-free files here
      wow_impact.mp3
      payoff_reveal.mp3
  scripts/
    topic_selector.py          # Step 1  — trend-aware topic selection + dedup
    script_generator.py        # Step 2  — 4 templates × 6 hook formulas + CTR titles
    timeline_builder.py        # Step 3  — emotional arc + Shorts psychology + adaptive params
    voice_generator.py         # Step 4  — emotion-tuned TTS + inter-scene silence
    scene_planner.py           # Step 5  — semantic text → emotional visual keywords
    cinematic_planner.py       # Step 5b — shot sequencing + pacing + suspense arc
    visual_fetcher.py          # Step 6  — multi-keyword Pexels/Pixabay fetch
    video_assembler.py         # Step 7  — 8 motion presets + animated close scene
    subtitle_generator.py      # Step 8  — per-scene SRT with Shorts positioning
    audio_processor.py         # Step 9  — 3-stage normalize + SFX + background music
    encoder.py                 # Step 10 — mux video + audio with apad sync
    quality_gate.py            # Step 11 — 10 hard checks, 3-attempt retry
    thumbnail_generator.py     # Step 12 — Pillow thumbnail + logo
    ctr_optimizer.py           # Step 12b — title + headline CTR scoring and synergy
    uploader.py                # Step 13 — upload + captions + comment + playlist
    news_analytics.py          # Step 14 — retention curve + adaptive learning
  temp/                        # Runtime scratch (voice, visuals, scenes, subtitles)
  output/                      # Final MP4s + thumbnails
  logs/
    quality_failures.json      # Gate failures with attempt number and checks detail
    video_results.json         # Per-video upload log (last 200)
    performance_history.json   # Per-category avg retention — drives topic selection
    analytics_data.json        # Raw YouTube Analytics + retention curve data
    adaptive_params.json       # Auto-evolved pipeline parameters from retention signals
.github/workflows/
  news_video.yml               # Scheduled + manual dispatch (shorts/standard/long)
requirements.txt
```

---

## Bug fixes applied (latest audit)

Five bugs were found and fixed in a full codebase audit:

| File | Bug | Severity |
|------|-----|----------|
| `topic_selector.py:194` | SyntaxError — unescaped quotes inside string literal in trend hints prompt | Critical |
| `topic_selector.py:199` | SyntaxError — literal newline inside f-string (invalid in Python ≤ 3.11) | Critical |
| `timeline_builder.py:120` | NameError — `Path` used but `from pathlib import Path` was never imported | Critical |
| `timeline_builder.py:133` | Logic bug — adaptive params applied by mutating the module-level dict, corrupting defaults on repeated calls | High |
| `news_analytics.py:306` | Dead code — `elif avg_ret > 70` was unreachable; lock-release logic never ran | Medium |

All 18 pipeline files pass `py_compile` + import test after fixes.
