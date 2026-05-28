"""
STEP 2 — Script Generation (Visionary Minds Edition)

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

_NARRATIVE_VARIANTS: dict[str, dict] = {
    "classic": {
        "description": "Classic curiosity-gap structure: hook teases → tension builds mystery → core delivers facts → payoff resolves → close teases next",
        "hook_rule":    "ONE sentence, max 12 words. State something astonishing WITHOUT explaining it. Pure curiosity gap.",
        "tension_rule": "2-3 sentences. Raise MORE questions. Make it feel like forbidden knowledge they were never taught.",
        "core_rule":    "4-6 short sentences. Most surprising fact FIRST. One fact per sentence. Vary rhythm: short. Longer context. Short again. Mark your single most shocking sentence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Deliver the satisfying answer that resolves the hook.",
        "close_rule":   "ONE sentence. Tease the NEXT mind-blowing fact they must see.",
    },
    "mystery": {
        "description": "Unsolved mystery structure: open with an ancient or scientific mystery — answer is withheld until the very last moment",
        "hook_rule":    "ONE sentence, max 12 words. Open with a mysterious question that has no obvious answer.",
        "tension_rule": "2-3 sentences. Deepen the mystery. Add conflicting evidence. Make it feel completely unsolvable.",
        "core_rule":    "4-6 sentences. Present evidence step by step — do NOT reveal the answer yet. Escalate the puzzle. Mark the most paradoxical fact with [WOW].",
        "payoff_rule":  "Max 2 sentences. Finally reveal the surprising answer. Make it feel worth the wait.",
        "close_rule":   "ONE sentence. Hint there is a DEEPER connected mystery.",
    },
    "shock_first": {
        "description": "Lead with the most impossible-sounding fact as if it is obvious, then spend the rest of the video proving it",
        "hook_rule":    "ONE sentence, max 12 words. State the single most impossible-sounding fact as cold hard fact.",
        "tension_rule": "2-3 sentences. Immediately challenge the viewer's disbelief. 'This sounds impossible. Here is exactly why it is real.'",
        "core_rule":    "4-6 sentences. Prove the shocking claim with layered evidence. Each sentence escalates the proof. Mark the most undeniable evidence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Show the real-world implication — why this changes how we see everything.",
        "close_rule":   "ONE sentence. Reveal there is an even more extreme version of this fact.",
    },
    "reverse": {
        "description": "Reverse storytelling: start at the unbelievable outcome, work backward to reveal the hidden cause",
        "hook_rule":    "ONE sentence, max 12 words. Describe the unbelievable END RESULT as already established fact.",
        "tension_rule": "2-3 sentences. Ask how this is even possible. Begin tracing backward through the chain of cause.",
        "core_rule":    "4-6 sentences. Unpack the hidden chain of causes in reverse order. Mark the most surprising cause with [WOW].",
        "payoff_rule":  "Max 2 sentences. Reveal the original tiny hidden cause that triggered the entire chain.",
        "close_rule":   "ONE sentence. Point out this exact hidden-cause pattern exists in something else entirely.",
    },
}

_SYSTEM_TMPL = """You are a world-class educational YouTube Shorts scriptwriter for the channel "Visionary Minds".
Your scripts use retention psychology to make viewers feel they can't stop watching.
Content: real-world facts — science, history, nature, space, animals, geography, ocean, culture.

NARRATIVE STRUCTURE THIS VIDEO: {description}

SEGMENT RULES:
HOOK    (0-3s)  : {hook_rule}
                  NEVER start with "Did you know", "Welcome back", "Today we discuss", "In today's video".
TENSION (3-15s) : {tension_rule}
CORE    (15-45s): {core_rule}
PAYOFF  (45-55s): {payoff_rule}
CLOSE   (55-60s): {close_rule}
                  NEVER say "Like and subscribe".

TARGET: 130-180 words total. Pace = 2.8 words/second.

TITLE RULES (curiosity-gap psychology):
  GOOD: "The Impossible Thing Hiding Inside Every Human Cell"
  GOOD: "Scientists Found Something That Breaks Physics"
  GOOD: "Nobody Told You The Real Reason Dinosaurs Vanished"
  BAD:  "Amazing Facts About DNA" (too vague)
  BAD:  "Shocking Truth About X" (overused trigger word)
  Rule: imply hidden/forbidden knowledge without using overused adjectives.

Writing style: authoritative, fast-paced, conversational.
Respond ONLY with valid JSON. No text outside the JSON."""

_USER_TMPL = """Write a YouTube Shorts "Visionary Minds" script for this topic:

TOPIC    : {title}
DETAILS  : {description}
CATEGORY : {intent}
TEMPLATE : {template_name}

Return EXACTLY this JSON (no extra keys, no markdown fences):
{{
  "narrative_template": "{template_name}",
  "segments": [
    {{"id": 1, "label": "HOOK",    "text": "...", "estimated_duration_seconds": 3,  "emotion": "excited",    "complexity": "simple"}},
    {{"id": 2, "label": "TENSION", "text": "...", "estimated_duration_seconds": 12, "emotion": "mysterious", "complexity": "moderate"}},
    {{"id": 3, "label": "CORE",    "text": "...", "estimated_duration_seconds": 30, "emotion": "neutral",    "complexity": "complex"}},
    {{"id": 4, "label": "PAYOFF",  "text": "...", "estimated_duration_seconds": 10, "emotion": "dramatic",   "complexity": "simple"}},
    {{"id": 5, "label": "CLOSE",   "text": "...", "estimated_duration_seconds": 5,  "emotion": "neutral",    "complexity": "simple"}}
  ],
  "total_estimated_seconds": 60,
  "full_script": "all segments combined into one paragraph",
  "metadata": {{
    "title": "Curiosity-gap title implying hidden knowledge (max 90 chars, no 'shocking'/'unbelievable'/'amazing')",
    "description": "2-3 sentence description with the main fact. End with relevant hashtags.",
    "tags": ["facts", "did you know", "world facts", "real world facts", "category-specific tag", "educational"],
    "engagement_question": "One question that sparks debate or invites personal stories from viewers"
  }}
}}"""


def generate_script(topic: dict) -> dict:
    # Rotate narrative template — variety prevents channel from feeling formulaic
    template_name = random.choice(list(_NARRATIVE_VARIANTS.keys()))
    variant       = _NARRATIVE_VARIANTS[template_name]
    system_prompt = _SYSTEM_TMPL.format(**variant)

    prompt = _USER_TMPL.format(
        title         = topic["title"],
        description   = topic["description"][:400],
        intent        = topic["intent"],
        template_name = template_name,
    )

    for key in _GROQ_KEYS:
        if not key:
            continue
        for attempt in range(2):
            try:
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
                            {"role": "user",   "content": prompt},
                        ],
                        "temperature": 0.75,
                        "max_tokens":  1500,
                    },
                    timeout=30,
                )
                if r.status_code == 429:
                    log.warning("Rate limit on key …%s", key[-4:])
                    break
                r.raise_for_status()
                raw    = r.json()["choices"][0]["message"]["content"].strip()
                script = _parse(raw)
                if script:
                    log.info("Script OK — %d words via Groq [%s]",
                             len(script["full_script"].split()), template_name)
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
