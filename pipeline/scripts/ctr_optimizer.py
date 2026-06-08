"""
CTR OPTIMIZER — Combined title + thumbnail headline synergy scoring

Title and thumbnail must tell DIFFERENT parts of the same story:
  Title:     creates curiosity gap (what is the mystery?)
  Thumbnail: creates visual tension (I have to see this)

If they repeat each other, the viewer gets no additional reason to click.
If they're synergistic, each one amplifies the other's pull.

SCORING CRITERIA (0–10 each):
  curiosity_gap    — implies hidden/forbidden knowledge
  emotional_tension — creates anxiety to find out
  specificity       — concrete facts beat vague claims
  length_fit        — title ≤ 90 chars, headline ≤ 72 chars
  synergy           — title + thumbnail tell complementary stories
  novelty           — avoids overused patterns (shocking, amazing, unbelievable)

Returns the highest-scoring (title, headline) pair.
"""

import logging
import re

log = logging.getLogger(__name__)

# Words that indicate curiosity-gap psychology is already present
_CURIOSITY_WORDS = {
    "hidden", "secret", "impossible", "nobody", "real reason", "truth",
    "actually", "scientists", "discovered", "found", "never taught",
    "what really", "why really", "how really", "until now", "breaking",
    "just discovered", "they hid", "suppressed", "unknown",
}

# Overused / penalised patterns
_WEAK_PATTERNS = {
    "shocking", "amazing", "incredible", "unbelievable", "mind blowing",
    "you won't believe", "wait until", "top 10", "list of", "facts about",
    "interesting facts", "did you know that", "here are",
}

# Power words that score high
_POWER_WORDS = {
    "impossible", "hidden", "real", "secret", "nobody", "scientists",
    "discovered", "found", "breaks", "never", "forbidden", "suppressed",
    "actual", "truth", "real reason", "not what",
}

# ── Scoring functions ─────────────────────────────────────────────────────────

def _score_curiosity(text: str) -> float:
    t = text.lower()
    score = sum(1.0 for w in _CURIOSITY_WORDS if w in t)
    return min(score * 3.0, 10.0)


def _score_tension(text: str) -> float:
    """Emotional tension = does the text make you anxious to find out more?"""
    t = text.lower()
    tension_patterns = [
        r"\?$",                          # ends with question
        r"(nobody|no one).*(know|told|taught)",
        r"(real|actual|true).*(reason|truth|cause)",
        r"(scientists|researchers).*(found|discovered)",
        r"(hidden|secret|forbidden)",
        r"(impossible|can\'t exist|shouldn\'t)",
        r"(changes|breaks|defies).*(everything|physics|reality)",
    ]
    score = 0.0
    for p in tension_patterns:
        if re.search(p, t):
            score += 1.4
    return min(score, 10.0)


def _score_specificity(text: str) -> float:
    """Specific numbers and facts score higher than vague claims."""
    score = 0.0
    if re.search(r'\d+', text):         score += 3.0   # has a number
    if re.search(r'\d+[,.]?\d*\s*(million|billion|trillion|thousand|percent|%|km|kg|mph|ly)', text.lower()):
        score += 2.0                                    # has a unit
    if len(text.split()) >= 6:          score += 2.0   # not too short
    if len(text.split()) >= 10:         score += 1.0   # detailed enough
    return min(score, 10.0)


def _score_length(text: str, max_len: int) -> float:
    n = len(text)
    if n > max_len:      return 0.0
    if n < 20:           return 3.0   # too short
    if n <= max_len * 0.7: return 8.0
    return 10.0


def _score_novelty(text: str) -> float:
    """Penalise overused phrases."""
    t = text.lower()
    penalty = sum(1.0 for w in _WEAK_PATTERNS if w in t)
    return max(0.0, 10.0 - penalty * 4.0)


def _score_synergy(title: str, headline: str) -> float:
    """
    Title and headline should share the same TOPIC but different ANGLES.
    High synergy = they're about the same thing but each reveals something new.
    Low synergy = they're identical (redundant) or completely unrelated.
    """
    t_words = set(title.lower().split())
    h_words = set(headline.lower().split())
    # Remove stopwords
    stopwords = {"the", "a", "an", "is", "it", "in", "of", "and", "to", "that", "this"}
    t_words -= stopwords
    h_words -= stopwords

    if not t_words or not h_words:
        return 5.0

    overlap = len(t_words & h_words) / max(len(t_words), len(h_words))

    # Ideal overlap: 20–50% (share topic, not words)
    if 0.20 <= overlap <= 0.50:
        return 10.0
    elif overlap < 0.10:
        return 3.0    # too unrelated
    elif overlap > 0.80:
        return 2.0    # too redundant
    else:
        return 6.0


def _total_score(title: str, headline: str) -> float:
    # Curiosity-gap + tension drive >60% of CTR decisions on YouTube
    return (
        _score_curiosity(title)         * 0.30 +
        _score_tension(title)           * 0.25 +
        _score_specificity(title)       * 0.10 +
        _score_length(title, 90)        * 0.05 +
        _score_novelty(title)           * 0.15 +
        _score_synergy(title, headline) * 0.15
    )


# ── Candidate generation ──────────────────────────────────────────────────────

def _generate_title_variants(title: str, hook_text: str) -> list[str]:
    """Generate up to 4 title variants — always include a question-format version."""
    variants = [title]
    title_lower = title.lower()

    # Variant 2: question-format only for noun-phrase titles (short, no conjugated verb)
    _verb_mid = re.compile(r"\b(are|is|was|were|have|has|had|fell|died|broke|happened)\b")
    if not re.match(r"^(why|how|what|where|when|who)\b", title_lower) and not _verb_mid.search(title_lower):
        base = title.rstrip(".!?")
        if re.search(r"\b(real|truth|hidden|secret|actual)\b", title_lower):
            variants.append(f"Why {base}?")
        elif len(title.split()) <= 6:
            variants.append(f"How Does {base} Actually Work?")

    # Variant 3: "Nobody told you" framing — strong curiosity gap
    has_power = any(w in title_lower for w in _POWER_WORDS)
    if not has_power:
        # Strip question starters + auxiliaries to get the topic noun phrase
        _strip = r"^(why |how |what |where |when |who |does |do |did |is |are |was |were |can |will |should |the |a |an )+"
        core_phrase = re.sub(_strip, "", title_lower, flags=re.I).rstrip(".!?")
        variants.append(f"Nobody Told You The Truth About {core_phrase.title()}")

    # Variant 4: hook-sentence trimmed to title length (often strongest)
    hook_words = hook_text.split()[:14]
    hook_snippet = " ".join(hook_words).rstrip(".!?,")
    if hook_snippet and len(hook_snippet) >= 20 and hook_snippet.lower() != title_lower:
        variants.append(hook_snippet)

    # Deduplicate and cap
    seen: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.append(v)
    return seen[:4]


def _generate_headline_variants(title: str, hook_text: str) -> list[str]:
    """Generate up to 4 thumbnail headline variants (used as text overlay)."""
    variants: list[str] = []

    # Variant 1: extract 1-2 power-word-rich words from title — short punchy overlay
    title_lower = title.lower()
    punch_words = [
        w.upper() for w in title.split()
        if re.sub(r"[^a-z]", "", w.lower()) in _POWER_WORDS
    ][:2]
    if punch_words:
        variants.append(" ".join(punch_words))

    # Variant 2: question from first 7 words of title
    words = title.split()
    if len(words) >= 5:
        variants.append(" ".join(words[:7]).rstrip(".!?,") + "?")

    # Variant 3: hook's first clause — often the most visceral sentence
    hook_short = re.split(r"[.!?]", hook_text.strip())[0].strip()
    if hook_short and hook_short not in variants:
        variants.append(hook_short[:72])

    # Variant 4: title truncated (safe fallback)
    variants.append(title[:72])

    seen: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.append(v)
    return [v[:72] for v in seen[:4]]


# ── Public API ────────────────────────────────────────────────────────────────

def optimize_ctr(title: str, hook_text: str, intent: str) -> dict:
    """
    Score all (title_variant, headline_variant) combinations and return
    the highest-scoring pair plus individual scores for logging.

    Returns:
        {title, headline, score, title_score, headline_score}
    """
    title_variants    = _generate_title_variants(title, hook_text)
    headline_variants = _generate_headline_variants(title, hook_text)

    best_score = -1.0
    best_title = title
    best_headline = title[:72]

    for t in title_variants:
        for h in headline_variants:
            score = _total_score(t, h)
            if score > best_score:
                best_score    = score
                best_title    = t
                best_headline = h

    log.info("CTR optimizer: score=%.2f title='%s…'", best_score, best_title[:50])

    return {
        "title":          best_title[:90],
        "headline":       best_headline[:72],
        "ctr_score":      round(best_score, 3),
        "title_curiosity": round(_score_curiosity(best_title), 2),
        "title_tension":   round(_score_tension(best_title), 2),
        "synergy":         round(_score_synergy(best_title, best_headline), 2),
    }
