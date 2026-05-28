# MindBlownFacts — YouTube Automation Pipeline

Fully automated pipeline that selects a world-facts topic, writes a retention-psychology script, generates an emotion-tuned voiceover, assembles a branded video with logo overlay and animated close scene, and uploads it to YouTube. Runs on GitHub Actions three times a day — two Shorts and one long-form standard video.

---

## How it works

The pipeline runs **14 sequential steps** driven by a single `master_timeline.json` that every step reads and updates. Timeline durations are **locked after step 4** — no downstream step may change them.

| Step | Module | What it does |
|------|--------|-------------|
| 1 | `topic_selector` | Picks a topic via Groq LLM with trend-aware prompting (fresh angles, recent discoveries); deduplicates against 12 months of history; selects category by performance weight |
| 2 | `script_generator` | Writes a 5-segment script in one of **4 rotating narrative structures**; injects one of **6 rotating hook formulas**; word count scales with `VIDEO_FORMAT`; marks WOW moments; generates CTR-psychology title |
| 3 | `timeline_builder` | Converts segments to per-scene timeline; applies **global emotional arc** per narrative template; Shorts psychology (2.5s hook cap, 3.5s CORE intervals); per-category persona dwell times |
| 4 | `voice_generator` | Generates per-scene MP3s with emotion-tuned settings (edge-tts → ElevenLabs → gTTS → silence fallback); appends 300ms inter-scene silence (600ms at CORE→PAYOFF boundary); **locks timeline durations** |
| 5 | `scene_planner` | **Semantic text analysis** maps 12 narrative trigger patterns in script text to emotional visual keywords; assigns `motion_emotion` tag per scene |
| 6 | `visual_fetcher` | Tries all 3 ranked keywords before category fallbacks; portrait orientation enforced for Shorts |
| 7 | `video_assembler` | Renders each scene with brand overlays (logo top-left, channel name bottom-left, category pill top-right); **8 emotion-driven motion presets** rotated by scene; animated close scene with logo fade-in + text glow |
| 8 | `subtitle_generator` | Writes per-scene SRT files; Shorts captions at 75% frame height (clear of YouTube UI overlay) |
| 9 | `audio_processor` | **3-stage pipeline:** decode PCM → two-pass loudnorm −14 LUFS + afftdn noise reduction → fades + alimiter + M4A output; optional background music mix at −20 dB |
| 10 | `encoder` | Stream-copies assembled video + AAC-encodes audio; `apad` extends audio to video length; `-shortest` aligns at video end |
| 11 | `quality_gate` | **10 hard checks** — all must pass before upload; up to 3 retry attempts on failure |
| 12 | `thumbnail_generator` | Pillow-based 1280×720 thumbnail — blurred scene background, bold yellow CTR-psychology headline, logo bottom-left, category pill top-right |
| 13 | `uploader` | YouTube resumable upload; thumbnail; merged SRT captions; engagement comment; category playlist |
| 14 | `news_analytics` | Logs result; fetches audience retention curve; identifies drop-off positions; writes `performance_history.json` per category |

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
| Scale break | Compare scale to something familiar but make the comparison incomprehensible. |
| Tension gap | State something happened without explaining why. Open loop psychology. |
| Forbidden knowledge | Frame the fact as something suppressed or never taught. |

4 templates × 6 hook formulas = **24 unique structural combinations** per channel rotation.

### Global emotional arc

Each narrative template drives a planned emotion sequence across the full video — not just per-scene. The arc overrides LLM-assigned emotions to guarantee coherent emotional storytelling.

| Template | HOOK | TENSION | CORE | PAYOFF | CLOSE |
|----------|------|---------|------|--------|-------|
| classic | excited | mysterious | neutral | dramatic | excited |
| mystery | mysterious | dramatic | mysterious | excited | neutral |
| shock_first | dramatic | excited | neutral | dramatic | excited |
| reverse | dramatic | mysterious | neutral | excited | mysterious |

These emotions directly control TTS voice settings (step 4) and motion preset selection (step 7).

### Visual emotion intelligence

`scene_planner` scans the actual script text for 12 narrative trigger patterns and prepends emotionally-matched visual keywords before the static category banks.

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

Eight Ken Burns motion presets rotated by emotion tag + scene index — no two consecutive scenes use the same motion.

| Preset | Emotion | Use case |
|--------|---------|---------|
| `slow_drift` | neutral | Calm, beauty, payoff scenes |
| `push_in` | excited | Standard hook and tension |
| `impact_zoom` | dramatic | WOW moments, impact reveals |
| `reveal_pull` | mysterious | Mystery structure, reverse narrative |
| `pan_right` / `pan_left` | excited | Geography, exploration, scale |
| `rise_up` | neutral | Discovery, emergence, dawn |
| `descend` | mysterious | Underground, deep ocean, threat |

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

## Background music

Drop royalty-free audio files in `pipeline/assets/music/` — the pipeline auto-detects and mixes them at −20 dB under the voice track.

| File name | Used for |
|-----------|---------|
| `mysterious.mp3` | Mystery / reverse narrative videos |
| `excited.mp3` | Classic / shock-first videos |
| `dramatic.mp3` | Dramatic reveals and impact scenes |
| `neutral.mp3` | General fallback |

Music is lowpass-filtered at 12 kHz (never competes with voice clarity), faded in over 1.5 s, faded out over 2 s. Skipped automatically if directory is empty.

---

## Retention analytics

After each video, `news_analytics` fetches the YouTube audience retention curve and stores:

- Retention at 25% / 50% / 75% milestones
- Position and magnitude of the biggest single drop-off
- Retention signal: `early_drop` (hook/tension too slow) / `mid_drop` (CORE is losing viewers) / `late_drop` (payoff/close is weak) with an actionable fix hint

These signals feed `performance_history.json` to guide future category selection and will eventually drive automatic script parameter adjustments.

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

Selected by **performance weight** — categories with higher average retention are preferred. Deduplication runs against the full 12-month video history. Topic prompt uses trend-aware instructions to find fresh angles and recent discoveries.

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

| File | Purpose |
|------|---------|
| `pipeline/assets/logo.png` | Channel logo — PNG with transparency. Overlaid top-left on every video scene and bottom-left on thumbnails. Falls back to text pill if missing. |
| `pipeline/assets/music/*.mp3` | Background music tracks. Named by emotion. Skipped if directory is empty. |

---

## Schedule

| UTC | Cron | `VIDEO_FORMAT` | Output |
|-----|------|---------------|--------|
| 07:00 | `0 7 * * *` | `shorts` | ~60 s vertical Shorts (1080×1920) |
| 12:00 | `0 12 * * *` | `standard` | 3–5 min landscape (1920×1080) |
| 17:00 | `0 17 * * *` | `shorts` | ~60 s vertical Shorts (1080×1920) |

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

# Force a specific category
VIDEO_FORMAT=standard INTENT_OVERRIDE=SPACE python pipeline/main.py
```

Outputs land in `pipeline/output/`. Logs go to `pipeline/logs/`.

---

## Project structure

```
pipeline/
  main.py                    # Orchestrator — 14 steps, 3-attempt quality retry
  assets/
    logo.png                 # Channel logo (PNG with transparency)
    music/
      mysterious.mp3         # Background music — drop royalty-free files here
      excited.mp3
      dramatic.mp3
      neutral.mp3
  scripts/
    topic_selector.py        # Step 1  — trend-aware topic selection + dedup
    script_generator.py      # Step 2  — 4 templates × 6 hook formulas + CTR titles
    timeline_builder.py      # Step 3  — global emotional arc + Shorts psychology
    voice_generator.py       # Step 4  — emotion-tuned TTS + inter-scene silence
    scene_planner.py         # Step 5  — semantic text → emotional visual keywords
    visual_fetcher.py        # Step 6  — multi-keyword Pexels/Pixabay fetch
    video_assembler.py       # Step 7  — 8 motion presets + animated close scene
    subtitle_generator.py    # Step 8  — per-scene SRT with Shorts positioning
    audio_processor.py       # Step 9  — 3-stage normalize + background music mix
    encoder.py               # Step 10 — mux video + audio with apad sync
    quality_gate.py          # Step 11 — 10 hard checks, 3-attempt retry
    thumbnail_generator.py   # Step 12 — CTR headline + logo + Pillow thumbnail
    uploader.py              # Step 13 — upload + captions + comment + playlist
    news_analytics.py        # Step 14 — retention curve + drop-off analytics
  temp/                      # Runtime scratch (voice, visuals, scenes, subtitles)
  output/                    # Final MP4s + thumbnails
  logs/
    quality_failures.json    # Gate failures with attempt number and checks detail
    video_results.json       # Per-video upload log (last 200)
    performance_history.json # Per-category avg retention — drives topic selection
    analytics_data.json      # Raw YouTube Analytics + retention curve data
.github/workflows/
  news_video.yml             # Scheduled + manual dispatch (shorts/standard/long)
requirements.txt
```
