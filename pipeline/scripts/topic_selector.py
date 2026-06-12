"""
STEP 1 — Topic Selection (MindBlownFacts Edition)

Uses Groq to generate a specific, surprising world-fact topic from a curated seed bank.
Categories are rotated evenly across all 15 types using a frequency-inverse score so no
single category dominates. Deduplication: token_set_ratio > 0.80 against today's produced videos.

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

CATEGORIES = ["SPACE", "SCIENCE", "HISTORY", "ANIMALS", "NATURE", "GEOGRAPHY", "OCEAN", "CULTURE",
              "TECHNOLOGY", "PSYCHOLOGY", "MYTHOLOGY", "MEDICINE", "MATHEMATICS", "ECONOMICS", "PHYSICS"]

# ── Algorithm 4 config ────────────────────────────────────────────────────────
# Saturation is measured by view velocity of top 10 results, NOT total result count.
# totalResults is a corpus-size signal, not competition density.
# Median views of top 10:
#   < 100,000        → PASS (low competition)
#   100k – 500k      → PASS with -10 score penalty
#   > 500,000        → REJECT (market already dominated)
_SATURATION_MEDIAN_PASS    = 100_000
_SATURATION_MEDIAN_PENALTY = 500_000

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
    "OCEAN":       "ocean discovery",
    "CULTURE":     "ancient culture facts",
    "TECHNOLOGY":  "technology innovation facts",
    "PSYCHOLOGY":  "psychology mind facts",
    "MYTHOLOGY":   "ancient mythology legends",
    "MEDICINE":    "medical science facts",
    "MATHEMATICS": "mathematics facts",
    "ECONOMICS":   "economics money facts",
    "PHYSICS":     "physics facts discoveries",
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
    "CULTURE":     ["culture", "language", "ritual", "tradition", "tribe", "artifact", "religion", "food"],
    "TECHNOLOGY":  ["technology", "ai", "robot", "computer", "digital", "cyber", "chip", "internet", "software", "automation", "machine"],
    "PSYCHOLOGY":  ["psychology", "brain", "mind", "behavior", "cognitive", "memory", "emotion", "perception", "mental", "consciousness"],
    "MYTHOLOGY":   ["myth", "legend", "god", "ancient", "folklore", "deity", "hero", "dragon", "oracle", "zeus", "odin", "thor"],
    "MEDICINE":    ["medical", "doctor", "surgery", "disease", "virus", "body", "organ", "health", "hospital", "treatment", "cure", "drug"],
    "MATHEMATICS": ["math", "number", "equation", "theorem", "infinity", "prime", "geometry", "calculus", "algorithm", "statistics"],
    "ECONOMICS":   ["economy", "money", "wealth", "market", "trade", "bank", "financial", "currency", "stock", "investment", "inflation"],
    "PHYSICS":     ["physics", "quantum", "gravity", "relativity", "energy", "force", "particle", "wave", "electromagnetic", "thermodynamics"],
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
    "TECHNOLOGY": [
        "AI is now better than doctors at detecting cancer",
        "the internet weighs the same as a strawberry",
        "a modern smartphone has more power than NASA in 1969",
        "quantum computers can break any encryption instantly",
        "robots are already replacing 85 million jobs worldwide",
        "the first computer bug was a real insect",
        "we produce more data every day than in all of human history before 2003",
        "self-healing materials can repair themselves like skin",
        "brain-computer interfaces let paralyzed people type with thoughts",
        "lithium batteries were accidentally discovered",
        "fiber optic cables carry data at the speed of light",
    ],
    "PSYCHOLOGY": [
        "the human brain cannot tell the difference between real and imagined",
        "you make 35000 decisions every single day without knowing",
        "memories are reconstructed differently every time you recall them",
        "the bystander effect means more people means less help",
        "sleep deprivation creates the same symptoms as being drunk",
        "the placebo effect can work even when you know it is a placebo",
        "humans are the only animals that cry from emotion",
        "decision fatigue causes worse choices later in the day",
        "color affects mood and behavior more than any other visual stimulus",
        "fear and excitement produce identical physiological responses",
        "multitasking reduces productivity by 40 percent",
    ],
    "MYTHOLOGY": [
        "the myth of Atlantis may be based on a real sunken island",
        "Norse mythology predicted the internet with the world tree Yggdrasil",
        "ancient Greek gods were based on real astronomical observations",
        "the Trojan War was proven real by archaeology in 1870",
        "dragons appear in every ancient culture independently",
        "the myth of the Minotaur may be based on a real maze in Crete",
        "Hercules was based on a real Mycenaean king",
        "ancient Egyptians believed the heart not the brain held intelligence",
        "the flood myth appears in over 200 independent cultures worldwide",
        "Medusa was originally a protector goddess not a monster",
        "the myth of werewolves may have originated from a real medical condition",
    ],
    "MEDICINE": [
        "the human body replaces itself completely every 7 to 10 years",
        "penicillin was discovered accidentally by a messy laboratory",
        "surgeons used to operate without washing their hands",
        "the appendix is not actually useless — it stores good bacteria",
        "your gut has more neurons than your spinal cord",
        "aspirin was used for 70 years before anyone understood how it worked",
        "the placenta is the only temporary organ the human body grows",
        "leeches are still used in modern surgery",
        "the human immune system destroys over a billion cancer cells per day",
        "blood types were only discovered in 1901",
        "laughing strengthens the immune system as much as exercise",
    ],
    "MATHEMATICS": [
        "infinity comes in different sizes — some infinities are bigger than others",
        "the number zero was invented and almost banned",
        "prime numbers are used to protect every password on earth",
        "a mathematical proof took 358 years to solve",
        "the Fibonacci sequence appears in every living thing on earth",
        "there are more possible chess games than atoms in the universe",
        "mathematicians proved there are problems computers can never solve",
        "pi contains every number sequence that will ever exist",
        "the Monty Hall problem defies human intuition completely",
        "a single equation predicted both nuclear bombs and GPS satellites",
        "topology proved a coffee cup and a donut are the same shape",
    ],
    "ECONOMICS": [
        "the world's 8 richest people own as much as the poorest 3.5 billion",
        "money was invented because barter never actually worked",
        "the 2008 financial crisis was predicted by one man years before",
        "diamonds are not rare — they are artificially scarce by design",
        "the economy of the underground black market rivals real countries",
        "ancient Rome had inflation so bad it collapsed the currency",
        "the stock market crashes every 7 to 10 years with mathematical precision",
        "a single tweet can move global markets by billions in seconds",
        "banana republics were literally created by a single fruit company",
        "Viking economics were more sophisticated than medieval Europe",
        "the tulip mania of 1637 was the world's first financial bubble",
    ],
    "PHYSICS": [
        "time actually moves slower for objects in motion — and we proved it",
        "everything solid is actually 99.9 percent empty space",
        "light behaves differently when observed than when not observed",
        "quantum particles can be in two places at once",
        "the double slit experiment broke our understanding of reality",
        "a neutron star teaspoon weighs a billion tonnes",
        "black holes evaporate over trillions of years through Hawking radiation",
        "the strong nuclear force is the most powerful force in the universe",
        "entangled particles communicate faster than light — Einstein called it spooky",
        "the universe has no center and no edge",
        "time travel into the future is physically possible and proven",
    ],
}

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"


# ── Public entry point ────────────────────────────────────────────────────────

def select_topic_cluster(logs_dir: Path, n: int = 5) -> dict | None:
    """
    For standard/long videos: pick a category, then select n seeds from that
    category that all connect to ONE central angle. Returns a topic dict with an
    extra 'topics' key — a list of sub-topics the script will cover in sequence.

    Falls back to select_topic() if clustering fails (e.g. Groq unavailable).
    """
    full_history   = _load_full_history(logs_dir)
    perf_weights   = _load_performance_weights(logs_dir)
    produced_today = _load_produced_today(logs_dir)
    used_categories = {v.get("intent", "") for v in produced_today}

    # Pick the category from the top YouTube trending topic — no rotation.
    yt_trending = _fetch_youtube_trending()
    all_yt: list[tuple[str, str, float]] = []
    for cat, items in yt_trending.items():
        for seed, score in items:
            all_yt.append((cat, seed, score))
    all_yt.sort(key=lambda x: x[2], reverse=True)

    tried_cats: set[str] = set()
    for cat, _seed, _ in all_yt[:15]:
        if cat in tried_cats:
            continue
        tried_cats.add(cat)
        cluster = _build_topic_cluster(cat, n, full_history)
        if cluster:
            log.info("Cluster(YT) [%s] '%s' — %d related topics",
                     cat, cluster["title"][:60], len(cluster["topics"]))
            return cluster

    # Fallback: try RSS-sourced categories
    trending_seeds = _fetch_trending_seeds(logs_dir)
    all_rss: list[tuple[str, str, float]] = []
    for cat, items in trending_seeds.items():
        for seed, score in items:
            all_rss.append((cat, seed, score))
    all_rss.sort(key=lambda x: x[2], reverse=True)

    for cat, _seed, _ in all_rss[:15]:
        if cat in tried_cats:
            continue
        tried_cats.add(cat)
        cluster = _build_topic_cluster(cat, n, full_history)
        if cluster:
            log.info("Cluster(RSS) [%s] '%s' — %d related topics",
                     cat, cluster["title"][:60], len(cluster["topics"]))
            return cluster

    log.warning("Cluster selection failed — falling back to single topic")
    return select_topic(logs_dir)


def _build_topic_cluster(category: str, n: int, produced: list[dict]) -> dict | None:
    """Pick n related seeds from the category and ask Groq to build a cluster."""
    seeds = _SEEDS.get(category, [])
    if len(seeds) < n:
        return None

    # Sample n+2 seeds so Groq has extras to choose from
    candidates = random.sample(seeds, min(n + 2, len(seeds)))

    cluster = _groq_build_cluster(category, candidates, n)
    if not cluster:
        return None

    if _is_duplicate(cluster["title"], produced):
        log.debug("Cluster title duplicate — skipping: %s", cluster["title"][:60])
        return None

    return cluster


def _groq_build_cluster(category: str, seeds: list[str], n: int) -> dict | None:
    """
    Ask Groq to:
    1. Choose n seeds that share ONE central angle / connecting theme
    2. Generate an overarching video title (curiosity-gap, max 70 chars)
    3. Generate a short description
    Returns a cluster dict ready for use as a topic.
    """
    keys = [
        os.getenv("GROQ_API_KEY_1", "").strip(),
        os.getenv("GROQ_API_KEY_2", "").strip(),
    ]
    seeds_str = "\n".join(f"- {s}" for s in seeds)

    for key in [k for k in keys if k]:
        try:
            r = requests.post(
                _GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [{
                        "role": "system",
                        "content": (
                            "You are a viral YouTube content strategist. "
                            "Return ONLY valid JSON, no markdown, no explanation."
                        ),
                    }, {
                        "role": "user",
                        "content": (
                            f"Category: {category}\n"
                            f"Available topics:\n{seeds_str}\n\n"
                            f"Task: Select exactly {n} topics that connect to ONE central "
                            "angle or theme — they should feel like chapters of the same "
                            "story, not random facts. The viewer must feel they are getting "
                            "a deep dive into one idea, not a random list.\n\n"
                            "Also generate:\n"
                            "- overarching video title (max 70 chars, curiosity-gap question "
                            "starting with Why/How/What — no words: shocking/amazing/mind-blowing)\n"
                            "- description (2 sentences: most surprising angle, then why it matters)\n"
                            "- central_angle (the connecting theme in 6-10 words)\n\n"
                            "Return JSON:\n"
                            '{"title": "...", "description": "...", "central_angle": "...", '
                            f'"topics": [{{"seed": "...", "title": "...", "description": "..."}}]}} '
                            f"(exactly {n} items in topics array)"
                        ),
                    }],
                    "temperature": 0.8,
                    "max_tokens":  900,
                },
                timeout=25,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r'\{.*\}', raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    if data.get("title") and isinstance(data.get("topics"), list) and data["topics"]:
                        curiosity = _curiosity_gap_score(data["title"])
                        return {
                            "title":             data["title"][:200],
                            "description":       data.get("description", "")[:500],
                            "intent":            category,
                            "source":            "Cluster",
                            "published_at":      datetime.utcnow().isoformat(),
                            "article_url":       "",
                            "seed":              data.get("central_angle", seeds[0]),
                            "trend_hint":        "",
                            "novelty_score":     50,
                            "curiosity_score":   curiosity,
                            "saturation":        "pass",
                            "viral_score":       0.0,
                            "performance_score": 50.0,
                            "competition_count": 0,
                            "central_angle":     data.get("central_angle", ""),
                            "topics":            data["topics"],
                        }
        except Exception as exc:
            log.debug("Groq cluster build: %s", exc)
    return None


def _check_news_trigger(logs_dir: Path) -> dict | None:
    """Pick up news trigger if available and not yet used today."""
    try:
        path = logs_dir / "news_trigger.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        today = datetime.utcnow().date().isoformat()
        if data.get("date") == today and not data.get("used", False):
            topic = data.get("topic")
            if topic:
                # Mark as used
                data["used"] = True
                path.write_text(json.dumps(data, indent=2))
                log.info("News trigger picked up: %s", topic["title"][:70])
                return topic
    except Exception as exc:
        log.debug("News trigger check: %s", exc)
    return None


def select_topic(logs_dir: Path) -> dict | None:
    produced_today  = _load_produced_today(logs_dir)
    full_history    = _load_full_history(logs_dir)
    used_categories = {v.get("intent", "") for v in produced_today}
    perf_weights    = _load_performance_weights(logs_dir)

    # Priority -1: News trigger — breaking news facts angle
    news_topic = _check_news_trigger(logs_dir)
    if news_topic:
        return news_topic

    # Priority 0: INTENT_OVERRIDE env var — forces a specific category
    override = os.getenv("INTENT_OVERRIDE", "").strip().upper()
    if override and override in CATEGORIES:
        log.info("INTENT_OVERRIDE=%s — forcing category", override)
        seeds = _SEEDS.get(override, [])
        random.shuffle(seeds)
        for seed in seeds[:6]:
            topic = _build_topic(override, seed, full_history, "")
            if topic:
                topic["source"] = "IntentOverride"
                return topic
        # Fallback: bypass filters for forced category
        seed = random.choice(_SEEDS.get(override, ["facts"]))
        title, description = _groq_expand(override, seed, "")
        if not title:
            title = f"The Incredible Truth About {seed.title()}"
            description = f"Fascinating facts about {seed}."
        return {
            "title": title[:200], "description": description[:500],
            "intent": override, "source": "IntentOverride-Fallback",
            "published_at": datetime.utcnow().isoformat(),
            "article_url": "", "seed": seed, "trend_hint": "",
            "novelty_score": 50, "curiosity_score": 0,
            "saturation": "pass", "viral_score": 0.0,
            "performance_score": 50.0,
        }

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

    # Priority 1b: Topic cluster sequences — follow-up to viral video chains
    cluster_topic = _next_cluster_topic(logs_dir, used_categories)
    if cluster_topic:
        return cluster_topic

    # Priority 2: YouTube trending tells us WHICH CATEGORY is hot right now,
    # but we pick the actual topic from curated broad _SEEDS (not the trending
    # video title itself — those are niche/competitive and already covered by
    # big channels). Broad evergreen seeds get wide reach; trending category
    # gives us the timing signal.
    yt_trending = _fetch_youtube_trending()
    all_yt: list[tuple[str, str, float]] = []   # (cat, seed, score)
    for cat, items in yt_trending.items():
        for seed, score in items:
            all_yt.append((cat, seed, score))
    all_yt.sort(key=lambda x: x[2], reverse=True)  # rank 1 first

    # Dedupe to top category order (highest total trending score per category)
    seen_cats: list[str] = []
    for cat, _, _ in all_yt:
        if cat not in seen_cats:
            seen_cats.append(cat)

    for cat in seen_cats[:8]:
        # Use broad curated seeds — not the trending niche title
        broad_seeds = list(_SEEDS.get(cat, []))
        random.shuffle(broad_seeds)
        for seed in broad_seeds[:10]:
            topic = _build_topic(cat, seed, full_history, "")
            if topic:
                topic["source"] = "YouTubeTrending+BroadSeed"
                log.info("Broad topic [%s]: %s", cat, topic["title"][:80])
                return topic

    # Priority 3: Facts RSS category signal + broad seeds fallback
    trending_seeds = _fetch_trending_seeds(logs_dir)
    trending_hints = _fetch_trending_hints()

    # Use RSS to find hot categories, then pick broad seeds from those categories
    rss_cat_scores: dict[str, float] = {}
    for cat, items in trending_seeds.items():
        rss_cat_scores[cat] = sum(score for _, score in items)
    rss_cats = sorted(rss_cat_scores, key=rss_cat_scores.get, reverse=True)

    for cat in rss_cats[:8]:
        broad_seeds = list(_SEEDS.get(cat, []))
        random.shuffle(broad_seeds)
        for seed in broad_seeds[:8]:
            topic = _build_topic(cat, seed, full_history, trending_hints.get(cat, ""))
            if topic:
                topic["source"] = "FactsRSS+BroadSeed"
                log.info("RSS broad topic [%s]: %s", cat, topic["title"][:80])
                return topic

    # All categories exhausted — last resort, bypass all filters
    log.info("All categories exhausted — generating fresh angle (filters bypassed)")
    # Pick top YouTube trending category if available, otherwise random
    cat = all_yt[0][0] if all_yt else (all_rss[0][0] if all_rss else random.choice(CATEGORIES))
    seed = random.choice(_SEEDS[cat])

    # Try Groq first
    title, description = _groq_expand(cat, seed, trending_hints.get(cat, ""))
    if not title:
        title       = f"The Incredible Truth About {seed.title()}"
        description = f"Fascinating and little-known facts about {seed}."

    # Return directly — no duplicate check, no saturation, no curiosity filter
    # This is the pipeline's safety net and must always produce a topic
    return {
        "title":             title[:200],
        "description":       description[:500],
        "intent":            cat,
        "source":            "MindBlownFacts-Fallback",
        "published_at":      datetime.utcnow().isoformat(),
        "article_url":       "",
        "seed":              seed,
        "trend_hint":        "",
        "novelty_score":     50,
        "curiosity_score":   0,
        "saturation":        "pass",
        "viral_score":       0.0,
        "performance_score": 50.0,
    }


# ── Algorithm 1 — Trending Topic Arbitrage ────────────────────────────────────

def _fetch_trending_seeds(logs_dir: Path) -> dict[str, list[tuple[str, float]]]:
    """
    Returns {category: [(fact_topic, score), ...]} from current science/facts RSS feeds.
    Replaces Google Trends (celebrity/sports noise) with real educational fact sources:
    NASA, ScienceDaily, LiveScience, Space.com, BBC Science, PhysOrg, etc.
    Results cached for _TREND_CACHE_TTL_HOURS to avoid repeat fetches.
    """
    cached = _load_trend_cache(logs_dir)
    if cached:
        log.info("Trend cache hit — skipping facts RSS fetch")
        return {cat: [tuple(x) for x in v] for cat, v in cached.items()}

    results: dict[str, list[tuple[str, float]]] = {cat: [] for cat in CATEGORIES}

    # Current science/facts RSS feeds — free, no auth, always educational content
    _FACTS_RSS = [
        ("NASA",        "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
        ("ScienceDaily","https://www.sciencedaily.com/rss/all.xml"),
        ("LiveScience", "https://www.livescience.com/feeds/all"),
        ("Space",       "https://www.space.com/feeds/all"),
        ("PhysOrg",     "https://phys.org/rss-feed/"),
        ("BBCSci",      "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        ("NewSci",      "https://www.newscientist.com/feed/home/"),
        ("EarthSky",    "https://earthsky.org/feed"),
        ("NatGeo",      "https://www.nationalgeographic.com/pages/topic/rss"),
        ("Smithsonian", "https://www.smithsonianmag.com/rss/latest_articles/"),
    ]

    import xml.etree.ElementTree as ET
    seen_titles: dict[str, int]   = {}   # title → feed count (cross-feed = stronger)
    best_position: dict[str, int] = {}   # title → lowest (best) position seen

    for feed_name, url in _FACTS_RSS:
        try:
            r = requests.get(url, timeout=12,
                             headers={"User-Agent": "Mozilla/5.0"})
            if not r.ok:
                log.debug("Facts RSS [%s]: HTTP %d", feed_name, r.status_code)
                continue
            root  = ET.fromstring(r.content)
            items = root.findall(".//item")[:20]
            for pos, item in enumerate(items):
                title = (item.findtext("title") or "").strip().lower()
                desc  = (item.findtext("description") or "")[:200].lower()
                text  = f"{title} {desc}"
                if not title or len(title) < 10:
                    continue
                seen_titles[text] = seen_titles.get(text, 0) + 1
                if text not in best_position or pos < best_position[text]:
                    best_position[text] = pos
            log.debug("Facts RSS [%s]: %d items", feed_name, len(items))
        except Exception as exc:
            log.debug("Facts RSS [%s]: %s", feed_name, exc)

    # Score: 95 base + 45 per extra feed + rank bonus (50 → 0 over 20 positions)
    for text, count in seen_titles.items():
        pos        = best_position.get(text, 19)
        rank_bonus = max(0.0, 50.0 * (1.0 - pos / 19.0))
        score      = 95.0 + 45.0 * (count - 1) + rank_bonus
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                results[cat].append((text[:120], score))
                break

    cross_feed = sum(1 for c in seen_titles.values() if c > 1)
    total_mapped = sum(len(v) for v in results.values())
    log.info("Facts RSS: %d topics (%d cross-feed) mapped across categories",
             total_mapped, cross_feed)

    _save_trend_cache(logs_dir, {cat: list(v) for cat, v in results.items()})
    log.info("Current facts RSS: %d topics fetched across %d categories",
             total_mapped, len(CATEGORIES))

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


# ── Algorithm: YouTube Trending Top 50 ───────────────────────────────────────

def _fetch_youtube_trending() -> dict[str, list[tuple[str, float]]]:
    """
    Fetches the top 50 currently trending YouTube videos (mostPopular chart).
    Uses YOUTUBE_API_KEY — 1 quota unit, very cheap.

    Scoring: rank 1 = 100 pts down to rank 50 ≈ 8 pts (linear).
    Topics mapped to categories via _CATEGORY_KEYWORDS.
    Returns {category: [(topic_phrase, score), ...]}
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return {}

    results: dict[str, list[tuple[str, float]]] = {cat: [] for cat in CATEGORIES}
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "key":        api_key,
                "chart":      "mostPopular",
                "regionCode": "US",
                "maxResults": 50,
                "part":       "snippet",
            },
            timeout=12,
        )
        if not r.ok:
            log.debug("YouTube trending: HTTP %d", r.status_code)
            return {}

        items = r.json().get("items", [])
        for pos, item in enumerate(items):
            snippet = item.get("snippet", {})
            title   = snippet.get("title", "").strip().lower()
            desc    = snippet.get("description", "")[:200].lower()
            text    = f"{title} {desc}"

            # rank 1 = 100, rank 50 ≈ 8, linear decay
            score = max(8.0, 100.0 * (1.0 - pos / max(len(items) - 1, 1)))

            for cat, keywords in _CATEGORY_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    # Use title as seed — it's already a proved viral phrase
                    results[cat].append((title, score))
                    break

        mapped = sum(len(v) for v in results.values())
        log.info("YouTube Trending top-%d: %d videos mapped to categories",
                 len(items), mapped)
    except Exception as exc:
        log.debug("YouTube trending fetch: %s", exc)

    return results


# ── Topic Velocity Clustering — queue helpers ─────────────────────────────────

def _next_cluster_topic(logs_dir: Path, used_categories: set) -> dict | None:
    """
    Returns the next topic in an active cluster chain if one exists.
    Updates current_idx in topic_clusters.json after consuming a topic.
    """
    try:
        clusters_path = logs_dir / "topic_clusters.json"
        if not clusters_path.exists():
            return None
        clusters = json.loads(clusters_path.read_text())
        changed  = False

        for cluster in clusters:
            cat = cluster.get("category", "")
            if cat in used_categories:
                continue
            idx   = cluster.get("current_idx", 0)
            chain = cluster.get("chain", [])
            if idx >= len(chain):
                continue  # cluster exhausted

            seed = chain[idx]
            full_history = []  # cluster topics bypass deduplication for simplicity

            topic = _build_topic(cat, seed, full_history, "")
            if topic:
                cluster["current_idx"] = idx + 1
                changed = True
                topic["source"] = "TopicCluster"
                log.info("Topic cluster [%s] step %d/%d: %s",
                         cat, idx + 1, len(chain), topic["title"][:60])
                if changed:
                    clusters_path.write_text(json.dumps(clusters, indent=2))
                return topic

    except Exception as exc:
        log.debug("Cluster topic check: %s", exc)
    return None


_VELOCITY_TTL_HOURS = 72

def _load_velocity_queue(logs_dir: Path) -> list[dict]:
    """Returns pending high-priority seeds younger than 72 hours from velocity_queue.json."""
    try:
        path = logs_dir / "velocity_queue.json"
        if not path.exists():
            return []
        entries = json.loads(path.read_text())
        cutoff  = (datetime.utcnow().timestamp()) - (_VELOCITY_TTL_HOURS * 3600)
        fresh   = []
        for e in entries:
            # Support both Unix ts field (new) and ISO queued_at field (legacy)
            ts = e.get("ts")
            if ts is None:
                try:
                    ts = datetime.fromisoformat(e["queued_at"]).timestamp()
                except Exception:
                    ts = cutoff + 1  # unknown age — treat as fresh
            if ts >= cutoff:
                fresh.append(e)
        if len(fresh) < len(entries):
            log.info("Velocity queue: evicted %d stale entries (>72h old)",
                     len(entries) - len(fresh))
        return fresh
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

# ── Existing helpers (unchanged) ──────────────────────────────────────────────

def _load_comment_boost() -> dict[str, int]:
    try:
        p = Path(__file__).parent.parent / "logs" / "auto_fixes.json"
        if p.exists():
            return json.loads(p.read_text()).get("category_boost", {})
    except Exception:
        pass
    return {}


def _recent_category_counts(logs_dir: Path, n: int = 30) -> dict[str, int]:
    """Count how many times each category appears in the last n uploaded videos."""
    try:
        path = logs_dir / "video_results.json"
        if not path.exists():
            return {}
        results = json.loads(path.read_text())
        counts: dict[str, int] = {}
        for r in results[-n:]:
            cat = r.get("intent", "")
            if cat:
                counts[cat] = counts.get(cat, 0) + 1
        return counts
    except Exception:
        return {}


def _prioritise_categories(
    cats: list[str],
    used_today: set[str],
    weights: dict[str, float],
    logs_dir: Path | None = None,
    trending_seeds: dict | None = None,
) -> list[str]:
    available = [c for c in cats if c not in used_today]
    if not available:
        available = list(cats)

    boost         = _load_comment_boost()
    recent_counts = _recent_category_counts(logs_dir, n=30) if logs_dir else {}

    # Trending bonus: categories with active Google Trends hits get a +0 to +65
    # score boost so they rise above frequency-penalised categories.
    # Raw trend scores are 95-185 (95 base + 45/extra market); normalise to 0-65.
    trend_bonus: dict[str, float] = {}
    if trending_seeds:
        for cat, seeds in trending_seeds.items():
            if seeds:
                top = max(s for _, s in seeds[:3])      # best of top 3
                trend_bonus[cat] = min((top - 95) / 2, 65)  # normalised 0-65

    def _score(c: str) -> float:
        perf     = weights.get(c, 50.0)                      # 0-100 retention %
        cb       = boost.get(c, 0) * 5                       # viewer request boost
        freq_pen = min(recent_counts.get(c, 0), 5) * 11      # 0-55 penalty
        freq_bon = 30 if recent_counts.get(c, 0) == 0 else 0 # never-used bonus
        trend    = trend_bonus.get(c, 0)                     # 0-65 trending bonus
        return perf + cb - freq_pen + freq_bon + trend

    # Shuffle BEFORE sorting so equal-score categories get random order rather
    # than always putting SPACE first (SPACE is first in the CATEGORIES list).
    random.shuffle(available)
    available.sort(key=_score, reverse=True)
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


def _wikipedia_novelty_score(topic: str) -> int:
    """
    Two-signal novelty score (0-100):
      30% — lexical signal: presence of discovery/novelty keywords in Wikipedia extract
      70% — recency signal: days since last Wikipedia page edit (100=today, 0=90+ days)
    Free, no API key required.
    Returns 50 (neutral) on any error so it never blocks the pipeline.
    """
    try:
        # Recency signal: check last edit date via recentchanges API
        rc = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "recentchanges",
                    "rctitle": topic, "rclimit": "1", "format": "json"},
            timeout=8,
        )
        recency_score = 0
        if rc.ok:
            changes = rc.json().get("query", {}).get("recentchanges", [])
            if changes:
                from datetime import datetime, timezone
                ts = changes[0].get("timestamp", "")
                if ts:
                    edited = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    days_ago = (datetime.now(timezone.utc) - edited).days
                    recency_score = max(0, int(100 - (days_ago / 90) * 100))

        # Lexical signal: check extract for discovery keywords
        ex = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "titles": topic,
                    "prop": "extracts", "exintro": True,
                    "explaintext": True, "format": "json"},
            timeout=8,
        )
        lexical_score = 0
        if ex.ok:
            pages = ex.json().get("query", {}).get("pages", {})
            extract = " ".join(
                p.get("extract", "") for p in pages.values()
            ).lower()
            novelty_words = [
                "discovered", "revealed", "hidden", "secret", "ancient",
                "impossible", "mystery", "unknown", "lost", "forbidden",
                "breakthrough", "first", "new", "recent", "confirmed",
            ]
            hits = sum(1 for w in novelty_words if w in extract)
            lexical_score = min(100, hits * 15)

        score = int(lexical_score * 0.30 + recency_score * 0.70)
        log.debug("Novelty score for '%s': %d (lexical=%d recency=%d)",
                  topic[:40], score, lexical_score, recency_score)
        return score

    except Exception as exc:
        log.debug("Wikipedia novelty check: %s", exc)
        return 50  # neutral fallback


_CURIOSITY_GAP_PATTERNS = [
    # Curiosity gap: implies hidden/forbidden knowledge
    (r"scientists? found|discovered|revealed|hidden|secret|nobody told|"
     r"never taught|forbidden|they don.?t want|suppressed|covered up", 30),
    # Surprise: violates expectation
    (r"impossible|defies|shouldn.?t|can.?t exist|shouldn.?t be possible|"
     r"breaks (the )?rules|shouldn.?t work|against (all )?odds", 25),
    # Contradiction: attacks widely-held belief
    (r"everything.*(wrong|false|lie)|wrong about|myth|actually|"
     r"contrary to|opposite of|turns out|in fact", 20),
    # Mystery: open question
    (r"why|how (is it possible|does|could)|what (really |actually )?happen|"
     r"mystery|no.?one knows|still unknown|unexplained|unsolved", 15),
    # Specificity: exact numbers / real places / real science
    (r"\d[\d,]*(\.\d+)?\s*(km|miles?|ton|year|second|billion|million|"
     r"percent|degree|meter|kg|lb)", 10),
]


def _curiosity_gap_score(title: str) -> int:
    """
    Score a title 0-100 on curiosity-gap psychology.
    Titles below 30 are likely generic ("Amazing Facts") and should be rejected.
    Titles above 70 are strong candidates.
    """
    title_lower = title.lower()
    score = 0
    for pattern, pts in _CURIOSITY_GAP_PATTERNS:
        if re.search(pattern, title_lower):
            score += pts
    return min(100, score)


def _check_saturation(title: str) -> str:
    """
    Returns 'pass', 'penalty', or 'reject' based on view velocity of top 10 results.
    Uses YOUTUBE_API_KEY (research project) — does NOT count against upload quota.
    Falls back to 'pass' when API key is missing.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return "pass"
    try:
        # Step 1: search top 10 results for this title
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": api_key, "q": title,
                "type": "video", "order": "relevance",
                "maxResults": "10", "part": "id",
            },
            timeout=10,
        )
        if not r.ok:
            return "pass"
        items = r.json().get("items", [])
        if not items:
            return "pass"

        video_ids = ",".join(i["id"]["videoId"] for i in items if "videoId" in i.get("id", {}))
        if not video_ids:
            return "pass"

        # Step 2: fetch view counts (videos.list = 1 unit — very cheap)
        s = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"key": api_key, "id": video_ids,
                    "part": "statistics", "maxResults": "10"},
            timeout=10,
        )
        if not s.ok:
            return "pass"

        view_counts = []
        for item in s.json().get("items", []):
            vc = item.get("statistics", {}).get("viewCount")
            if vc:
                view_counts.append(int(vc))

        if not view_counts:
            return "pass"

        view_counts.sort()
        median = view_counts[len(view_counts) // 2]

        if median > _SATURATION_MEDIAN_PENALTY:
            log.debug("Saturation: median views=%d — REJECT (>500k)", median)
            return "reject"
        if median > _SATURATION_MEDIAN_PASS:
            log.debug("Saturation: median views=%d — penalty (100k-500k)", median)
            return "penalty"
        log.debug("Saturation: median views=%d — pass (<100k)", median)
        return "pass"

    except Exception as exc:
        log.debug("Saturation check error: %s", exc)
        return "pass"


def _count_youtube_results(query: str, api_key: str) -> int:
    """Count how many YouTube videos exist for a search query."""
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": api_key, "q": query,
                "type": "video", "part": "id",
                "maxResults": "50",
            },
            timeout=10,
        )
        if r.ok:
            return r.json().get("pageInfo", {}).get("totalResults", 999999)
    except Exception:
        pass
    return 999999


def _find_best_seo_title(base_title: str, seed: str, category: str) -> tuple[str, int]:
    """
    Generate title variants with low-competition modifiers.
    Returns (best_title, result_count) — lowest competition wins.

    Low competition = few existing YouTube videos = easy to rank #1.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return base_title, 999999

    year = datetime.utcnow().year
    cat  = category.title()

    # Generate variants with low-competition modifiers
    variants = [
        base_title,
        f"{base_title} {year}",
        f"{seed.title()} Facts {year}",
        f"{seed.title()} Facts Nobody Knows",
        f"The Truth About {seed.title()} {year}",
        f"{cat} Facts {year} That Will Shock You",
        f"Why {seed.title()} Will Surprise You {year}",
    ]

    best_title  = base_title
    best_count  = 999999

    for variant in variants[:5]:  # check max 5 variants
        count = _count_youtube_results(variant, api_key)
        log.debug("SEO check '%s': %d results", variant[:50], count)
        if count < best_count:
            best_count = count
            best_title = variant
        time.sleep(0.3)  # gentle rate limiting

    log.info("SEO: best title '%s' (%d competing videos)",
             best_title[:60], best_count)
    return best_title[:200], best_count


def _build_topic(category: str, seed: str, produced: list[dict],
                 trend_hint: str = "") -> dict | None:
    # Wikipedia verification first — skip topic if no article found
    wiki_summary = _wikipedia_verify(seed)
    if not wiki_summary:
        log.debug("Wikipedia: no article for '%s' — skipping", seed[:40])
        return None
    log.debug("Wikipedia verified seed '%s'", seed[:40])

    title, description = _groq_expand(category, seed, trend_hint)

    if not title:
        title       = f"Incredible Facts About {seed.title()}"
        description = f"Fascinating and little-known facts about {seed}."

    if _is_duplicate(title, produced):
        log.debug("Duplicate — skipping: %s", title[:60])
        return None

    saturation = _check_saturation(title)
    if saturation == "reject":
        log.debug("Saturation reject (high competition): %s", title[:60])
        return None

    # SEO upgrade — find lowest competition title variant
    title, competition_count = _find_best_seo_title(title, seed, category)

    # Curiosity gap validation — reject generic titles
    curiosity = _curiosity_gap_score(title)
    if curiosity < 30:
        log.debug("Curiosity gap reject (score=%d): %s", curiosity, title[:60])
        return None

    # Wikipedia novelty score — warn if stale but don't hard-block
    novelty = _wikipedia_novelty_score(category + " " + seed)
    if novelty < 20:
        log.debug("Low novelty score (%d) for: %s — proceeding with warning", novelty, title[:60])

    # Sub-topic performance signal (from analytics history)
    performance_score = _subtopic_performance_score(seed, category)

    # Combined viral opportunity score (0-100)
    # Weights: trend 30%, search 20%, novelty 15%, curiosity 15%, performance 10%, saturation 10%
    saturation_bonus = 10 if saturation == "pass" else (5 if saturation == "penalty" else 0)
    trend_score      = min(100, float(trend_hint[:3].strip()) if trend_hint and trend_hint[:3].isdigit() else 50)
    viral_score      = (
        0.30 * trend_score
      + 0.20 * 50             # search score placeholder (autocomplete already used for ranking)
      + 0.15 * novelty
      + 0.15 * curiosity
      + 0.10 * performance_score
      + 0.10 * saturation_bonus * 10
    )
    log.debug("Viral score for '%s': %.1f (novelty=%d curiosity=%d perf=%.0f)",
              title[:50], viral_score, novelty, curiosity, performance_score)

    return {
        "title":            title[:200],
        "description":      description[:500],
        "intent":           category,
        "source":           "MindBlownFacts",
        "published_at":     datetime.utcnow().isoformat(),
        "article_url":      "",
        "seed":             seed,
        "trend_hint":       trend_hint[:100] if trend_hint else "",
        "novelty_score":    novelty,
        "curiosity_score":  curiosity,
        "saturation":       saturation,
        "viral_score":        round(viral_score, 1),
        "performance_score":  performance_score,
        "wiki_summary":       wiki_summary,
        "competition_count":  competition_count,
    }


def _wikipedia_verify(seed: str) -> str:
    """
    Searches Wikipedia for the seed topic and returns a verified 1-3 sentence
    summary. Tries 5 fallback levels so trending seeds like "nasa asteroid 2025"
    still resolve. Returns empty string only if all attempts fail.
    """
    words = [w for w in seed.strip().split() if w]
    _stopwords = {"the", "a", "an", "of", "in", "on", "at", "is", "are", "was",
                  "were", "and", "or", "to", "for", "with", "by", "from", "that"}
    content_words = [w for w in words if w.lower() not in _stopwords]

    attempts: list[str] = [seed]                       # level 1: full seed
    if len(words) > 4:
        attempts.append(" ".join(words[:4]))           # level 2: first 4 words
    if len(words) > 3:
        attempts.append(" ".join(words[:3]))           # level 3: first 3 words
    if len(words) > 2:
        attempts.append(" ".join(words[:2]))           # level 4: first 2 words
    # level 5: most significant single word (longest content word, skip pure numbers)
    sig = max(content_words, key=lambda w: len(w) if not w.isdigit() else 0, default="")
    if sig and sig not in attempts:
        attempts.append(sig)

    # Deduplicate while preserving order
    seen: list[str] = []
    for a in attempts:
        if a and a not in seen:
            seen.append(a)
    attempts = seen

    for query in attempts:
        try:
            r = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query,
                        "srlimit": "1", "format": "json"},
                timeout=8,
            )
            if not r.ok:
                continue
            results = r.json().get("query", {}).get("search", [])
            if not results:
                continue
            page_title = results[0]["title"]
            ex = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "titles": page_title,
                        "prop": "extracts", "exintro": True,
                        "explaintext": True, "exsentences": 3, "format": "json"},
                timeout=8,
            )
            if not ex.ok:
                continue
            pages = ex.json().get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "").strip()
                if extract and len(extract) > 50:
                    if query != seed:
                        log.debug("Wikipedia: simplified retry succeeded for '%s'", seed[:40])
                    return extract[:400]
        except Exception as exc:
            log.debug("Wikipedia verify [%s]: %s", query[:40], exc)

    return ""


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
                                "IMPORTANT: Only generate topics based on real, verifiable facts. "
                                "Never invent statistics, events, or claims. "
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
        # Support both flat {cat: pct} and nested {cat: {avg_retention_pct: pct}}
        weights = {}
        for cat, info in data.items():
            if isinstance(info, dict):
                weights[cat] = info.get("avg_retention_pct", 50.0)
            elif isinstance(info, (int, float)):
                weights[cat] = float(info)
        return weights
    except Exception:
        return {}


def _subtopic_performance_score(seed: str, category: str) -> float:
    """
    Return sub-topic level performance score (0-100) from analytics history.
    Normalizes the seed to a key and looks it up in subtopic_history.json.
    Falls back to category average, then 50 (neutral) if no data.
    """
    try:
        logs_dir = Path(__file__).parent.parent / "logs"
        path     = logs_dir / "subtopic_history.json"
        if path.exists():
            data = json.loads(path.read_text())
            # Normalize seed to a simple key
            key = re.sub(r"[^a-z0-9]", "_", seed.lower().strip())[:40]
            if key in data:
                return float(data[key].get("avg_retention_pct", 50.0))
            # Try partial match
            for k, v in data.items():
                if k in key or key in k:
                    return float(v.get("avg_retention_pct", 50.0))
        # Fall back to category average
        perf_path = logs_dir / "performance_history.json"
        if perf_path.exists():
            perf = json.loads(perf_path.read_text())
            cat_data = perf.get(category, {})
            if isinstance(cat_data, dict):
                return float(cat_data.get("avg_retention_pct", 50.0))
            elif isinstance(cat_data, (int, float)):
                return float(cat_data)
    except Exception:
        pass
    return 50.0
