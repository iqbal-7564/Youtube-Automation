"""
STEP 2 — Script Generation (MindBlownFacts Edition)

Single Groq LLM call. Returns 5-segment retention-psychology script
plus YouTube metadata. Each segment now carries emotion + complexity tags
used downstream by voice_generator and timeline_builder.
"""

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

_GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1", "").strip(),
    os.getenv("GROQ_API_KEY_2", "").strip(),
]
_MODEL = "llama3-70b-8192"

_SYSTEM = """You are a world-class educational YouTube Shorts scriptwriter for the channel "MindBlownFacts".
Your scripts use retention psychology to make viewers feel they can't stop watching.
The content is always about fascinating real-world facts — science, history, nature, space, animals, geography, ocean, culture.

SEGMENT RULES:
HOOK    (0-3s)  : ONE sentence, max 12 words. Drop a mind-blowing fact or question that creates instant curiosity.
                  NEVER start with "Did you know", "Welcome back", "Today we discuss", "In today's video".
                  Use the curiosity gap — state something astonishing but don't explain it yet.
TENSION (3-15s) : 2-3 sentences. Expand on the hook with more surprising context. Raise MORE questions.
                  Make it feel like the viewer is about to discover something they were never taught in school.
CORE    (15-45s): 4-6 short sentences. The real facts, ordered most-surprising first. One fact per sentence.
                  Vary rhythm deliberately: short. Slightly longer to give context. Short again. Keep it punchy.
PAYOFF  (45-55s): Max 2 sentences. Deliver the satisfying explanation that answers the hook. Give clear value.
CLOSE   (55-60s): ONE sentence. Tease the next mind-blowing fact to keep them following.
                  NEVER say "Like and subscribe".

TARGET: 130-180 words total. Pace = 2.8 words/second.
Writing style: authoritative, fast-paced, conversational — like a brilliant friend who knows everything.
Respond ONLY with valid JSON. No text outside the JSON."""

_USER_TMPL = """Write a YouTube Shorts "MindBlownFacts" script for this topic:

TOPIC    : {title}
DETAILS  : {description}
CATEGORY : {intent}

Return EXACTLY this JSON (no extra keys, no markdown fences):
{{
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
    "title": "Short punchy title with the key fact (max 95 chars, no 'shocking' or 'unbelievable')",
    "description": "2-3 sentence description with the main fact. End with relevant hashtags.",
    "tags": ["facts", "did you know", "world facts", "real world facts", "category-specific tag", "educational"],
    "engagement_question": "One open question to pin as the first comment — invites viewer to respond"
  }}
}}"""


def generate_script(topic: dict) -> dict:
    prompt = _USER_TMPL.format(
        title       = topic["title"],
        description = topic["description"][:400],
        intent      = topic["intent"],
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
                            {"role": "system", "content": _SYSTEM},
                            {"role": "user",   "content": prompt},
                        ],
                        "temperature": 0.7,
                        "max_tokens":  1400,
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
                    log.info("Script OK — %d words via Groq",
                             len(script["full_script"].split()))
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
                # Back-fill emotion/complexity if LLM omitted them
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
                # Back-fill engagement_question
                data.setdefault("metadata", {})
                data["metadata"].setdefault(
                    "engagement_question",
                    "What fact surprised you the most? Drop it below 👇",
                )
                return data
        except json.JSONDecodeError:
            pass
    return None


def _fallback(topic: dict) -> dict:
    t   = topic["title"]
    cat = topic.get("intent", "SCIENCE")
    hook    = "This is one of the most incredible facts on Earth."
    tension = (f"Most people have never heard this. "
               "Scientists have known for decades, but it never made the headlines. "
               "Here is what is really going on.")
    core    = (f"{t}. The scale of this is hard to comprehend. "
               "Researchers have studied this phenomenon for years. "
               "The data confirms it beyond any doubt.")
    payoff  = "Now you know the truth behind one of the world's most overlooked facts."
    close   = "Follow for more mind-blowing real world facts every day."
    full    = " ".join([hook, tension, core, payoff, close])
    return {
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
            "title":               t[:95],
            "description": (
                f"{t}\n\n"
                f"Category: {cat}\n\n"
                "#MindBlownFacts #Facts #DidYouKnow #WorldFacts #Educational"
            ),
            "tags": ["real world facts", "facts", "did you know", "world facts",
                     "educational", "science facts", cat.lower()],
            "engagement_question": f"Did you already know this about {t[:40]}? Tell us below!",
        },
    }
