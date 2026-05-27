"""
STEP 1 — Topic Selection

Fetches articles from RSS feeds (+ NewsAPI if key present), classifies intent,
filters duplicates / recent social posts, and returns the highest-priority topic.
Priority: DISASTER > WAR > POLITICS > ECONOMY > SPORTS
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

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

RSS_FEEDS = [
    ("Reuters World", "https://feeds.reuters.com/Reuters/worldNews"),
    ("BBC World",     "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera",    "https://www.aljazeera.com/xml/rss/all.xml"),
    ("AP Top News",   "https://rsshub.app/apnews/topics/world-news"),
]

INTENT_KEYWORDS: dict[str, list[str]] = {
    "DISASTER": [
        "earthquake", "flood", "hurricane", "typhoon", "tornado", "wildfire",
        "tsunami", "eruption", "volcano", "cyclone", "disaster", "evacuation",
        "collapsed", "landslide", "explosion kills", "fire kills", "deaths",
    ],
    "WAR": [
        "war", "attack", "military strike", "troops", "bomb", "missile",
        "conflict", "battle", "invasion", "ceasefire", "offensive", "rocket",
        "airstrike", "combat", "frontline", "shelling", "drone strike", "killed",
    ],
    "POLITICS": [
        "election", "president", "prime minister", "government", "parliament",
        "congress", "senate", "sanctions", "diplomacy", "summit", "protest",
        "coup", "minister resigns", "referendum", "vote", "opposition",
    ],
    "ECONOMY": [
        "economy", "inflation", "recession", "stock market", "central bank",
        "gdp", "unemployment", "tariff", "currency", "financial crisis",
        "interest rate", "federal reserve", "trade war", "oil prices",
    ],
    "SPORTS": [
        "world cup", "championship", "tournament", "olympics", "final",
        "football", "soccer", "cricket", "tennis", "basketball",
        "record broken", "wins title", "gold medal", "transfer fee",
    ],
}

PRIORITY = ["DISASTER", "WAR", "POLITICS", "ECONOMY", "SPORTS"]

FAKE_INDICATORS = [
    "you won't believe", "secret they don't want", "mainstream media hiding",
    "deep state", "illuminati", "100% proof", "exposed!!!",
    "shocking truth revealed", "what they're not telling you",
]


def select_topic(logs_dir: Path) -> dict | None:
    articles = _fetch_all()
    if not articles:
        log.warning("No articles fetched from any source")
        return None

    log.info("Fetched %d raw articles", len(articles))
    articles = [a for a in articles if not _is_fake(a)]
    log.info("%d after fake-news filter", len(articles))

    for a in articles:
        a["intent"] = _classify(a)
    articles = [a for a in articles if a["intent"] != "UNKNOWN"]

    produced_today = _load_produced_today(logs_dir)
    used_intents   = {v.get("intent", "") for v in produced_today}

    articles.sort(key=lambda a: PRIORITY.index(a["intent"])
                  if a["intent"] in PRIORITY else 99)

    for a in articles:
        if a["intent"] in used_intents:
            log.debug("Skipping %s — intent already used today", a["intent"])
            continue
        if _is_duplicate(a["title"], produced_today):
            log.debug("Skipping duplicate: %s", a["title"][:60])
            continue
        return {
            "title":        a["title"][:200],
            "description":  a.get("summary", "")[:500],
            "intent":       a["intent"],
            "source":       a.get("source", "News"),
            "published_at": a.get("published", ""),
            "article_url":  a.get("link", ""),
        }

    log.warning("No article passed all filters")
    return None


# ── Fetchers ──────────────────────────────────────────────────────────────────

def _fetch_all() -> list[dict]:
    articles: list[dict] = []

    newsapi_key = os.getenv("NEWSAPI_KEY", "")
    if newsapi_key:
        articles.extend(_fetch_newsapi(newsapi_key))

    if _HAS_FEEDPARSER:
        for name, url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:20]:
                    articles.append({
                        "title":     _strip(e.get("title", "")),
                        "summary":   _strip(e.get("summary", "")),
                        "link":      e.get("link", ""),
                        "published": e.get("published", ""),
                        "source":    name,
                    })
                log.debug("RSS %s: %d entries", name, len(feed.entries[:20]))
            except Exception as exc:
                log.warning("RSS %s failed: %s", name, exc)
    else:
        for name, url in RSS_FEEDS:
            articles.extend(_fetch_rss_raw(name, url))

    seen: set[str] = set()
    unique: list[dict] = []
    for a in articles:
        key = a["title"][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def _fetch_newsapi(key: str) -> list[dict]:
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"language": "en", "pageSize": 20},
            headers={"X-Api-Key": key},
            timeout=10,
        )
        if r.ok:
            return [
                {
                    "title":     a.get("title", ""),
                    "summary":   a.get("description", ""),
                    "link":      a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "source":    a.get("source", {}).get("name", "NewsAPI"),
                }
                for a in r.json().get("articles", [])
                if a.get("title")
            ]
    except Exception as exc:
        log.warning("NewsAPI failed: %s", exc)
    return []


def _fetch_rss_raw(name: str, url: str) -> list[dict]:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        items = re.findall(
            r'<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>'
            r'.*?<link>(.*?)</link>.*?</item>',
            r.text, re.DOTALL
        )
        return [
            {"title": t.strip(), "summary": "", "link": l.strip(),
             "published": "", "source": name}
            for t, l in items[:20] if t.strip()
        ]
    except Exception as exc:
        log.warning("Raw RSS %s failed: %s", name, exc)
    return []


# ── Filters ───────────────────────────────────────────────────────────────────

def _is_fake(article: dict) -> bool:
    title = article.get("title", "").lower()
    if any(ind in title for ind in FAKE_INDICATORS):
        return True
    if title.count("!") >= 3:
        return True
    words = title.split()
    if words and sum(1 for w in words if w.isupper() and len(w) > 2) / len(words) > 0.6:
        return True
    return False


def _classify(article: dict) -> str:
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()
    scores = {
        intent: sum(1 for kw in kws if kw in text)
        for intent, kws in INTENT_KEYWORDS.items()
    }
    scores = {k: v for k, v in scores.items() if v > 0}
    if not scores:
        return "UNKNOWN"
    return max(scores, key=lambda k: (scores[k], -(PRIORITY.index(k))))


def _is_duplicate(title: str, produced: list[dict]) -> bool:
    return any(_sim(title.lower(), p.get("title", "").lower()) > 0.85
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


def _strip(html: str) -> str:
    return re.sub(r'<[^>]+>', '', html).strip()
