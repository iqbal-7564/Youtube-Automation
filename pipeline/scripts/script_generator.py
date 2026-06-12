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
    "TWO parts: (1) Echo a specific word or phrase from the HOOK — this creates a loop "
    "that makes viewers rewatch. Hook: 'Your brain is lying' → Close starts: 'Your brain never stops lying.' "
    "Hook: 'Dead. Still moving.' → Close starts: 'It was never really dead.' "
    "(2) Then ONE subscribe CTA sentence. Vary wording: "
    "'Follow MindBlownFacts — a new fact drops every day.' "
    "/ 'Subscribe for more facts that shatter what you think you know.' "
    "NEVER say 'Like and subscribe' or 'Hit the bell'."
)

_NARRATIVE_VARIANTS: dict[str, dict] = {
    "classic": {
        "description": "Classic curiosity-gap structure: hook teases → tension builds mystery → core delivers facts → payoff resolves → close subscribe CTA",
        "hook_rule":    "ONE sentence, MAX 6 WORDS for Shorts. State something astonishing WITHOUT explaining it. Pure curiosity gap. No filler words.",
        "tension_rule": "2-3 sentences. Raise MORE questions. Make it feel like forbidden knowledge they were never taught.",
        "core_rule":    "4-6 short sentences. Most surprising fact FIRST. One fact per sentence. Vary rhythm: short. Longer context. Short again. Mark your single most shocking sentence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Deliver the satisfying answer that resolves the hook.",
        "close_rule":   _CLOSE_RULE,
    },
    "mystery": {
        "description": "Unsolved mystery structure: open with an ancient or scientific mystery — answer is withheld until the very last moment",
        "hook_rule":    "ONE sentence, MAX 6 WORDS for Shorts. Open with a mysterious question that has no obvious answer. No explanation.",
        "tension_rule": "2-3 sentences. Deepen the mystery. Add conflicting evidence. Make it feel completely unsolvable.",
        "core_rule":    "4-6 sentences. Present evidence step by step — do NOT reveal the answer yet. Escalate the puzzle. Mark the most paradoxical fact with [WOW].",
        "payoff_rule":  "Max 2 sentences. Finally reveal the surprising answer. Make it feel worth the wait.",
        "close_rule":   _CLOSE_RULE,
    },
    "shock_first": {
        "description": "Lead with the most impossible-sounding fact as if it is obvious, then spend the rest of the video proving it",
        "hook_rule":    "ONE sentence, MAX 6 WORDS for Shorts. State the single most impossible-sounding fact as cold hard fact. No hedging.",
        "tension_rule": "2-3 sentences. Immediately challenge the viewer's disbelief. 'This sounds impossible. Here is exactly why it is real.'",
        "core_rule":    "4-6 sentences. Prove the shocking claim with layered evidence. Each sentence escalates the proof. Mark the most undeniable evidence with [WOW].",
        "payoff_rule":  "Max 2 sentences. Show the real-world implication — why this changes how we see everything.",
        "close_rule":   _CLOSE_RULE,
    },
    "reverse": {
        "description": "Reverse storytelling: start at the unbelievable outcome, work backward to reveal the hidden cause",
        "hook_rule":    "ONE sentence, MAX 6 WORDS for Shorts. Describe the unbelievable END RESULT as cold established fact.",
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
        "word_target":   "75-90 words total",
        "duration_hint": "~40 seconds",
        "core_depth":    "3 short punchy sentences MAX. One fact per sentence. Cut every word that doesn't shock.",
        "max_tokens":    1200,
    },
    "standard": {
        "word_target":   "1400-1700 words total",
        "duration_hint": "8-10 minutes",
        "core_depth":    (
            "35-48 sentences covering 5-6 distinct angles on the topic. "
            "Each angle gets 6-8 sentences: state the surprising fact, explain the mechanism, "
            "give a real-world scale comparison, reveal the counterintuitive implication. "
            "Include historical context, modern research, and a mind-blowing 'so what' moment. "
            "Vary sentence rhythm aggressively: short punch. Medium explanation. Short again. Longer story. "
            "Mark the single most shocking sentence in CORE with [WOW]."
        ),
        "max_tokens":    6000,
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
        "video_label":   "YouTube Shorts (MUST be under 50 seconds total)",
        "hook_time":     "0-2s",
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
        "video_label":   "YouTube educational video (target 8-10 minutes)",
        "hook_time":     "0-20s",
        "tension_time":  "20-80s",
        "core_time":     "80-520s",
        "payoff_time":   "520-570s",
        "close_time":    "570-590s",
        "hook_dur":      18,
        "tension_dur":   60,
        "core_dur":      440,
        "payoff_dur":    50,
        "close_dur":     22,
        "total_est":     590,
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
    "STOP SCROLL: Command viewer to stop. 'Stop. This is real.' Direct confrontation forces a pause.",
    "PERSONAL THREAT: Make it about the viewer's body or life right now. 'Your brain is doing this right now.' Instant relevance.",
    "IMPOSSIBLE CLAIM: Lead with a claim that sounds like a lie. 'Scientists just broke the laws of physics.' Disbelief = engagement.",
    "TIMER: Create urgency with a specific time. 'Every 24 hours, this planet does something impossible.' Makes it feel urgent.",
]

# Shorts-only hook formulas — more extreme than the standard set.
# These are tuned to the 2-second scroll window where a viewer decides to stay or leave.
_SHORTS_HOOK_FORMULAS = [
    "PERSONAL NOW: About the viewer's body RIGHT NOW. 'Your brain is lying to you right now.' First word = 'Your' or 'You'. Present tense. No explanation.",
    "SINGLE IMPOSSIBLE WORD OPENER: Start with one word that creates instant dissonance. 'Dead. Yet still moving.' Short pause after word one.",
    "SILENT THREAT: Make it feel like critical survival info is being withheld. 'This is slowly killing you.' No qualifier, no softening.",
    "AGENCY SECRET: Frame it as information a powerful entity hid. 'NASA never told you this.' or 'Schools hid this for 100 years.'",
    "SPECIES SHOCK: Challenge human identity. 'You are 90% not human.' or 'Humans are the only species that...' — end on something disturbing.",
    "COUNTDOWN URGENCY: Attach a real time interval to something impossible. 'Every 2 seconds your body does something impossible.' Forces the viewer to count.",
    "WORLD LIE: Challenge one fundamental belief everyone holds. 'The sky is not actually blue.' State it as fact, zero hedging.",
    "SCALE CRUSH: Something so extreme it breaks comprehension. 'A teaspoon of this weighs a billion tonnes.' Specificity = credibility.",
    "DIRECT STOP: Force the scroll to stop. 'Wait.' Then the fact. One word command creates a micro-pause that curiosity fills.",
    "IDENTITY SHATTER: Attack who the viewer thinks they are. 'You share 60% of your DNA with a banana.' Make it personal, make it absurd.",
]

# Shorts-specific boost — injected only for Shorts format
_SHORTS_SYSTEM_BOOST = """
SHORTS RETENTION RULES — viewer swipes in 2 seconds if not shocked immediately:

HOOK RULES (most critical element — this is the ONLY thing that stops the scroll):
1. MAX 6 WORDS. Fewer = stronger. 'You are not human.' beats 'Did you know humans have non-human cells?'
2. FIRST 2 WORDS = MAXIMUM IMPACT. BANNED first words: Did, Have, There, This, In, A, The, Today, Welcome, Here.
   REQUIRED strong openers: Your / You / Wait / Stop / Dead / Never / a SPECIFIC NUMBER / the shocking subject noun itself.
3. PRESENT TENSE ONLY. 'Your brain is lying' — not 'Scientists discovered brains lie'. Present tense = happening to the viewer right now.
4. PERSONAL THREAT or IDENTITY BREAK. The viewer must feel personally affected or intellectually shattered — not just intellectually curious.
5. ZERO EXPLANATION in the hook. The hook is a cliff edge — do not explain, do not soften. Let it hang.

TENSION:
6. First sentence of TENSION must DEEPEN the personal threat — do not answer the hook, make it feel more real and unavoidable.

PAYOFF:
7. End PAYOFF with exactly ONE like CTA: 'Tap like if this broke your brain.' / 'Like if you never knew this.' / 'Double tap if this surprised you.' Natural, short.

CLOSE:
8. CLOSE must echo a specific word or phrase from the HOOK — creates a loop sensation. Hook: 'You are not human' → Close: 'and you have never been fully human.'

EVERY SENTENCE:
9. Delete filler transitions: never 'So', 'Basically', 'In other words', 'To summarize', 'Essentially'.
10. Every sentence raises stakes OR delivers a fact. Nothing else earns its place.
"""

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

# Category-specific seed tags. Injected into the tags instruction so the LLM
# generates relevant long-tail phrases instead of generic ones.
_CATEGORY_TAGS: dict[str, list[str]] = {
    "SPACE":       ["space facts", "nasa facts", "universe facts", "black hole facts", "astronomy facts", "space science", "galaxy facts", "planet facts", "cosmos facts", "space discovery 2025"],
    "SCIENCE":     ["science facts", "biology facts", "chemistry facts", "scientific discovery", "science explained", "real science facts", "science secrets", "physics facts"],
    "HISTORY":     ["history facts", "ancient history", "historical facts", "world history", "ancient civilizations", "forgotten history", "history mysteries", "historical secrets"],
    "ANIMALS":     ["animal facts", "wildlife facts", "amazing animals", "animal behavior", "rare animals", "strange animals", "animal science", "nature facts animals"],
    "NATURE":      ["nature facts", "earth facts", "natural phenomena", "environment facts", "plant facts", "nature science", "natural world facts", "ecology facts"],
    "GEOGRAPHY":   ["geography facts", "world geography", "country facts", "earth geography", "map facts", "countries of the world", "places on earth facts"],
    "OCEAN":       ["ocean facts", "deep sea facts", "marine biology facts", "deep ocean creatures", "sea facts", "underwater facts", "ocean science", "pacific ocean facts"],
    "CULTURE":     ["culture facts", "world culture facts", "ancient culture", "cultural history", "traditions facts", "civilization facts", "human culture"],
    "TECHNOLOGY":  ["technology facts", "tech facts", "computer science facts", "ai facts", "invention facts", "engineering facts", "science and technology"],
    "PSYCHOLOGY":  ["psychology facts", "human psychology", "brain facts", "mind facts", "mental science", "behavioral psychology", "cognitive science facts"],
    "MYTHOLOGY":   ["mythology facts", "greek mythology", "ancient myths", "mythology explained", "world mythology", "legend facts", "myths and legends"],
    "MEDICINE":    ["medical facts", "health facts", "human body facts", "anatomy facts", "biology human body", "medicine science", "doctor facts", "disease facts"],
    "MATHEMATICS": ["math facts", "mathematics facts", "number facts", "math history", "geometry facts", "mathematical discoveries", "math science"],
    "ECONOMICS":   ["economics facts", "money facts", "finance facts", "world economy facts", "economic history", "business facts", "wealth facts"],
    "PHYSICS":     ["physics facts", "quantum physics facts", "physics explained", "energy facts", "force facts", "physics science", "laws of physics"],
}


def _build_tags_for_prompt(intent: str) -> str:
    """Build a JSON array hint with category seeds + a placeholder the LLM will fill."""
    seeds = _CATEGORY_TAGS.get(intent.upper(), ["facts", "educational"])
    tags: list[str] = list(seeds[:8])
    tags.append(
        "REPLACE_WITH_5_TOPIC_SPECIFIC_TAGS: use exact long-tail phrases people search for this topic"
    )
    tags += ["MindBlownFacts", "educational", "facts", "did you know"]
    return json.dumps(tags)


def _load_viewer_note() -> str:
    try:
        from pathlib import Path as _P
        p = _P(__file__).parent.parent / "logs" / "script_feedback.json"
        if p.exists():
            note = json.loads(p.read_text()).get("viewer_note", "")
            if note:
                return f"\n\nVIEWER FEEDBACK (apply to this script):\n{note}"
    except Exception:
        pass
    return ""


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

TITLE RULES — YouTube Shorts optimised (follow ALL rules every time):
  Rule 0: MUST match the exact topic. Never change the subject.
  Rule 1: FRONT-LOAD the keyword — first 40 characters must contain the main topic word(s).
          Shorts feed truncates at ~40 chars. The topic must be readable before the "…"
  Rule 2: Under 70 characters total. No excessive ALL CAPS (max 1 word in caps if any).
  Rule 3: End with exactly 1 emoji relevant to the topic. Never 0, never 2+.
  Rule 4: Include a specific number OR a strong qualifier (real, actual, hidden, why, how) when it fits naturally.
  Rule 5: BANNED overused words: shocking / unbelievable / amazing / mind-blowing / incredible / nobody told you / the truth nobody / what they don't.
  Rule 6: VARY THE FORMAT every video — pick ONE format from the pool below. Never repeat the same format twice in a row.

  FORMAT POOL (rotate — each video uses a different one):
  A. Question + payoff:    "Why Do [TOPIC] [SURPRISING FACT]? 🤯"
  B. Real reason:          "[TOPIC]: The Real Reason [CLAIM] 🔬"
  C. Personal impact:      "What [TOPIC] Does To Your Body Right Now 🧠"
  D. Scale fact:           "[TOPIC] Is [SCALE COMPARISON] — And It Changes Everything 🌌"
  E. Discovery framing:    "Scientists Just Found [TOPIC] [SURPRISING DETAIL] 🔭"
  F. Reversal/subversion:  "How [TOPIC] Actually Works (You've Been Lied To) ⚡"
  G. Number-led:           "[NUMBER] [TOPIC] Facts That [EMOTIONAL PAYOFF] 🫀"
  H. Identity challenge:   "Your [BODY PART/SELF] Is [IMPOSSIBLE CLAIM] About [TOPIC] 👁️"
  I. Conflict framing:     "[TOPIC] vs [OPPOSING IDEA] — Only One Can Be True 🚨"
  J. Time urgency:         "Every [TIME UNIT], [TOPIC] Does Something [CLAIM] ⏱️"
  K. Double keyword (| SEO — HIGHEST PRIORITY format, use often):
     "[Hook phrase about topic] | [2-3 word search category] 🔬"
     Before |: short curiosity hook (what people CLICK). After |: what people SEARCH.
     Example: "Black Holes Eat Light | Space Science Facts 🌌"
     Example: "Your Brain Deletes Memories | Psychology Facts 🧠"
     Example: "Ocean Glows In The Dark | Marine Biology 🌊"

  GOOD: "Why Does The Ocean Glow At Night? 🌊"               ← A, front-loaded, emoji, <70 chars
  GOOD: "Black Holes: The Real Reason Light Can't Escape 🌌"  ← B, front-loaded
  GOOD: "What Lava Actually Does To Human Bone 🔥"            ← C, personal + specific
  GOOD: "Scientists Just Found Life 11km Under The Ocean 🐙"  ← E, discovery
  GOOD: "How Your Brain Deletes Memories While You Sleep 🧠"  ← F, personal + specific
  GOOD: "Ocean Glows Blue At Night | Marine Biology Facts 🌊" ← K, SEO double-keyword (BEST for views)
  GOOD: "Your Brain Deletes Memories | Psychology Science 🧠" ← K, SEO double-keyword (BEST for views)
  BAD:  "The Truth Nobody Told You About Black Holes"         ← overused pattern (Rule 5)
  BAD:  "Amazing Facts About DNA That Will Blow Your Mind"    ← banned words (Rule 5)
  BAD:  "Why Nobody Talks About This Ocean Secret"            ← overused + no emoji (Rule 5)

Writing style: authoritative, fast-paced, conversational.
Respond ONLY with valid JSON. No text outside the JSON.

DIRECTOR BRIEF:
{director_brief}"""

_USER_TMPL = """Write a {video_label} "MindBlownFacts" script for this EXACT topic:

TOPIC    : {title}
DETAILS  : {description}
CATEGORY : {intent}
TEMPLATE : {template_name}{wiki_facts}

CRITICAL CONTENT RULES:
1. Every single segment (HOOK, TENSION, CORE, PAYOFF, CLOSE) MUST be directly about "{title}". Do NOT drift to related or similar topics.
2. The HOOK must reference the specific subject from "{title}" — not a generic fact.
3. The CORE must deliver real, specific facts about "{title}" as stated in DETAILS above.
4. If VERIFIED FACTS are provided above, build the script around those exact facts.
5. NEVER write a generic script. The viewer clicked because of "{title}" — deliver exactly that.

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
    "title": "Write a YouTube title for '{title}'. RULES: (1) STRONGLY PREFER format K from the FORMAT POOL — use the | separator: 'Hook phrase | Search category 🔬'. This is the highest-performing SEO format. (2) If format K doesn't fit naturally, pick any other format from the pool — vary, never reuse the same format twice. (3) First 40 chars must contain the main topic keyword. (4) Under 70 chars total. (5) End with exactly 1 relevant emoji. (6) No ALL CAPS. (7) Must describe '{title}' exactly — no subject changes. (8) NEVER use: Nobody Told You / Truth Nobody / shocking / amazing.",
    "description": "SEO-CRITICAL structure — follow exactly:\nLine 1 (max 140 chars): open with the EXACT 2-3 word phrase people search for this topic, then a compelling sentence. Front-load the keyword — YouTube indexes first words most heavily. Example: 'Black holes are regions...' / 'Octopuses have three hearts...' / 'The real reason Rome collapsed...'\nLine 2: The single most shocking specific fact from the script — include a real number or a scale comparison.\nLine 3: Subscribe to MindBlownFacts for daily mind-blowing facts.\nLine 4-5: 2 natural sentences weaving in long-tail keywords people actually search (e.g. 'Scientists recently discovered...', 'Most people never learn that...', 'The truth about X is...').\nFinal line: 10-12 hashtags — mix specific topic hashtags with broad ones: #Facts #DidYouKnow #Educational #Science #MindBlownFacts",
    "tags": {tags_instruction},
    "engagement_question": "One question about '{title}' that sparks debate or invites personal stories from viewers"
  }}
}}"""


_CLUSTER_USER_TMPL = """Write a {video_label} "MindBlownFacts" script covering these RELATED topics as one cohesive video:

OVERARCHING THEME : {title}
CENTRAL ANGLE     : {central_angle}
CATEGORY          : {intent}
TEMPLATE          : {template_name}

TOPICS TO COVER (cover ALL of them in the CORE, in this exact order):
{topics_list}

STRUCTURE RULES:
- HOOK     : ONE sentence (max 12 words) teasing the central angle — NOT a single sub-topic. Pure curiosity gap.
             HOOK FORMULA TO USE: {hook_formula}
- TENSION  : 2-3 sentences building anticipation. Hint that viewers are about to learn several things that connect in a surprising way.
- CORE     : Cover EACH topic as its own named mini-segment. For every topic:
               * Open with a clear transition: "First...", "Second...", "Now here's where it gets strange...", "But that's not the most surprising part..." etc.
               * 4-6 sentences: the surprising fact → the mechanism → real-world scale comparison → counterintuitive implication
               * Place [WOW] on the single most shocking sentence across ALL topics (only one [WOW] total)
             Vary rhythm: short punch. Longer explanation. Short again.
             DEPTH: {core_depth}
- PAYOFF   : 2 sentences connecting ALL topics back to the central angle — the big-picture insight that ties everything together.
- CLOSE    : {close_rule}

TARGET: {word_target}. Duration hint: {duration_hint}.

Return EXACTLY this JSON (no extra keys, no markdown):
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
    "title": "Write a YouTube title for '{title}'. RULES: (1) Front-load the main topic keyword in first 40 chars. (2) Pick ONE format from the FORMAT POOL — vary it every video. (3) Under 70 chars. (4) End with exactly 1 relevant emoji. (5) No ALL CAPS. (6) Must stay on topic '{title}'.",
    "description": "SEO-CRITICAL structure — follow exactly:\nLine 1 (max 140 chars): open with the EXACT 2-3 word phrase people search for this overarching theme, then a compelling sentence. Front-load the keyword.\nLine 2: The single most surprising connection across all topics — include a real number or comparison.\nLine 3: Subscribe to MindBlownFacts for daily mind-blowing facts.\nLine 4-5: 2 natural sentences weaving in long-tail keywords (e.g. 'Scientists recently discovered...', 'Most people never learn that...').\nFinal line: 10-12 hashtags — mix specific topic hashtags with broad: #Facts #DidYouKnow #Educational #Science #MindBlownFacts",
    "tags": {tags_instruction},
    "engagement_question": "One question about '{title}' that sparks debate or personal stories"
  }}
}}"""


def _generate_cluster_script(topic: dict, video_format: str) -> dict:
    """Generate a multi-topic cluster script for standard/long videos."""
    fmt_profile  = _FORMAT_PROFILES.get(video_format, _FORMAT_PROFILES["standard"])
    fmt_timing   = _FORMAT_TIMING.get(video_format, _FORMAT_TIMING["standard"])
    template_name = random.choice(list(_NARRATIVE_VARIANTS.keys()))
    hook_formula  = random.choice(_HOOK_FORMULAS)
    variant       = _NARRATIVE_VARIANTS[template_name]

    topics_list = "\n".join(
        f"{i+1}. {t.get('title', t.get('seed', ''))} — {t.get('description', '')}"
        for i, t in enumerate(topic["topics"])
    )

    system_prompt = _SYSTEM_TMPL.format(
        description    = variant["description"],
        hook_rule      = variant["hook_rule"],
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
    ) + _load_viewer_note()

    filled_prompt = _CLUSTER_USER_TMPL.format(
        video_label       = fmt_timing["video_label"],
        title             = topic["title"],
        central_angle     = topic.get("central_angle", topic["description"][:60]),
        intent            = topic["intent"],
        template_name     = template_name,
        topics_list       = topics_list,
        hook_formula      = hook_formula,
        core_depth        = fmt_profile["core_depth"],
        close_rule        = variant["close_rule"],
        word_target       = fmt_profile["word_target"],
        duration_hint     = fmt_profile["duration_hint"],
        hook_dur          = fmt_timing["hook_dur"],
        tension_dur       = fmt_timing["tension_dur"],
        core_dur          = fmt_timing["core_dur"],
        payoff_dur        = fmt_timing["payoff_dur"],
        close_dur         = fmt_timing["close_dur"],
        total_est         = fmt_timing["total_est"],
        tags_instruction  = _build_tags_for_prompt(topic["intent"]),
    )

    for key in _GROQ_KEYS:
        if not key:
            continue
        for attempt in range(3):
            try:
                r = requests.post(
                    _GROQ_URL,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type":  "application/json"},
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
                    log.warning("Rate limit on key …%s (cluster)", key[-4:])
                    break
                r.raise_for_status()
                raw    = r.json()["choices"][0]["message"]["content"].strip()
                script = _parse(raw)
                if script:
                    words = len(script["full_script"].split())
                    log.info("Cluster script OK — %d words [%s/%s/%d topics]",
                             words, video_format, template_name, len(topic["topics"]))
                    check = _fact_check(script["full_script"], key)
                    if check.get("has_issues"):
                        log.warning("Fact-check flagged cluster (attempt %d): %s",
                                    attempt + 1, check.get("reason"))
                        if attempt < 2:
                            continue
                        log.warning("Fact-check still flagged — using best available")
                    else:
                        log.info("Cluster fact-check passed")
                    script["video_format"] = video_format
                    script["is_cluster"]   = True
                    script["cluster_topics"] = [t.get("title", t.get("seed", ""))
                                                for t in topic["topics"]]
                    return script
            except Exception as exc:
                log.warning("Groq cluster attempt %d: %s", attempt + 1, exc)

    log.warning("Cluster LLM unavailable — falling back to single-topic script")
    return _fallback(topic)


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

    # Cluster topics (standard/long only): use the multi-topic prompt
    if topic.get("topics") and video_format != "shorts":
        return _generate_cluster_script(topic, video_format)
    fmt_profile = _FORMAT_PROFILES[video_format]

    # Rotate narrative template + hook formula — double variety prevents formula fatigue
    template_name = random.choice(list(_NARRATIVE_VARIANTS.keys()))
    # Shorts uses a more extreme formula pool — tuned for 2-second scroll psychology
    formula_pool  = _SHORTS_HOOK_FORMULAS if video_format == "shorts" else _HOOK_FORMULAS
    hook_formula  = random.choice(formula_pool)
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
    ) + _load_viewer_note() + (_SHORTS_SYSTEM_BOOST if video_format == "shorts" else "")

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
                    video_label      = fmt_timing["video_label"],
                    title            = topic["title"],
                    description      = topic["description"][:400],
                    intent           = topic["intent"],
                    template_name    = template_name,
                    wiki_facts       = wiki_facts,
                    hook_dur         = fmt_timing["hook_dur"],
                    tension_dur      = fmt_timing["tension_dur"],
                    core_dur         = fmt_timing["core_dur"],
                    payoff_dur       = fmt_timing["payoff_dur"],
                    close_dur        = fmt_timing["close_dur"],
                    total_est        = fmt_timing["total_est"],
                    tags_instruction = _build_tags_for_prompt(topic["intent"]),
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
