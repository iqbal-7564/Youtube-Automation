"""
STEP 1 — Topic Selection (MindBlownFacts Edition)

Uses Groq to generate a specific, surprising world-fact topic from a curated seed bank.
Categories (priority order): SPACE > SCIENCE > HISTORY > ANIMALS > NATURE > GEOGRAPHY > OCEAN > CULTURE
Deduplication: token_set_ratio > 0.80 against today's produced videos.
Fallback: random seed title if Groq is unavailable.
"""

import json
import logging
import os
import random
import re
from datetime import datetime
from pathlib import Path

import requests

try:
    from rapidfuzz import fuzz as _fuzz
    def _sim(a: str, b: str) -> float:
        return _fuzz.token_set_ratio(a, b) / 100.0
except ImportError:
    def _sim(a: str, b: str) -> float:
        wa, wb = set(a.lower().split()), set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

log = logging.getLogger(__name__)

CATEGORIES = ["SPACE", "SCIENCE", "HISTORY", "ANIMALS", "NATURE", "GEOGRAPHY", "OCEAN", "CULTURE"]

_SEEDS: dict[str, list[str]] = {
    "SPACE": [
        "black holes", "neutron stars", "the true scale of the universe",
        "dark matter mystery", "the speed of light limits",
        "Jupiter's storms bigger than Earth", "Saturn's rings composition",
        "habitable exoplanets", "what happened before the Big Bang",
        "Mars has the tallest volcano in the solar system",
        "a day on Venus is longer than its year",
        "the sun loses 4 million tons per second", "pulsars",
    ],
    "SCIENCE": [
        "quantum entanglement and teleportation", "DNA stores data like a hard drive",
        "how human memory actually works", "electricity travels at near light speed",
        "nuclear fusion could power civilization forever", "why humans dream",
        "how antibiotics are becoming useless", "CRISPR can rewrite life",
        "time moves slower near heavy objects", "magnets and quantum mechanics",
        "fire is not actually a solid liquid or gas", "the laws of thermodynamics",
    ],
    "HISTORY": [
        "ancient Egypt pyramid construction methods",
        "why the Roman Empire really collapsed",
        "the Black Death changed Europe forever",
        "Genghis Khan's empire was larger than any in history",
        "the Library of Alexandria held half a million scrolls",
        "ancient Greeks discovered the Earth was round in 240 BC",
        "writing was invented to track beer supplies",
        "the Industrial Revolution happened in 50 years",
        "Rome had a population of 1 million before London",
        "Vikings discovered America 500 years before Columbus",
        "the Silk Road spread religion and plague simultaneously",
    ],
    "ANIMALS": [
        "octopuses have three hearts and blue blood",
        "animal migration covering thousands of miles",
        "the mantis shrimp can punch at bullet speed",
        "bioluminescent creatures light up the deep ocean",
        "crows can recognise and remember human faces",
        "dolphins call each other by name",
        "tardigrades can survive in outer space",
        "the immortal jellyfish reverts to a younger state",
        "ants have been farming for 50 million years",
        "elephants are the only animals that hold funerals",
        "whales communicate across entire ocean basins",
    ],
    "NATURE": [
        "how volcanoes create new land",
        "the Amazon produces 20 percent of Earth's oxygen",
        "the Northern Lights are caused by solar wind",
        "lightning strikes Earth 100 times per second",
        "coral reefs support 25 percent of all marine life",
        "some caves have ecosystems that evolved in total darkness",
        "a single storm can release nuclear bomb levels of energy",
        "the Sahara was a lush jungle 10000 years ago",
        "permafrost holds twice the carbon in our atmosphere",
        "fire needs living ecosystems to be able to survive",
        "tidal forces are slowly moving the Moon away from Earth",
    ],
    "GEOGRAPHY": [
        "a point on the equator moves 1670 km per hour",
        "the Mariana Trench is deeper than Everest is tall",
        "Russia spans 11 time zones",
        "Australia is wider than the Moon",
        "there is a place where four countries meet at one point",
        "Finland has more lakes than any country on Earth",
        "Canada has more lakes than the rest of the world combined",
        "there are countries completely surrounded by other countries",
        "the world's highest navigable lake is above the clouds",
        "some borders are drawn with mathematical precision",
        "Brazil was once the capital of the Portuguese Empire",
    ],
    "OCEAN": [
        "the Mariana Trench pressure would crush a submarine instantly",
        "ocean currents act as a global heating system",
        "bioluminescent bays glow bright blue at night",
        "underwater volcanoes outnumber land volcanoes",
        "ocean dead zones are growing every decade",
        "90 percent of all life on Earth lives in the ocean",
        "the Pacific garbage patch is twice the size of Texas",
        "the ocean floor has mountains taller than Everest",
        "waves in the Southern Ocean circle the globe non-stop",
        "there are underwater waterfalls larger than Niagara",
        "sea ice in Antarctica is thicker than the Eiffel Tower is tall",
    ],
    "CULTURE": [
        "ancient Sumerian is the oldest written language ever found",
        "the most spoken language in 3000 BC was Sumerian",
        "ancient Romans used crushed mouse brains as toothpaste",
        "Göbekli Tepe is 6000 years older than Stonehenge",
        "the ancient trade route connected China to Rome",
        "half the world's languages will be extinct in 100 years",
        "ancient Egyptians used honey as medicine and it still works",
        "traditional wayfinding could navigate the Pacific without instruments",
        "Jericho is the oldest continuously inhabited city",
        "the Colosseum could flood for mock sea battles",
        "ancient Persians debated sober then drunk to double-check decisions",
    ],
}

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"


def select_topic(logs_dir: Path) -> dict | None:
    produced_today   = _load_produced_today(logs_dir)
    full_history     = _load_full_history(logs_dir)
    used_categories  = {v.get("intent", "") for v in produced_today}
    perf_weights     = _load_performance_weights(logs_dir)

    # Fetch trending hints once (used to enrich all topic expansions this run)
    trending_hints = _fetch_trending_hints()

    # Build ordered category list, performance-weighted, today-deduped
    ordered = _prioritise_categories(CATEGORIES, used_categories, perf_weights)

    for cat in ordered:
        seed  = random.choice(_SEEDS[cat])
        topic = _build_topic(cat, seed, full_history, trending_hints.get(cat, ""))
        if topic:
            log.info("Selected [%s]: %s", cat, topic["title"][:80])
            return topic

    # All categories exhausted — pick highest-weight and ignore history
    log.info("All categories exhausted — generating fresh angle")
    cat  = ordered[0] if ordered else random.choice(CATEGORIES)
    seed = random.choice(_SEEDS[cat])
    return _build_topic(cat, seed, [], trending_hints.get(cat, ""))


def _prioritise_categories(
    cats: list[str],
    used_today: set[str],
    weights: dict[str, float],
) -> list[str]:
    """Sort categories by performance weight, skip ones used today."""
    available = [c for c in cats if c not in used_today]
    if not available:
        available = list(cats)
    available.sort(key=lambda c: weights.get(c, 1.0), reverse=True)
    return available


def _fetch_trending_hints() -> dict[str, str]:
    """Use Groq to fetch one trending angle hint per category."""
    keys = [os.getenv("GROQ_API_KEY_1", "").strip(), os.getenv("GROQ_API_KEY_2", "").strip()]
    for key in keys:
        if not key:
            continue
        try:
            cats_str = ", ".join(CATEGORIES)
            r = requests.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [{
                        "role": "system",
                        "content": (
                            "You are a viral content strategist. "
                            "Return ONLY valid JSON, no markdown. "
                            'Format: {"CATEGORY": "hint"} for each category.'
                        ),
                    }, {
                        "role": "user",
                        "content": (
                            f"For each category: {cats_str}\n"
                            "Give ONE trending angle in 8-12 words — fresh, specific, "
                            "currently viral on YouTube in 2025. Focus on recent discoveries, "
                            "counterintuitive facts, or newly revealed historical truths."
                        ),
                    }],
                    "temperature": 0.7,
                    "max_tokens": 400,
                },
                timeout=15,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    if isinstance(data, dict):
                        return data
        except Exception as exc:
            log.debug("Trend hints: %s", exc)
        break
    return {}


def _build_topic(category: str, seed: str, produced: list[dict],
                 trend_hint: str = "") -> dict | None:
    title, description = _groq_expand(category, seed, trend_hint)

    if not title:
        title       = f"Incredible Facts About {seed.title()}"
        description = f"Fascinating and little-known facts about {seed}."

    if _is_duplicate(title, produced):
        log.debug("Duplicate — skipping: %s", title[:60])
        return None

    return {
        "title":        title[:200],
        "description":  description[:500],
        "intent":       category,
        "source":       "MindBlownFacts",
        "published_at": datetime.utcnow().isoformat(),
        "article_url":  "",
        "seed":         seed,
        "trend_hint":   trend_hint[:100] if trend_hint else "",
    }


def _groq_expand(category: str, seed: str, trend_hint: str = "") -> tuple[str, str]:
    keys = [os.getenv("GROQ_API_KEY_1", "").strip(), os.getenv("GROQ_API_KEY_2", "").strip()]
    for key in keys:
        if not key:
            continue
        try:
            r = requests.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You generate specific, mind-blowing world-fact video topics. "
                                "Return ONLY valid JSON with no markdown: "
                                "{\"title\": \"...\", \"description\": \"...\"} "
                                "Title: max 80 chars. Use curiosity-gap psychology — imply "
                                "hidden or forbidden knowledge. "
                                "Good: 'The Impossible Thing Scientists Found in Deep Ocean' "
                                "Bad:  'Amazing Ocean Facts' "
                                "Description: 1-2 sentences with the most surprising specific detail. "
                                "Focus on FRESH ANGLES: recent discoveries, counterintuitive facts, "
                                "or surprising connections to modern life. Make it feel like "
                                "something people would share right now."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Category: {category}\n"
                                f"Seed topic: {seed}\n"
                                + (f"Trending angle hint: {trend_hint}\n" if trend_hint else "") +
                                "Generate a fresh, surprising angle on this topic for a viral "
                                "YouTube Shorts video. Prioritize recent discoveries or "
                                "counterintuitive facts. Use the trending hint if provided."
                            ),
                        },
                    ],
                    "temperature": 0.90,
                    "max_tokens":  200,
                },
                timeout=20,
            )
            if r.ok:
                raw  = r.json()["choices"][0]["message"]["content"].strip()
                m    = re.search(r'\{.*\}', raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    if data.get("title"):
                        return data["title"], data.get("description", "")
        except Exception as exc:
            log.debug("Groq topic expand: %s", exc)
    return "", ""


def _is_duplicate(title: str, produced: list[dict]) -> bool:
    return any(_sim(title.lower(), p.get("title", "").lower()) > 0.80
               for p in produced)


def _load_produced_today(logs_dir: Path) -> list[dict]:
    try:
        path = logs_dir / "video_results.json"
        if not path.exists():
            return []
        today = datetime.utcnow().date().isoformat()
        return [r for r in json.loads(path.read_text())
                if r.get("uploaded_at", "").startswith(today)]
    except Exception:
        return []


def _load_full_history(logs_dir: Path) -> list[dict]:
    """Load all video results from the last 12 months for deduplication."""
    try:
        path = logs_dir / "video_results.json"
        if not path.exists():
            return []
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=365)).isoformat()
        return [r for r in json.loads(path.read_text())
                if r.get("uploaded_at", "") >= cutoff]
    except Exception:
        return []


def _load_performance_weights(logs_dir: Path) -> dict[str, float]:
    """Read per-category average retention from analytics, return as weights."""
    try:
        path = logs_dir / "performance_history.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return {cat: info.get("avg_retention_pct", 50.0)
                for cat, info in data.items()}
    except Exception:
        return {}
