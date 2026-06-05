"""
News Monitor — Trending news → facts angle video trigger

Checks Google News RSS every hour.
If breaking news matches our categories → extracts facts angle
→ writes trigger file → pipeline picks it up as bonus video.

Rules:
- Max 1 bonus video per day
- Standard format only (4-5 min)
- Facts angle only — never reports news
- Wikipedia verified before triggering
- Min score 70/100 before triggering
"""

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_LOGS_DIR    = Path(__file__).parent.parent / "logs"
_TRIGGER_PATH = _LOGS_DIR / "news_trigger.json"

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"

# Google News RSS feeds per category — free, no API key
_NEWS_FEEDS: dict[str, str] = {
    "SPACE":       "https://news.google.com/rss/search?q=space+nasa+discovery&hl=en",
    "SCIENCE":     "https://news.google.com/rss/search?q=science+discovery+research&hl=en",
    "HISTORY":     "https://news.google.com/rss/search?q=ancient+history+archaeology&hl=en",
    "ANIMALS":     "https://news.google.com/rss/search?q=animal+wildlife+discovery&hl=en",
    "NATURE":      "https://news.google.com/rss/search?q=nature+earth+environment&hl=en",
    "OCEAN":       "https://news.google.com/rss/search?q=ocean+deep+sea+discovery&hl=en",
    "TECHNOLOGY":  "https://news.google.com/rss/search?q=technology+ai+innovation&hl=en",
    "PSYCHOLOGY":  "https://news.google.com/rss/search?q=psychology+brain+research&hl=en",
    "MYTHOLOGY":   "https://news.google.com/rss/search?q=ancient+mythology+discovery&hl=en",
    "MEDICINE":    "https://news.google.com/rss/search?q=medical+discovery+health&hl=en",
    "PHYSICS":     "https://news.google.com/rss/search?q=physics+quantum+discovery&hl=en",
}

# Keywords that indicate genuinely big/interesting news
_HIGH_VALUE_KEYWORDS = [
    "discovered", "found", "reveals", "breakthrough", "first time",
    "never before", "ancient", "extinct", "impossible", "mystery",
    "scientists", "researchers", "study", "proof", "evidence",
    "million years", "billion years", "new species", "new planet",
]


def _already_triggered_today() -> bool:
    """Max 1 bonus video per day."""
    try:
        if not _TRIGGER_PATH.exists():
            return False
        data = json.loads(_TRIGGER_PATH.read_text())
        today = datetime.utcnow().date().isoformat()
        return data.get("date") == today and data.get("used", False)
    except Exception:
        return False


def _fetch_news(category: str) -> list[dict]:
    """Fetch RSS feed and return top 5 stories."""
    url = _NEWS_FEEDS.get(category)
    if not url:
        return []
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        root  = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            if title:
                items.append({
                    "title": title,
                    "desc":  re.sub(r"<[^>]+>", "", desc)[:300],
                    "pub":   pub,
                })
        return items
    except Exception as exc:
        log.debug("RSS fetch [%s]: %s", category, exc)
        return []


def _score_story(title: str, desc: str) -> int:
    """Score news story 0-100 for facts video potential."""
    text  = (title + " " + desc).lower()
    score = 0
    for kw in _HIGH_VALUE_KEYWORDS:
        if kw in text:
            score += 6
    # Bonus for specific numbers
    if re.search(r"\d+\s*(million|billion|thousand|years?|km|species)", text):
        score += 10
    return min(100, score)


def _groq_facts_angle(news_title: str, category: str) -> tuple[str, str]:
    """Convert news headline into facts video topic using Groq."""
    keys = [
        os.getenv("GROQ_API_KEY_1", "").strip(),
        os.getenv("GROQ_API_KEY_2", "").strip(),
    ]
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
                            "Convert a news headline into a mind-blowing FACTS video topic. "
                            "NOT a news report — extract the deeper WHY/HOW facts angle. "
                            "Return ONLY valid JSON: {\"title\": \"...\", \"description\": \"...\"} "
                            "Title: question format starting with Why/How/What, max 70 chars. "
                            "Description: the most surprising fact this news reveals, 1-2 sentences."
                        ),
                    }, {
                        "role": "user",
                        "content": (
                            f"News: {news_title}\n"
                            f"Category: {category}\n"
                            "Extract the mind-blowing facts angle — not the news itself."
                        ),
                    }],
                    "temperature": 0.7,
                    "max_tokens":  200,
                },
                timeout=20,
            )
            if r.ok:
                raw = r.json()["choices"][0]["message"]["content"].strip()
                m   = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    if data.get("title"):
                        return data["title"], data.get("description", "")
        except Exception as exc:
            log.debug("Groq facts angle: %s", exc)
    return "", ""


def _wikipedia_verify(title: str) -> bool:
    """Quick Wikipedia check — does this topic have a real article?"""
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search",
                    "srsearch": title, "srlimit": "1", "format": "json"},
            timeout=8,
        )
        if r.ok:
            return len(r.json().get("query", {}).get("search", [])) > 0
    except Exception:
        pass
    return False


_QUEUE_PATH = _LOGS_DIR / "news_queue.json"


def _load_queue() -> list[dict]:
    """Load accumulated trending topics queue."""
    try:
        if _QUEUE_PATH.exists():
            data = json.loads(_QUEUE_PATH.read_text())
            # Keep only topics from last 24 hours
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            return [t for t in data if t.get("found_at", "") >= cutoff]
    except Exception:
        pass
    return []


def _save_queue(queue: list[dict]) -> None:
    """Save queue keeping last 50 entries."""
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _QUEUE_PATH.write_text(json.dumps(queue[-50:], indent=2))
    except Exception:
        pass


def _save_best_trigger(queue: list[dict]) -> None:
    """Pick highest scoring topic from queue and save as trigger."""
    if not queue:
        return
    best = max(queue, key=lambda x: x.get("news_score", 0))
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _TRIGGER_PATH.write_text(json.dumps({
        "date":    datetime.utcnow().date().isoformat(),
        "used":    False,
        "topic":   best,
        "created": datetime.utcnow().isoformat(),
    }, indent=2))
    log.info("Best trigger saved: score=%d '%s'",
             best.get("news_score", 0), best["title"][:60])


def run_news_monitor() -> bool:
    """
    Every hour: scan news feeds, add good stories to queue.
    Queue accumulates all day — pipeline picks highest scorer at video time.
    Returns True if new topics added to queue.
    """
    queue  = _load_queue()
    added  = 0

    # Track already queued titles to avoid duplicates
    queued_titles = {t.get("seed", "").lower() for t in queue}

    for category in _NEWS_FEEDS:
        stories = _fetch_news(category)
        for story in stories:
            # Skip already in queue
            if story["title"].lower() in queued_titles:
                continue

            score = _score_story(story["title"], story["desc"])
            if score < 60:
                continue

            # Convert to facts angle
            title, description = _groq_facts_angle(story["title"], category)
            if not title:
                continue

            # Wikipedia verify
            if not _wikipedia_verify(title):
                continue

            topic = {
                "title":            title[:200],
                "description":      description[:500],
                "intent":           category,
                "source":           "NewsTrend",
                "published_at":     datetime.utcnow().isoformat(),
                "article_url":      "",
                "seed":             story["title"][:100],
                "trend_hint":       "",
                "novelty_score":    80,
                "curiosity_score":  70,
                "saturation":       "pass",
                "viral_score":      float(score),
                "performance_score": 50.0,
                "news_score":       score,
                "found_at":         datetime.utcnow().isoformat(),
            }
            queue.append(topic)
            queued_titles.add(story["title"].lower())
            added += 1
            log.info("Queued [%s] score=%d: %s", category, score, title[:55])

        time.sleep(0.5)

    _save_queue(queue)

    # Always update trigger with best topic in queue
    if queue:
        _save_best_trigger(queue)

    log.info("News monitor: +%d new topics, queue=%d, best score=%d",
             added, len(queue),
             max((t.get("news_score", 0) for t in queue), default=0))
    return added > 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    run_news_monitor()
