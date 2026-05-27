"""
STEP 2 — Script Generation

Single Groq LLM call. Returns 5-segment retention-psychology script
plus YouTube metadata. Batches title/description/tags in the same call.
"""

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

_GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1", ""),
    os.getenv("GROQ_API_KEY_2", ""),
]
_MODEL = "llama3-70b-8192"

_SYSTEM = """You are a professional news-video scriptwriter for YouTube Shorts.
Your scripts use retention psychology to keep viewers watching to the last second.

SEGMENT RULES:
HOOK    (0-3s)  : ONE sentence, max 12 words. Create a question in the viewer's mind WITHOUT answering it.
                  Use curiosity gap. NEVER start "In today's news", "Welcome back", "Today we discuss".
TENSION (3-15s) : 2-3 sentences. Expand the hook. Add stakes. Do NOT answer the hook. Raise MORE questions.
CORE    (15-45s): 4-6 short sentences. Facts ordered highest-impact first. One fact per sentence.
                  Vary length deliberately: short. Slightly longer for context. Short again.
PAYOFF  (45-55s): Max 2 sentences. Answer the hook question. Give the viewer clear value.
CLOSE   (55-60s): ONE sentence. Open loop hinting at future coverage.
                  NEVER say "Like and subscribe".

TARGET: 130-180 words total. Pace = 2.8 words/second.
Respond ONLY with valid JSON. No text outside the JSON."""

_USER_TMPL = """Write a YouTube Shorts news script for this story:

HEADLINE : {title}
DETAILS  : {description}
SOURCE   : {source}
INTENT   : {intent}

Also generate YouTube metadata in the same response.

Return EXACTLY this JSON (no extra keys, no markdown fences):
{{
  "segments": [
    {{"id": 1, "label": "HOOK",    "text": "...", "estimated_duration_seconds": 3}},
    {{"id": 2, "label": "TENSION", "text": "...", "estimated_duration_seconds": 12}},
    {{"id": 3, "label": "CORE",    "text": "...", "estimated_duration_seconds": 30}},
    {{"id": 4, "label": "PAYOFF",  "text": "...", "estimated_duration_seconds": 10}},
    {{"id": 5, "label": "CLOSE",   "text": "...", "estimated_duration_seconds": 5}}
  ],
  "total_estimated_seconds": 60,
  "full_script": "HOOK + TENSION + CORE + PAYOFF + CLOSE combined",
  "metadata": {{
    "title": "Hook phrase | Location Year  (max 95 chars, no 'shocking')",
    "description": "...",
    "tags": ["tag1", "tag2", "tag3"]
  }}
}}"""


def generate_script(topic: dict) -> dict:
    prompt = _USER_TMPL.format(
        title       = topic["title"],
        description = topic["description"][:400],
        source      = topic["source"],
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
                        "max_tokens":  1200,
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
    # Strip markdown fences
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
                return data
        except json.JSONDecodeError:
            pass
    return None


def _fallback(topic: dict) -> dict:
    t = topic["title"]
    s = topic.get("source", "sources")
    hook    = "What just happened will change everything."
    tension = (f"Reports are emerging from multiple {s} channels. "
               "The situation is still unfolding. Here is what we know so far.")
    core    = (f"{t}. Officials have confirmed the reports. "
               "Response teams are already mobilising. More information is coming in.")
    payoff  = "The full picture is now clear. This is a major developing story."
    close   = "This story is still developing — follow for live updates."
    full    = " ".join([hook, tension, core, payoff, close])
    return {
        "segments": [
            {"id": 1, "label": "HOOK",    "text": hook,    "estimated_duration_seconds": 3},
            {"id": 2, "label": "TENSION", "text": tension, "estimated_duration_seconds": 12},
            {"id": 3, "label": "CORE",    "text": core,    "estimated_duration_seconds": 30},
            {"id": 4, "label": "PAYOFF",  "text": payoff,  "estimated_duration_seconds": 10},
            {"id": 5, "label": "CLOSE",   "text": close,   "estimated_duration_seconds": 5},
        ],
        "total_estimated_seconds": 60,
        "full_script": full,
        "metadata": {
            "title":       t[:95],
            "description": (
                f"{t}\n\n"
                f"Source: {s} — {topic.get('article_url', '')}\n\n"
                "#VisionaryMinds #News #BreakingNews #WorldNews"
            ),
            "tags": ["news", "breaking news", "world news", "VisionaryMinds",
                     topic["intent"].lower()],
        },
    }
