# MindBlownFacts — YouTube Automation Pipeline

Fully automated pipeline that selects a world-facts topic, writes a script, generates a voiceover, assembles a video with visuals and branded overlays, and uploads it to YouTube. Runs on GitHub Actions three times a day.

---

## How it works

The pipeline runs 14 sequential steps driven by a single `master_timeline.json` that every step reads and updates.

| Step | Module | What it does |
|------|--------|-------------|
| 1 | `topic_selector` | Picks a topic via Groq; deduplicates against 12 months of history; selects category by performance weight |
| 2 | `script_generator` | Writes a 5-segment script (HOOK → TENSION → CORE → PAYOFF → CLOSE); each segment tagged with `emotion` and `complexity`; generates `engagement_question` for pinned comment |
| 3 | `timeline_builder` | Converts segments to per-scene timeline; enforces minimum dwell times per complexity (simple=3s, moderate=4.5s, complex=6s) |
| 4 | `voice_generator` | Generates per-scene MP3s with emotion-tuned voice settings (edge-tts → ElevenLabs → gTTS → silence); appends 300ms inter-scene silence; tracks which TTS engine was used per scene |
| 5 | `scene_planner` | Assigns 3 ranked visual keywords + `focus_region` per scene |
| 6 | `visual_fetcher` | Tries all 3 scene keywords before falling back to category fallbacks; portrait filter enforced for Shorts |
| 7 | `subtitle_generator` | Writes per-scene SRT files; Shorts captions positioned at 75% frame height (clear of YouTube UI overlay) |
| 8 | `video_assembler` | Renders each scene; prepends 0.5s pre-roll black frame; adds Shorts hook card (1.5s readable text for silent autoplay); directed Ken Burns motion per `focus_region`; mandatory transitions by narrative section; appends 20s branded end card for standard videos |
| 9 | `audio_processor` | Concatenates voice files → loudness-normalise −14 LUFS → peak limiter → 0.5s fade-in + 1s fade-out |
| 10 | `encoder` | Stream-copies assembled video + AAC-encodes audio; `apad` extends audio to video length; `-t` hard cap |
| 11 | `quality_gate` | **10 hard checks** — all must pass; up to 3 retry attempts on failure |
| 12 | `thumbnail_generator` | Pillow-based 1280×720 designed thumbnail — blurred scene visual background, bold yellow headline text, channel + category pills. Never a frame grab. |
| 13 | `uploader` | YouTube resumable upload; uploads designed thumbnail; uploads merged SRT captions; posts + pins engagement comment; assigns to category playlist; chapter markers in description |
| 14 | `news_analytics` | Logs result; writes per-category `performance_history.json` to feed category selection |

---

## Quality gate — 10 checks

All 10 must pass before upload. Failures trigger up to **3 retry attempts**:
- Attempt 2 — re-assemble without xfade transitions
- Attempt 3 — minimal title-card fallback video
- After 3 failures — slot is skipped and logged

| Check | Threshold |
|-------|----------|
| file_integrity | Container valid, moov at start, size > 100 KB |
| resolution | Exact match to profile spec + 30 fps |
| duration | Within ± 2 s of timeline total |
| audio_sync | A/V track length within ± 100 ms |
| audio_level | Integrated loudness − 14 LUFS ± 2 |
| subtitles | No entry past video end; no entry < 300 ms |
| freeze_frame | No freeze > 500 ms (3+ identical consecutive pts values) |
| voice_quality | No scene used gTTS or silence fallback (blocks low-quality audio) |
| dropped_frames | No more than 3 frames with irregular timing (> 20% deviation from 30fps) |
| audio_gaps | No silence gap > 300 ms in the middle of the audio track |

---

## Output formats

| Profile | Dimensions | Duration | Use |
|---------|-----------|----------|-----|
| `shorts` | 1080 × 1920 | ≤ 60 s | YouTube Shorts |
| `standard` | 1920 × 1080 | > 60 s | Long-form |

Profile is chosen automatically after actual voice durations are measured (step 4).

---

## Topic categories

`SPACE · SCIENCE · HISTORY · ANIMALS · NATURE · GEOGRAPHY · OCEAN · CULTURE`

Categories are selected by **performance weight** — categories with higher historical average view duration are preferred. Weight data comes from `performance_history.json` updated after each analytics run. Deduplication runs against the full 12-month video history (not just today).

---

## Voice quality

Engine priority per scene: **edge-tts → ElevenLabs → gTTS → silence**

Voice settings are tuned per emotion tag:

| Emotion | ElevenLabs stability | Style | edge-tts rate |
|---------|---------------------|-------|--------------|
| excited | 0.35 | 0.70 | +5% |
| mysterious | 0.85 | 0.10 | −10% |
| dramatic | 0.55 | 0.45 | −5% |
| neutral | 0.75 | 0.00 | −5% |

If any scene falls back to gTTS or silence, the pipeline logs a warning and the `voice_quality` gate check will fail — preventing a low-quality video from being uploaded.

---

## Schedule

| UTC | Cron | Format |
|-----|------|--------|
| 07:00 | `0 7 * * *` | Shorts |
| 12:00 | `0 12 * * *` | Standard (highest global traffic) |
| 17:00 | `0 17 * * *` | Shorts |

The 12:00 job also triggers an **analytics refresh** that pulls YouTube performance data and updates `performance_history.json` to improve future topic selection.

You can also trigger a manual run from the **Actions** tab with an optional `intent_override`.

---

## Repository secrets

| Secret | Purpose |
|--------|---------|
| `GROQ_API_KEY_1` / `GROQ_API_KEY_2` | Script + topic generation (Groq LLM) |
| `ELEVENLABS_API_KEY` | Premium TTS voice (optional — pipeline falls back to edge-tts) |
| `PEXELS_API_KEY` | Stock footage / photos |
| `PIXABAY_API_KEY` | Stock footage / photos (fallback) |
| `YOUTUBE_CLIENT_ID` | YouTube Data API OAuth |
| `YOUTUBE_CLIENT_SECRET` | YouTube Data API OAuth |
| `YOUTUBE_REFRESH_TOKEN` | YouTube Data API OAuth |

---

## Local setup

```bash
# System deps (Ubuntu / Debian)
sudo apt-get install ffmpeg fonts-dejavu fonts-liberation libass-dev

# Python deps
pip install -r requirements.txt
# requirements.txt: requests gtts edge-tts rapidfuzz Pillow

# Run the pipeline once
python pipeline/main.py
```

Outputs land in `pipeline/output/`. Logs (including quality failures and performance history) go to `pipeline/logs/`.

---

## Project structure

```
pipeline/
  main.py                   # Orchestrator (14 steps, 3-attempt retry)
  scripts/
    topic_selector.py        # Step 1  — topic selection + dedup
    script_generator.py      # Step 2  — script + emotion/complexity tags
    timeline_builder.py      # Step 3  — timeline with min dwell times
    voice_generator.py       # Step 4  — TTS with emotion settings + silence padding
    scene_planner.py         # Step 5  — 3 keywords + focus_region per scene
    visual_fetcher.py        # Step 6  — multi-keyword fetch + portrait filter
    subtitle_generator.py    # Step 7  — SRT, Shorts-aware positioning
    video_assembler.py       # Step 8  — pre-roll, hook card, end card, Ken Burns
    audio_processor.py       # Step 9  — normalize + fade in/out
    encoder.py               # Step 10 — mux video + audio
    quality_gate.py          # Step 11 — 10 checks
    thumbnail_generator.py   # Step 12 — Pillow-designed thumbnail
    uploader.py              # Step 13 — upload, captions, comment, playlist
    news_analytics.py        # Step 14 — performance history per category
  temp/                      # Runtime scratch (voice, visuals, scenes, subtitles)
  output/                    # Final encoded MP4s + thumbnails
  logs/
    quality_failures.json    # Gate failures with attempt number
    video_results.json       # Per-video upload log
    performance_history.json # Per-category avg retention (drives topic selection)
    analytics_data.json      # Raw YouTube Analytics data
.github/workflows/
  news_video.yml             # CI/CD — scheduled + manual dispatch
requirements.txt
```
