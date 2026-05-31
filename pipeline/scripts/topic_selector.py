"""
STEP 1 — Topic Selection (MindBlownFacts Edition)

Uses Groq to generate a specific, surprising world-fact topic from a curated seed bank.
Categories (priority order): SPACE > SCIENCE > HISTORY > ANIMALS > NATURE > GEOGRAPHY > OCEAN > CULTURE
Deduplication: token_set_ratio > 0.80 against today's produced videos.

Algorithm 1 — Trending Topic Arbitrage (Google Trends via pytrends):
  Fetches rising related queries per category. Trending seeds are ranked ahead
  of static seeds so the most timely topics are attempted first.
  Opportunity score = trend_value (0-100 from Google) for ranking.
  Results cached for _TREND_CACHE_TTL_HOURS hours to avoid rate-limiting.

Algorithm 4 — Saturation Filter (YouTube Data API v3):
  After a title is generated, checks the YouTube search result count.
  Skips topics with > _SATURATION_MAX_RESULTS existing videos.
  Falls back gracefully (passes filter) when YOUTUBE_API_KEY is not set.

Fallback: random seed title if Groq is unavailable.
"""

import json
import logging
import os
import random
import re
import time
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

# ── Algorithm 4 config ────────────────────────────────────────────────────────
# Topics with more than this many YouTube results are considered oversaturated.
_SATURATION_MAX_RESULTS = 50_000

# ── Algorithm 1 config ────────────────────────────────────────────────────────
# Trend data is cached to avoid hammering Google Trends on every pipeline run.
_TREND_CACHE_TTL_HOURS = 6

# Google Trends search terms used to find rising related queries per category.
_CATEGORY_SEARCH_TERMS: dict[str, str] = {
    "SPACE":     "space discovery",
    "SCIENCE":   "science discovery",
    "HISTORY":   "ancient history facts",
    "ANIMALS":   "animal facts",
    "NATURE":    "nature facts",
    "GEOGRAPHY": "geography facts",
    "OCEAN":     "ocean discovery",
    "CULTURE":   "ancient culture facts",
}

# Keywords for mapping Google's "trending now" searches to our categories.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "SPACE":     ["space", "nasa", "asteroid", "planet", "star", "galaxy", "moon", "mars", "rocket", "comet", "cosmos", "universe"],
    "SCIENCE":   ["science", "physics", "dna", "gene", "virus", "quantum", "laser", "atom", "research", "biology", "chemistry"],
    "HISTORY":   ["history", "ancient", "roman", "egypt", "war", "empire", "viking", "medieval", "artifact", "civilization"],
    "ANIMALS":   ["animal", "shark", "whale", "bird", "snake", "spider", "wolf", "bear", "fish", "insect"],
    "NATURE":    ["volcano", "earthquake", "storm", "forest", "climate", "rain", "flood", "lightning", "tornado", "wildfire"],
    "GEOGRAPHY": ["country", "river", "mountain", "island", "continent", "border", "desert", "lake", "geography"],
    "OCEAN":     ["ocean", "sea", "deep", "coral", "reef", "wave", "tsunami", "marine", "submarine", "underwater"],
    "CULTURE":   ["culture", "language", "ritual", "tradition", "tribe", "artifact", "religion", "food"],
}

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


# ── Public entry point ────────────────────────────────────────────────────────

def select_topic(logs_dir: Path) -> dict | None:
    produced_today  = _load_produced_today(logs_dir)
    full_history    = _load_full_history(logs_dir)
    used_categories = {v.get("intent", "") for v in produced_today}
    perf_weights    = _load_performance_weights(logs_dir)

    # Priority 1: Velocity cluster queue — follow-up topics from viral videos
    velocity_queue = _load_velocity_queue(logs_dir)
    for item in velocity_queue:
        cat  = item.get("category", "")
        seed = item.get("seed", "")
        if not cat or not seed or cat in used_categories:
            continue
        topic = _build_topic(cat, seed, full_history, "")
        if topic:
            _consume_velocity_item(logs_dir, item)
            topic["source"] = "VelocityCluster"
            log.info("Velocity cluster [%s]: %s", cat, topic["title"][:80])
            return topic

    # Priority 2: Google Trends (multi-market) + YouTube Autocomplete dynamic seeds
    trending_seeds     = _fetch_trending_seeds(logs_dir)
    autocomplete_seeds = _fetch_autocomplete_seeds()

    # AI-generated angle hints (used to enrich Groq topic expansion)
    trending_hints = _fetch_trending_hints()

    ordered = _prioritise_categories(CATEGORIES, used_categories, perf_weights)

    for cat in ordered:
        candidates = _rank_seeds(
            cat,
            trending_seeds.get(cat, []),
            autocomplete_seeds.get(cat, []),
        )
        for seed in candidates[:6]:  # max 6 attempts per category
            topic = _build_topic(cat, seed, full_history, trending_hints.get(cat, ""))
            if topic:
                log.info("Selected [%s]: %s", cat, topic["title"][:80])
                return topic

    # All categories exhausted — pick highest-weight and ignore history
    log.info("All categories exhausted — generating fresh angle")
    cat  = ordered[0] if ordered else random.choice(CATEGORIES)
    seed = random.choice(_SEEDS[cat])
    return _build_topic(cat, seed, [], trending_hints.get(cat, ""))


# ── Algorithm 1 — Trending Topic Arbitrage ────────────────────────────────────

def _fetch_trending_seeds(logs_dir: Path) -> dict[str, list[tuple[str, float]]]:
    """
    Returns {category: [(rising_topic, trend_score), ...]} using pytrends.
    trend_score is the Google Trends 'value' field (0-100+, higher = more rising).
    Results are cached at logs_dir/trend_cache.json for _TREND_CACHE_TTL_HOURS hours.
    Falls back to empty dict if pytrends is unavailable or rate-limited.
    """
    cached = _load_trend_cache(logs_dir)
    if cached:
        log.info("Trend cache hit — skipping Google Trends fetch")
        return {cat: [tuple(x) for x in v] for cat, v in cached.items()}

    results: dict[str, list[tuple[str, float]]] = {cat: [] for cat in CATEGORIES}

    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.debug("pytrends not installed — no Google Trends data")
        return results

    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)

        # Step 1: trending searches across 4 English-speaking markets.
        # Topics appearing in multiple markets score higher — cross-market
        # momentum means a topic is breaking globally before it peaks.
        #   1 market  →  95   (local trend)
        #   2 markets → 140   (gaining momentum)
        #   3 markets → 185   (strong global signal)
        #   4 markets → 230   (viral — publish immediately)
        _MARKETS = ["united_states", "india", "united_kingdom", "australia"]
        market_counts: dict[str, int] = {}  # topic → number of markets it appears in

        for market in _MARKETS:
            try:
                time.sleep(0.4)  # pace between market calls
                df      = pt.trending_searches(pn=market)
                topics  = [t.lower() for t in df[0].tolist()[:30]]
                for topic in topics:
                    market_counts[topic] = market_counts.get(topic, 0) + 1
                log.debug("Trending [%s]: %d topics", market, len(topics))
            except Exception as exc:
                log.debug("Trending searches [%s]: %s", market, exc)

        # Map to categories and assign cross-market score
        for trend, count in market_counts.items():
            score = 95.0 + 45.0 * (count - 1)
            for cat, keywords in _CATEGORY_KEYWORDS.items():
                if any(kw in trend for kw in keywords):
                    results[cat].append((trend, score))
                    break

        multi_market = sum(1 for c in market_counts.values() if c > 1)
        log.info("Trending now: %d topics (%d cross-market) mapped across categories",
                 len(market_counts), multi_market)

        # Step 2: rising related queries per category (one call each, rate-limited)
        for cat in CATEGORIES:
            search_term = _CATEGORY_SEARCH_TERMS[cat]
            try:
                time.sleep(0.6)  # gentle pacing — avoids Google 429
                pt.build_payload([search_term], timeframe="now 7-d", geo="")
                related = pt.related_queries()
                rising  = related.get(search_term, {}).get("rising")
                if rising is not None and not rising.empty:
                    for _, row in rising.head(5).iterrows():
                        score = min(float(row.get("value", 50)), 100.0)
                        results[cat].append((str(row["query"]), score))
                    log.debug("Trends [%s]: %d rising queries", cat, len(results[cat]))
            except Exception as exc:
                log.debug("Rising queries [%s]: %s", cat, exc)

        _save_trend_cache(logs_dir, {cat: list(v) for cat, v in results.items()})
        total = sum(len(v) for v in results.values())
        log.info("Google Trends: %d rising topics fetched across %d categories", total, len(CATEGORIES))

    except Exception as exc:
        log.warning("Google Trends fetch failed: %s", exc)

    return results


def _rank_seeds(cat: str, trending: list[tuple[str, float]],
                autocomplete: list[tuple[str, float]] | None = None) -> list[str]:
    """Trending + autocomplete seeds (score-ranked) prepended to shuffled static seeds."""
    all_dynamic = trending + (autocomplete or [])
    ranked      = [t for t, _ in sorted(all_dynamic, key=lambda x: x[1], reverse=True)]
    static      = _SEEDS[cat].copy()
    random.shuffle(static)
    seen        = {t.lower() for t in ranked}
    static      = [s for s in static if s.lower() not in seen]
    return ranked + static


def _load_trend_cache(logs_dir: Path) -> dict:
    try:
        path = logs_dir / "trend_cache.json"
        if not path.exists():
            return {}
        data       = json.loads(path.read_text())
        cached_at  = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        age_hours  = (datetime.utcnow() - cached_at).total_seconds() / 3600
        if age_hours > _TREND_CACHE_TTL_HOURS:
            return {}
        return data.get("trends", {})
    except Exception:
        return {}


def _save_trend_cache(logs_dir: Path, trends: dict) -> None:
    try:
        path = logs_dir / "trend_cache.json"
        path.write_text(json.dumps({
            "cached_at": datetime.utcnow().isoformat(),
            "trends":    trends,
        }))
    except Exception:
        pass


# ── Algorithm: YouTube Autocomplete Keyword Mining ────────────────────────────

_AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"

def _fetch_autocomplete_seeds() -> dict[str, list[tuple[str, float]]]:
    """
    Queries YouTube's public autocomplete API for each category.
    No API key needed — free, real-time search demand signal.

    Scoring: position 0 = 90 pts, position 1 = 80, ..., position 8 = 10.
    High position = YouTube users actively searching this exact phrase right now.
    """
    results: dict[str, list[tuple[str, float]]] = {cat: [] for cat in CATEGORIES}

    for cat in CATEGORIES:
        query = _CATEGORY_SEARCH_TERMS[cat]
        try:
            r = requests.get(
                _AUTOCOMPLETE_URL,
                params={"ds": "yt", "client": "firefox", "q": query, "hl": "en"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=8,
            )
            if r.ok:
                data        = r.json()
                suggestions = data[1] if len(data) > 1 else []
                for i, suggestion in enumerate(suggestions[:9]):
                    score = max(90.0 - i * 10.0, 10.0)
                    results[cat].append((str(suggestion), score))
                log.debug("Autocomplete [%s]: %d suggestions", cat, len(results[cat]))
        except Exception as exc:
            log.debug("Autocomplete [%s]: %s", cat, exc)
        time.sleep(0.25)

    total = sum(len(v) for v in results.values())
    log.info("Autocomplete: %d live search suggestions fetched", total)
    return results


# ── Topic Velocity Clustering — queue helpers ─────────────────────────────────

def _load_velocity_queue(logs_dir: Path) -> list[dict]:
    """Returns pending high-priority seeds from velocity_queue.json."""
    try:
        path = logs_dir / "velocity_queue.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())
    except Exception:
        return []


def _consume_velocity_item(logs_dir: Path, item: dict) -> None:
    """Remove a consumed item from velocity_queue.json."""
    try:
        path  = logs_dir / "velocity_queue.json"
        queue = json.loads(path.read_text()) if path.exists() else []
        queue = [q for q in queue
                 if not (q.get("seed") == item.get("seed")
                         and q.get("queued_at") == item.get("queued_at"))]
        path.write_text(json.dumps(queue, indent=2))
    except Exception:
        pass


# ── Algorithm 4 — Saturation Filter ──────────────────────────────────────────

def _check_saturation(title: str) -> bool:
    """
    Returns True if the topic has room to compete (passes filter).
    Returns False if YouTube is already flooded with > _SATURATION_MAX_RESULTS videos.

    Uses YouTube Data API v3 search.list (100 quota units per call).
    Passes automatically when YOUTUBE_API_KEY is not set — never blocks production.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return True

    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part":       "snippet",
                "q":          title,
                "type":       "video",
                "maxResults": 1,
                "key":        api_key,
            },
            timeout=10,
        )
        if not r.ok:
            log.debug("YouTube saturation check HTTP %s — passing", r.status_code)
            return True

        total = r.json().get("pageInfo", {}).get("totalResults", 0)
        if total > _SATURATION_MAX_RESULTS:
            log.info("Saturated (%d results) — skipping: %.60s", total, title)
            return False

        log.debug("Saturation OK (%d results): %.60s", total, title)
        return True

    except Exception as exc:
        log.debug("Saturation check error: %s", exc)
        return True  # fail-open: never block when the API is unreachable


# ── Existing helpers (unchanged) ──────────────────────────────────────────────

def _prioritise_categories(
    cats: list[str],
    used_today: set[str],
    weights: dict[str, float],
) -> list[str]:
    available = [c for c in cats if c not in used_today]
    if not available:
        available = list(cats)
    available.sort(key=lambda c: weights.get(c, 1.0), reverse=True)
    return available


def _fetch_trending_hints() -> dict[str, str]:
    """Use Groq to fetch one AI-generated trending angle hint per category."""
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
                m   = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    if isinstance(data, dict):
                        return data
        except Exception as exc:
            log.debug("Trend hints: %s", exc)
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

    # Algorithm 4: reject over-saturated topics before committing
    if not _check_saturation(title):
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
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r'\{.*\}', raw, re.DOTALL)
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
        path  = logs_dir / "video_results.json"
        if not path.exists():
            return []
        today = datetime.utcnow().date().isoformat()
        return [r for r in json.loads(path.read_text())
                if r.get("uploaded_at", "").startswith(today)]
    except Exception:
        return []


def _load_full_history(logs_dir: Path) -> list[dict]:
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
    try:
        path = logs_dir / "performance_history.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return {cat: info.get("avg_retention_pct", 50.0)
                for cat, info in data.items()}
    except Exception:
        return {}
