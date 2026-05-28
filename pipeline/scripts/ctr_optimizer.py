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
    return (
        _score_curiosity(title)    * 0.25 +
        _score_tension(title)      * 0.20 +
        _score_specificity(title)  * 0.10 +
        _score_length(title, 90)   * 0.10 +
        _score_novelty(title)      * 0.15 +
        _score_synergy(title, headline) * 0.20
    )


# ── Candidate generation ──────────────────────────────────────────────────────

def _generate_title_variants(title: str, hook_text: str) -> list[str]:
    """Generate up to 3 title variants from the base title and hook text."""
    variants = [title]

    # Variant 2: curiosity-frame if base lacks power words
    title_lower = title.lower()
    has_power = any(w in title_lower for w in _POWER_WORDS)
    if not has_power:
        topic = title.rstrip(".")
        variants.append(f"The Real Reason {topic} Changes Everything")

    # Variant 3: hook-derived (use first 10 words of hook if it's stronger)
    hook_words = hook_text.split()[:12]
    hook_snippet = " ".join(hook_words).rstrip(".")
    if hook_snippet and len(hook_snippet) > 20:
        variants.append(hook_snippet)

    return variants[:3]


def _generate_headline_variants(title: str, hook_text: str) -> list[str]:
    """Generate up to 3 thumbnail headline variants."""
    variants = []

    # Variant 1: direct title (first 72 chars)
    variants.append(title[:72])

    # Variant 2: question form
    words = title.split()
    if len(words) >= 4:
        variants.append(f"Wait… {' '.join(words[:7])}?")

    # Variant 3: hook excerpt
    hook_short = " ".join(hook_text.split()[:8])
    if hook_short and hook_short not in variants:
        variants.append(hook_short)

    return [v[:72] for v in variants[:3]]


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
