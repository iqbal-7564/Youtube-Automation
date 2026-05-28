# Visionary Minds — YouTube Automation Pipeline

Fully automated pipeline that selects a world-facts topic, writes a script, generates a voiceover, assembles a branded video with visuals and logo overlay, and uploads it to YouTube. Runs on GitHub Actions three times a day — two Shorts and one long-form standard video.

---

## How it works

The pipeline runs **14 sequential steps** driven by a single `master_timeline.json` that every step reads and updates. Timeline durations are **locked after step 4** — no downstream step may change them.

| Step | Module | What it does |
|------|--------|-------------|
| 1 | `topic_selector` | Picks a topic via Groq LLM; deduplicates against 12 months of history; selects category by performance weight |
| 2 | `script_generator` | Writes a 5-segment script in one of 4 rotating narrative structures; word count scales with `VIDEO_FORMAT`; marks WOW moments; generates CTR-psychology title |
| 3 | `timeline_builder` | Converts segments to per-scene timeline; Shorts psychology (2.5s hook cap, 3.5s CORE intervals); per-category persona dwell times |
| 4 | `voice_generator` | Generates per-scene MP3s with emotion-tuned settings (edge-tts → ElevenLabs → gTTS → silence fallback); appends 300ms inter-scene silence (600ms at CORE→PAYOFF boundary); **locks timeline durations** |
| 5 | `scene_planner` | Semantic text analysis maps script content to emotional visual keywords; assigns `motion_emotion` tag per scene |
| 6 | `visual_fetcher` | Tries all 3 ranked keywords before category fallbacks; portrait orientation enforced for Shorts |
| 7 | `video_assembler` | Renders each scene with brand overlays (logo top-left, channel name bottom-left, category pill top-right); 8 emotion-driven motion presets; cross-dissolve / fade-to-black transitions |
| 8 | `subtitle_generator` | Writes per-scene SRT files; Shorts captions at 75% frame height (clear of YouTube UI overlay) |
| 9 | `audio_processor` | **3-stage pipeline:** decode PCM → two-pass loudnorm −14 LUFS + afftdn noise reduction → fades + alimiter + M4A output; `apad` at every stage guards against buffer tail loss |
| 10 | `encoder` | Stream-copies assembled video + AAC-encodes audio; `apad` extends audio to video length; `-shortest` aligns at video end |
| 11 | `quality_gate` | **10 hard checks** — all must pass before upload; up to 3 retry attempts on failure |
| 12 | `thumbnail_generator` | Pillow-based 1280×720 thumbnail — blurred scene background, bold yellow headline, CTR-psychology title, logo bottom-left, category pill top-right |
| 13 | `uploader` | YouTube resumable upload; thumbnail; merged SRT captions; engagement comment; category playlist |
| 14 | `news_analytics` | Logs result; fetches audience retention curve; identifies scene-level drop-offs; writes `performance_history.json` per category |

---

## Video formats

The `VIDEO_FORMAT` environment variable controls script length, scene pacing, and output resolution.

| Format | Duration | Words | Resolution | When |
|--------|----------|-------|-----------|------|
| `shorts` | ~60 s | 130–180 | 1080 × 1920 | 07:00 + 17:00 UTC daily |
| `standard` | 3–5 min | 450–600 | 1920 × 1080 | 12:00 UTC daily |
| `long` | 7–10 min | 900–1200 | 1920 × 1080 | Manual dispatch only |

Profile (Shorts vs long-form) is automatically resolved from the actual TTS duration after step 4. `VIDEO_FORMAT` is set by the GitHub Actions workflow per schedule.

---

## Narrative templates

Four script structures rotate per video so the channel never feels repetitive to binge-viewers.

| Template | Structure |
|----------|-----------|
| `classic` | Hook teases → tension builds mystery → core delivers facts → payoff resolves → close teases next |
| `mystery` | Open with unsolved mystery → withhold answer until final moment |
| `shock_first` | Lead with most impossible-sounding fact → spend rest of video proving it |
| `reverse` | Start at the incredible outcome → work backward to reveal the hidden cause |

---

## Visual emotion intelligence

`scene_planner` scans actual script text for 12 narrative trigger patterns and prepends emotionally-matched visual keywords before the static category banks:

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

---

## Motion presets

Eight Ken Burns motion presets are selected by emotion tag + scene index, preventing the same motion repeating on consecutive scenes.

| Preset | Emotion | Use case |
|--------|---------|---------|
| `slow_drift` | neutral | Calm, beauty, payoff |
| `push_in` | excited | Standard hook/tension |
| `impact_zoom` | dramatic | WOW moments, impact |
| `reveal_pull` | mysterious | Mystery, reverse narrative |
| `pan_right` / `pan_left` | excited | Geography, exploration |
| `rise_up` | neutral | Discovery, emergence |
| `descend` | mysterious | Underground, deep ocean, threat |

---

## Retention analytics

After each video, `news_analytics` fetches the YouTube audience retention curve and stores:
- Retention percentage at 25 / 50 / 75% milestones
- Position and size of the biggest single drop-off
- Retention signal: `early_drop` / `mid_drop` / `late_drop` with an actionable hint

These signals feed back into `performance_history.json` and will eventually guide automatic script adjustments.

---

## Quality gate — 10 checks

All 10 must pass before upload. Failures trigger up to **3 retry attempts**:
- Attempt 2 — re-assemble without xfade transitions
- Attempt 3 — minimal title-card fallback video
- After 3 failures — slot skipped and logged to `quality_failures.json`

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
| `audio_gaps` | No silence gap > 2.0 s (inter-scene silence is ~1.1–1.8 s by design) |

---

## Topic categories

`SPACE · SCIENCE · HISTORY · ANIMALS · NATURE · GEOGRAPHY · OCEAN · CULTURE`

Categories are selected by **performance weight** — categories with higher average view duration are preferred. Deduplication runs against the full 12-month video history.

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

Place the channel logo at:

```
pipeline/assets/logo.png
```

PNG with transparency recommended. The logo is overlaid top-left on every video scene and bottom-left on every thumbnail. If the file is missing, the pipeline falls back gracefully to a text "VM" pill in videos and a "Visionary Minds" text pill in thumbnails.

---

## Schedule

| UTC | Cron | `VIDEO_FORMAT` | Output |
|-----|------|---------------|--------|
| 07:00 | `0 7 * * *` | `shorts` | ~60s vertical Shorts |
| 12:00 | `0 12 * * *` | `standard` | 3–5 min landscape |
| 17:00 | `0 17 * * *` | `shorts` | ~60s vertical Shorts |

**Manual dispatch** — Go to Actions → Visionary Minds Video Pipeline → Run workflow. Inputs:
- `intent_override` — force a category (SPACE / SCIENCE / HISTORY / etc.)
- `video_format` — `shorts` | `standard` | `long` (7–10 min)

The 12:00 UTC job also triggers an **analytics refresh** that pulls YouTube retention data and updates `performance_history.json`.

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
| `YOUTUBE_REFRESH_TOKEN` | YouTube Data API OAuth — requires scopes: `youtube`, `youtube.force-ssl`, `youtube.upload` |

---

## Local setup

```bash
# System deps (Ubuntu / Debian)
sudo apt-get install ffmpeg fonts-dejavu fonts-liberation

# Python deps
pip install -r requirements.txt

# Run as Shorts (default)
python pipeline/main.py

# Run as standard long-form
VIDEO_FORMAT=standard python pipeline/main.py

# Run as long video (7-10 min)
VIDEO_FORMAT=long python pipeline/main.py
```

Outputs land in `pipeline/output/`. Logs go to `pipeline/logs/`.

---

## Project structure

```
pipeline/
  main.py                    # Orchestrator — 14 steps, 3-attempt quality retry
  assets/
    logo.png                 # Channel logo (PNG with transparency) — place here
  scripts/
    topic_selector.py        # Step 1  — topic selection + performance-weighted dedup
    script_generator.py      # Step 2  — 4 narrative templates + CTR titles + WOW moments
    timeline_builder.py      # Step 3  — Shorts psychology + persona dwell times per category
    voice_generator.py       # Step 4  — TTS with emotion tuning + inter-scene silence padding
    scene_planner.py         # Step 5  — semantic text analysis → emotional visual keywords
    visual_fetcher.py        # Step 6  — multi-keyword Pexels/Pixabay fetch + portrait filter
    video_assembler.py       # Step 7  — scene render + logo overlay + 8 motion presets
    subtitle_generator.py    # Step 8  — per-scene SRT with Shorts-aware positioning
    audio_processor.py       # Step 9  — 3-stage normalize: loudnorm + afftdn + limiter + M4A
    encoder.py               # Step 10 — mux video + audio with apad sync
    quality_gate.py          # Step 11 — 10 hard checks, 3-attempt retry
    thumbnail_generator.py   # Step 12 — Pillow thumbnail + CTR headline + logo
    uploader.py              # Step 13 — upload + thumbnail + captions + comment + playlist
    news_analytics.py        # Step 14 — retention curve + scene drop-off + performance history
  temp/                      # Runtime scratch (voice, visuals, scenes, subtitles)
  output/                    # Final MP4s + thumbnails
  logs/
    quality_failures.json    # Gate failures with attempt number and checks detail
    video_results.json       # Per-video upload log (last 200)
    performance_history.json # Per-category avg retention — drives topic selection
    analytics_data.json      # Raw YouTube Analytics + retention curve data
.github/workflows/
  news_video.yml             # Scheduled + manual dispatch CI/CD (shorts/standard/long)
requirements.txt
```
