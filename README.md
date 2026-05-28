# Visionary Minds — YouTube Automation Pipeline

Fully automated pipeline that selects a world-facts topic, writes a script, generates a voiceover, assembles a branded video with visuals and logo overlay, and uploads it to YouTube. Runs on GitHub Actions three times a day.

---

## How it works

The pipeline runs **14 sequential steps** driven by a single `master_timeline.json` that every step reads and updates. Timeline durations are **locked after step 4** — no downstream step may change them.

| Step | Module | What it does |
|------|--------|-------------|
| 1 | `topic_selector` | Picks a topic via Groq LLM; deduplicates against 12 months of history; selects category by performance weight |
| 2 | `script_generator` | Writes a 5-segment script (HOOK → TENSION → CORE → PAYOFF → CLOSE); each segment tagged with `emotion` + `complexity`; generates `engagement_question` for pinned comment |
| 3 | `timeline_builder` | Converts segments to per-scene timeline; enforces minimum dwell times by complexity (simple=3s, moderate=4.5s, complex=6s) |
| 4 | `voice_generator` | Generates per-scene MP3s with emotion-tuned settings (edge-tts → ElevenLabs → gTTS → silence fallback); appends 300ms inter-scene silence (600ms at CORE→PAYOFF boundary); **locks timeline durations** |
| 5 | `scene_planner` | Assigns 3 ranked visual keywords + `focus_region` per scene |
| 6 | `visual_fetcher` | Tries all 3 keywords before category fallbacks; portrait orientation enforced for Shorts; Ken Burns `focus_region` guides directed pan |
| 7 | `video_assembler` | Renders each scene with brand overlays (logo top-left, channel name bottom-left, category pill top-right); directed Ken Burns motion; cross-dissolve / fade-to-black transitions by narrative section |
| 8 | `subtitle_generator` | Writes per-scene SRT files with absolute→relative timestamp conversion; Shorts captions at 75% frame height (clear of YouTube UI) |
| 9 | `audio_processor` | **3-stage pipeline:** decode PCM → two-pass loudnorm −14 LUFS + afftdn noise reduction → fades + alimiter + M4A output; `apad` at every stage guards against buffer tail loss |
| 10 | `encoder` | Stream-copies assembled video + AAC-encodes audio; `apad` extends audio to video length; `-shortest` aligns at video end |
| 11 | `quality_gate` | **10 hard checks** — all must pass before upload; up to 3 retry attempts on failure |
| 12 | `thumbnail_generator` | Pillow-based 1280×720 thumbnail — blurred scene background, bold yellow headline, logo bottom-left, category pill top-right |
| 13 | `uploader` | YouTube resumable upload; thumbnail; merged SRT captions; engagement comment; category playlist |
| 14 | `news_analytics` | Logs result; writes `performance_history.json` per category to feed future topic selection |

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

## Output formats

| Profile | Dimensions | Duration | Use |
|---------|-----------|----------|-----|
| `shorts` | 1080 × 1920 | ≤ 60 s | YouTube Shorts |
| `standard` | 1920 × 1080 | > 60 s | Long-form |

Profile is chosen automatically after actual voice durations are measured at step 4.

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

| UTC | Cron | Format |
|-----|------|--------|
| 07:00 | `0 7 * * *` | Shorts |
| 12:00 | `0 12 * * *` | Standard |
| 17:00 | `0 17 * * *` | Shorts |

Manual runs are available from the **Actions** tab with an optional `intent_override`.

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
| `YOUTUBE_REFRESH_TOKEN` | YouTube Data API OAuth (requires `youtube`, `youtube.force-ssl`, `youtube.upload` scopes) |

---

## Local setup

```bash
# System deps (Ubuntu / Debian)
sudo apt-get install ffmpeg fonts-dejavu fonts-liberation

# Python deps
pip install -r requirements.txt

# Run once
python pipeline/main.py
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
    script_generator.py      # Step 2  — 5-segment script + emotion/complexity tags
    timeline_builder.py      # Step 3  — timeline with min dwell times per complexity
    voice_generator.py       # Step 4  — TTS with emotion tuning + inter-scene silence
    scene_planner.py         # Step 5  — 3 ranked keywords + focus_region per scene
    visual_fetcher.py        # Step 6  — multi-keyword Pexels/Pixabay fetch
    video_assembler.py       # Step 7  — scene render + logo overlay + transitions
    subtitle_generator.py    # Step 8  — per-scene SRT with Shorts-aware positioning
    audio_processor.py       # Step 9  — 3-stage normalize: loudnorm + afftdn + limiter
    encoder.py               # Step 10 — mux video + audio with apad sync
    quality_gate.py          # Step 11 — 10 hard checks, 3-attempt retry
    thumbnail_generator.py   # Step 12 — Pillow-designed 1280×720 thumbnail
    uploader.py              # Step 13 — upload + thumbnail + captions + comment
    news_analytics.py        # Step 14 — per-category performance history
  temp/                      # Runtime scratch (voice, visuals, scenes, subtitles)
  output/                    # Final MP4s + thumbnails
  logs/
    quality_failures.json    # Gate failures with attempt number and checks detail
    video_results.json       # Per-video upload log (last 200)
    performance_history.json # Per-category avg retention — drives topic selection
    analytics_data.json      # Raw YouTube Analytics data
.github/workflows/
  news_video.yml             # Scheduled + manual dispatch CI/CD
requirements.txt
```
