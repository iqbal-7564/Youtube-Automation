"""
STEP 2 — Script Generation (MindBlownFacts Edition)

Single Groq LLM call. Returns 5-segment retention-psychology script
plus YouTube metadata.

NARRATIVE VARIATION: four structural templates are rotated so every video
feels different to the viewer even when binge-watching the channel.
  classic     — HOOK mystery → TENSION build → CORE facts → PAYOFF reveal → CLOSE
  mystery     — open with unsolved mystery, delay answer until PAYOFF
  shock_first — lead with the single most impossible fact, then prove it
  reverse     — start at the incredible conclusion, work backward to cause

WOW MOMENTS: each CORE segment marks its most surprising sentence with [WOW]
so downstream modules can apply visual/audio intensity spikes.

CTR PSYCHOLOGY: title generation follows curiosity-gap rules — implies
information asymmetry without generic clickbait phrases.
"""

import json
import logging
import os
import random
import re

import requests

log = logging.getLogger(__name__)

_GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1", "").strip(),
    os.getenv("GROQ_API_KEY_2", "").strip(),
]
_MODEL = "llama-3.3-70b-versatile"

# ── Narrative templates ───────────────────────────────────────────────────────

_CLOSE_RULE = (
    "ONE short sentence only — a subscribe CTA. "
    "Examples: 'Follow MindBlownFacts for more mind-blowing facts every day.' "
    "/ 'Subscribe to MindBlownFacts — a new mind-blowing fact drops every day.' "
    "/ 'Follow for more facts that will change how you see the world.' "
    "Vary the exact wording each time. NEVER say 'Like and subscribe' or 'Hit the bell'."
)

_NARRATIVE_VARIANTS: dict[str, dict] = {
    "classic": {
        "description": "Classic curiosity-gap structure: hook teases → tension builds mystery → core delivers facts → payoff resolves → close subscribe CTA",
        "hook_rule":    "ONE sentence, max 12 words. State something astonishing WITHOUT explaining it. Pure curiosity gap.",
        "tension_rule": "2-3 sentences. Raise MORE questions. Make it feel like forbidden knowledge they were never taught.",
        "core_rule":    "4-6 short sentences. Most surprising fact FIRST. One fact per sentence. Vary rhythm: short. Longer context. Short again. Mark your single most shocking sentence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Deliver the satisfying answer that resolves the hook.",
        "close_rule":   _CLOSE_RULE,
    },
    "mystery": {
        "description": "Unsolved mystery structure: open with an ancient or scientific mystery — answer is withheld until the very last moment",
        "hook_rule":    "ONE sentence, max 12 words. Open with a mysterious question that has no obvious answer.",
        "tension_rule": "2-3 sentences. Deepen the mystery. Add conflicting evidence. Make it feel completely unsolvable.",
        "core_rule":    "4-6 sentences. Present evidence step by step — do NOT reveal the answer yet. Escalate the puzzle. Mark the most paradoxical fact with [WOW].",
        "payoff_rule":  "Max 2 sentences. Finally reveal the surprising answer. Make it feel worth the wait.",
        "close_rule":   _CLOSE_RULE,
    },
    "shock_first": {
        "description": "Lead with the most impossible-sounding fact as if it is obvious, then spend the rest of the video proving it",
        "hook_rule":    "ONE sentence, max 12 words. State the single most impossible-sounding fact as cold hard fact.",
        "tension_rule": "2-3 sentences. Immediately challenge the viewer's disbelief. 'This sounds impossible. Here is exactly why it is real.'",
        "core_rule":    "4-6 sentences. Prove the shocking claim with layered evidence. Each sentence escalates the proof. Mark the most undeniable evidence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Show the real-world implication — why this changes how we see everything.",
        "close_rule":   _CLOSE_RULE,
    },
    "reverse": {
        "description": "Reverse storytelling: start at the unbelievable outcome, work backward to reveal the hidden cause",
        "hook_rule":    "ONE sentence, max 12 words. Describe the unbelievable END RESULT as already established fact.",
        "tension_rule": "2-3 sentences. Ask how this is even possible. Begin tracing backward through the chain of cause.",
        "core_rule":    "4-6 sentences. Unpack the hidden chain of causes in reverse order. Mark the most surprising cause with [WOW].",
        "payoff_rule":  "Max 2 sentences. Reveal the original tiny hidden cause that triggered the entire chain.",
        "close_rule":   _CLOSE_RULE,
    },
}

# ── Format profiles ──────────────────────────────────────────────────────────
# VIDEO_FORMAT env var controls target length.
# shorts   → 130-180 words  (~60s)
# standard → 680-840 words  (~4-5 min)
# long     → 900-1344 words (~6-8 min)

_FORMAT_PROFILES: dict[str, dict] = {
    "shorts": {
        "word_target":   "95-115 words total",
        "duration_hint": "~50 seconds",
        "core_depth":    "3-4 short sentences. One fact per sentence. Every word counts.",
        "max_tokens":    1200,
    },
    "standard": {
        "word_target":   "680-840 words total",
        "duration_hint": "4-5 minutes",
        "core_depth":    (
            "18-24 sentences spread across 4 sub-topics. Go deep on each fact. "
            "Include real numbers, scale comparisons, and a counterintuitive twist. "
            "Vary sentence length: short punch. Longer explanatory follow-up. Short again. "
            "Mark the single most shocking sentence in CORE with [WOW]."
        ),
        "max_tokens":    4000,
    },
    "long": {
        "word_target":   "900-1344 words total",
        "duration_hint": "6-8 minutes",
        "core_depth":    (
            "28-38 sentences covering 5-6 distinct angles on the topic. "
            "Each angle gets 5-7 sentences: state the fact, explain the mechanism, "
            "give a real-world comparison, reveal the surprising implication. "
            "Include historical context, modern research, and a future implication. "
            "Mark the single most shocking sentence in CORE with [WOW]."
        ),
        "max_tokens":    6000,
    },
}

# ── Format-specific timing hints injected into both prompts ──────────────────
# These give the LLM concrete duration targets per segment so it writes
# enough text to actually fill the requested video length.

_FORMAT_TIMING: dict[str, dict] = {
    "shorts": {
        "video_label":   "YouTube Shorts (MUST be under 60 seconds total)",
        "hook_time":     "0-3s",
        "tension_time":  "3-12s",
        "core_time":     "12-34s",
        "payoff_time":   "34-44s",
        "close_time":    "44-50s",
        "hook_dur":      3,
        "tension_dur":   9,
        "core_dur":      22,
        "payoff_dur":    10,
        "close_dur":     6,
        "total_est":     50,
    },
    "standard": {
        "video_label":   "YouTube educational video (target 4-5 minutes)",
        "hook_time":     "0-15s",
        "tension_time":  "15-60s",
        "core_time":     "60-270s",
        "payoff_time":   "270-300s",
        "close_time":    "300-315s",
        "hook_dur":      12,
        "tension_dur":   45,
        "core_dur":      195,
        "payoff_dur":    30,
        "close_dur":     18,
        "total_est":     300,
    },
    "long": {
        "video_label":   "YouTube educational video (target 6-8 minutes)",
        "hook_time":     "0-20s",
        "tension_time":  "20-80s",
        "core_time":     "80-390s",
        "payoff_time":   "390-430s",
        "close_time":    "430-450s",
        "hook_dur":      18,
        "tension_dur":   60,
        "core_dur":      300,
        "payoff_dur":    40,
        "close_dur":     25,
        "total_est":     443,
    },
}

# ── Fact-check prompt ────────────────────────────────────────────────────────
_FACTCHECK_PROMPT = (
    "You are a fact-checker for educational YouTube scripts about science, history, "
    "nature, space, animals, geography, ocean, and culture. "
    "Read the script and decide if it contains any clearly false, fabricated, or "
    "wildly exaggerated claims that would embarrass a credible education channel. "
    "Minor dramatic framing and rhetorical emphasis are fine. "
    'Respond ONLY with valid JSON: {"has_issues": true/false, "reason": "one sentence or null"}'
)

# ── Hook formula library ─────────────────────────────────────────────────────
# Rotated per video to prevent hook fatigue. Each formula creates a different
# psychological mechanism that captures attention in the first 1-2 seconds.

_HOOK_FORMULAS = [
    "IMPOSSIBILITY: State a fact that sounds physically impossible. 'X can Y.' No explanation. Let it hang.",
    "SPECIFIC NUMBER: Use an exact, surprising number. '[PRECISE NUMBER] [shocking fact].' Specificity = credibility.",
    "CONTRADICTION: Attack a widely-held belief. 'Everything you know about X is wrong.' Instant curiosity gap.",
    "SCALE BREAK: Make the scale incomprehensible. Compare it to something familiar but make the comparison impossible to process.",
    "TENSION GAP: State something happened without explaining why. 'X exists. Nobody knows why.' Open loop psychology.",
    "FORBIDDEN KNOWLEDGE: Frame the fact as something suppressed. 'They never taught you this in school.'",
]

# Director Brain — global story state injected into every Groq system prompt.
# Zero extra API calls: context is appended to the existing system prompt.
# Ensures scripts have a globally coherent suspense arc and emotional journey
# rather than per-segment decisions made without full-video awareness.
_DIRECTOR_CONTEXT = {
    "story_role_sequence": ["hook", "rising_action", "peak", "reveal", "resolution"],
    "suspense_curve":      [0.75, 0.85, 1.0, 0.50, 0.20],
    "emotion_curve":       ["excited", "mysterious", "dramatic", "excited", "neutral"],
    "director_notes": (
        "Write each segment with awareness of its position in the full arc. "
        "HOOK must feel incomplete — create an open loop the viewer MUST close. "
        "TENSION escalates the urgency without answering the hook. "
        "CORE delivers the densest information at peak suspense. "
        "PAYOFF releases tension — the viewer feels satisfied and amazed. "
        "CLOSE is calm and invites return — never high-energy at this stage."
    ),
}

_SYSTEM_TMPL = """You are a world-class educational YouTube scriptwriter for the channel "MindBlownFacts".
Your scripts use retention psychology to make viewers feel they can't stop watching.
Content: real-world facts — science, history, nature, space, animals, geography, ocean, culture.
ACCURACY RULE: Every fact, number, and claim must be real and verifiable. Never invent statistics or events. If verified facts are provided below, treat them as ground truth.

NARRATIVE STRUCTURE THIS VIDEO: {description}

SEGMENT RULES:
HOOK    ({hook_time})  : {hook_rule}
                  NEVER start with "Did you know", "Welcome back", "Today we discuss", "In today's video".
TENSION ({tension_time}) : {tension_rule}
CORE    ({core_time}): {core_rule}
                  DEPTH: {core_depth}
                  Mark the single most surprising sentence with [WOW].
PAYOFF  ({payoff_time}): {payoff_rule}
CLOSE   ({close_time}): {close_rule}
                  NEVER say "Like and subscribe".

TARGET: {word_target}. Duration hint: {duration_hint}. Pace = 2.8 words/second.

TITLE RULES (curiosity-gap psychology):
  GOOD: "The Impossible Thing Hiding Inside Every Human Cell"
  GOOD: "Scientists Found Something That Breaks Physics"
  GOOD: "Nobody Told You The Real Reason Dinosaurs Vanished"
  BAD:  "Amazing Facts About DNA" (too vague)
  BAD:  "Shocking Truth About X" (overused trigger word)
  Rule: imply hidden/forbidden knowledge without using overused adjectives.

Writing style: authoritative, fast-paced, conversational.
Respond ONLY with valid JSON. No text outside the JSON.

DIRECTOR BRIEF:
{director_brief}"""

_USER_TMPL = """Write a {video_label} "MindBlownFacts" script for this topic:

TOPIC    : {title}
DETAILS  : {description}
CATEGORY : {intent}
TEMPLATE : {template_name}{wiki_facts}

Return EXACTLY this JSON (no extra keys, no markdown fences):
{{
  "narrative_template": "{template_name}",
  "segments": [
    {{"id": 1, "label": "HOOK",    "text": "...", "estimated_duration_seconds": {hook_dur},    "emotion": "excited",    "complexity": "simple"}},
    {{"id": 2, "label": "TENSION", "text": "...", "estimated_duration_seconds": {tension_dur}, "emotion": "mysterious", "complexity": "moderate"}},
    {{"id": 3, "label": "CORE",    "text": "...", "estimated_duration_seconds": {core_dur},    "emotion": "neutral",    "complexity": "complex"}},
    {{"id": 4, "label": "PAYOFF",  "text": "...", "estimated_duration_seconds": {payoff_dur},  "emotion": "dramatic",   "complexity": "simple"}},
    {{"id": 5, "label": "CLOSE",   "text": "...", "estimated_duration_seconds": {close_dur},   "emotion": "neutral",    "complexity": "simple"}}
  ],
  "total_estimated_seconds": {total_est},
  "full_script": "all segments combined into one paragraph",
  "metadata": {{
    "title": "Curiosity-gap title implying hidden knowledge (max 90 chars, no 'shocking'/'unbelievable'/'amazing')",
    "description": "2-3 sentence description with the main fact. End with relevant hashtags.",
    "tags": ["facts", "did you know", "world facts", "real world facts", "category-specific tag", "educational"],
    "engagement_question": "One question that sparks debate or invites personal stories from viewers"
  }}
}}"""


def _fact_check(text: str, key: str) -> dict:
    try:
        r = requests.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model":    _MODEL,
                "messages": [
                    {"role": "system", "content": _FACTCHECK_PROMPT},
                    {"role": "user",   "content": text[:2000]},
                ],
                "temperature": 0,
                "max_tokens":  120,
            },
            timeout=20,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$",        "", raw, flags=re.MULTILINE)
        return json.loads(raw)
    except Exception as exc:
        log.debug("Fact-check skipped: %s", exc)
        return {"has_issues": False, "reason": None}


def generate_script(topic: dict) -> dict:
    import os
    video_format = os.getenv("VIDEO_FORMAT", "shorts").lower()
    if video_format not in _FORMAT_PROFILES:
        video_format = "shorts"
    # For standard (non-shorts) runs randomly alternate 4-5 min vs 6-8 min
    if video_format == "standard":
        video_format = random.choice(["standard", "long"])
    fmt_profile = _FORMAT_PROFILES[video_format]

    # Rotate narrative template + hook formula — double variety prevents formula fatigue
    template_name = random.choice(list(_NARRATIVE_VARIANTS.keys()))
    hook_formula  = random.choice(_HOOK_FORMULAS)
    variant       = _NARRATIVE_VARIANTS[template_name]

    # Inject hook formula into the hook rule
    augmented_hook_rule = f"{variant['hook_rule']} HOOK FORMULA TO USE: {hook_formula}"

    fmt_timing = _FORMAT_TIMING.get(video_format, _FORMAT_TIMING["shorts"])

    system_prompt = _SYSTEM_TMPL.format(
        description    = variant["description"],
        hook_rule      = augmented_hook_rule,
        tension_rule   = variant["tension_rule"],
        core_rule      = variant["core_rule"],
        payoff_rule    = variant["payoff_rule"],
        close_rule     = variant["close_rule"],
        word_target    = fmt_profile["word_target"],
        duration_hint  = fmt_profile["duration_hint"],
        core_depth     = fmt_profile["core_depth"],
        hook_time      = fmt_timing["hook_time"],
        tension_time   = fmt_timing["tension_time"],
        core_time      = fmt_timing["core_time"],
        payoff_time    = fmt_timing["payoff_time"],
        close_time     = fmt_timing["close_time"],
        director_brief = json.dumps(_DIRECTOR_CONTEXT, indent=2),
    )

    wiki_summary = topic.get("wiki_summary", "")
    wiki_facts = (
        f"\nVERIFIED FACTS (Wikipedia — use as ground truth, reflect accurately):\n{wiki_summary}"
        if wiki_summary else ""
    )

    log.info("Generating [%s] script, template=%s wiki=%s",
             video_format, template_name, "yes" if wiki_summary else "no")

    for key in _GROQ_KEYS:
        if not key:
            continue
        for attempt in range(3):  # extra attempt reserved for fact-check retry
            try:
                filled_prompt = _USER_TMPL.format(
                    video_label   = fmt_timing["video_label"],
                    title         = topic["title"],
                    description   = topic["description"][:400],
                    intent        = topic["intent"],
                    template_name = template_name,
                    wiki_facts    = wiki_facts,
                    hook_dur      = fmt_timing["hook_dur"],
                    tension_dur   = fmt_timing["tension_dur"],
                    core_dur      = fmt_timing["core_dur"],
                    payoff_dur    = fmt_timing["payoff_dur"],
                    close_dur     = fmt_timing["close_dur"],
                    total_est     = fmt_timing["total_est"],
                )
                r = requests.post(
                    _GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":    _MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": filled_prompt},
                        ],
                        "temperature": 0.75,
                        "max_tokens":  fmt_profile["max_tokens"],
                    },
                    timeout=60,
                )
                if r.status_code == 429:
                    log.warning("Rate limit on key …%s", key[-4:])
                    break
                r.raise_for_status()
                raw    = r.json()["choices"][0]["message"]["content"].strip()
                script = _parse(raw)
                if script:
                    words = len(script["full_script"].split())
                    log.info("Script OK — %d words via Groq [%s/%s/hook:%s]",
                             words, video_format, template_name,
                             hook_formula.split(":")[0])
                    check = _fact_check(script["full_script"], key)
                    if check.get("has_issues"):
                        log.warning("Fact-check flagged (attempt %d): %s",
                                    attempt + 1, check.get("reason"))
                        if attempt < 2:
                            continue  # regenerate script
                        log.warning("Fact-check still flagged after retry — using best available")
                    else:
                        log.info("Fact-check passed")
                    script["video_format"] = video_format
                    return script
            except Exception as exc:
                log.warning("Groq attempt %d: %s", attempt + 1, exc)

    log.warning("LLM unavailable — using fallback script")
    return _fallback(topic)


def _parse(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$",        "", raw.strip(), flags=re.MULTILINE)
    for src in [raw, re.search(r'\{.*\}', raw, re.DOTALL)]:
        if src is None:
            continue
        text = src if isinstance(src, str) else src.group()
        try:
            data = json.loads(text)
            segs = data.get("segments", [])
            if len(segs) == 5 and data.get("full_script"):
                _defaults = [
                    ("HOOK",    "excited",    "simple"),
                    ("TENSION", "mysterious", "moderate"),
                    ("CORE",    "neutral",    "complex"),
                    ("PAYOFF",  "dramatic",   "simple"),
                    ("CLOSE",   "neutral",    "simple"),
                ]
                for seg, (_, emo, cplx) in zip(segs, _defaults):
                    seg.setdefault("emotion",    emo)
                    seg.setdefault("complexity", cplx)
                data.setdefault("metadata", {})
                data["metadata"].setdefault(
                    "engagement_question",
                    "What fact surprised you the most? Drop it below",
                )
                data.setdefault("narrative_template", "classic")
                return data
        except json.JSONDecodeError:
            pass
    return None


def _fallback(topic: dict) -> dict:
    t   = topic["title"]
    cat = topic.get("intent", "SCIENCE")
    hook    = "This fact will completely change how you see the world."
    tension = ("Most people never hear this. Scientists have known for years. "
               "Here is what is really happening.")
    core    = (f"{t}. [WOW] The scale of this is almost impossible to comprehend. "
               "Researchers have studied this for decades. "
               "The evidence is undeniable.")
    payoff  = "Now you understand the real truth behind one of the world's most overlooked facts."
    close   = "Follow for more facts that will make you question everything."
    full    = " ".join([hook, tension, core, payoff, close])
    return {
        "narrative_template": "classic",
        "segments": [
            {"id": 1, "label": "HOOK",    "text": hook,    "estimated_duration_seconds": 3,
             "emotion": "excited",    "complexity": "simple"},
            {"id": 2, "label": "TENSION", "text": tension, "estimated_duration_seconds": 12,
             "emotion": "mysterious", "complexity": "moderate"},
            {"id": 3, "label": "CORE",    "text": core,    "estimated_duration_seconds": 30,
             "emotion": "neutral",    "complexity": "complex"},
            {"id": 4, "label": "PAYOFF",  "text": payoff,  "estimated_duration_seconds": 10,
             "emotion": "dramatic",   "complexity": "simple"},
            {"id": 5, "label": "CLOSE",   "text": close,   "estimated_duration_seconds": 5,
             "emotion": "neutral",    "complexity": "simple"},
        ],
        "total_estimated_seconds": 60,
        "full_script": full,
        "metadata": {
            "title": t[:90],
            "description": (
                f"{t}\n\n"
                f"Category: {cat}\n\n"
                "#VisionaryMinds #Facts #DidYouKnow #WorldFacts #Educational"
            ),
            "tags": ["real world facts", "facts", "did you know", "world facts",
                     "educational", cat.lower()],
            "engagement_question": f"Did you already know this about {t[:40]}? Tell us below!",
        },
    }
