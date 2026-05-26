import feedparser
import hashlib
import re
import requests
from html import unescape
from datetime import datetime, timedelta, timezone

PAKISTAN_SOURCES = [
    "https://www.geo.tv/rss/1/0",
    "https://arynews.tv/feed/",
]

WORLD_SOURCES = [
    "https://feeds.reuters.com/reuters/worldNews",
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.france24.com/en/rss",
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/international/rss",
    "https://www.independent.co.uk/news/world/rss",
    "https://rss.dw.com/rss/en-all",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.smh.com.au/rss/world.xml",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsPoster/1.0)"}

def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def is_fresh(entry, hours=8):
    if not hasattr(entry, "published_parsed") or not entry.published_parsed:
        return False
    try:
        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        age       = datetime.now(timezone.utc) - published
        return age <= timedelta(hours=hours)
    except:
        return False

def fetch_feed(url, timeout=10):
    """Fetch RSS with proper timeout using requests"""
    try:
        r    = requests.get(url, headers=HEADERS, timeout=timeout)
        feed = feedparser.parse(r.text)
        return feed
    except requests.Timeout:
        print(f"  ✗ Timeout: {url}")
        return None
    except Exception as e:
        print(f"  ✗ Error {url}: {e}")
        return None

def fetch_articles():
    articles  = []
    seen_urls = set()

    print("Fetching Pakistan sources...")
    for url in PAKISTAN_SOURCES:
        feed = fetch_feed(url)
        if not feed:
            continue
        count = 0
        for entry in feed.entries:
            if not is_fresh(entry):
                continue
            link = getattr(entry, "link", None)
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            articles.append({
                "title":       clean_text(entry.title),
                "summary":     clean_text(entry.get("summary", entry.title)),
                "url":         link,
                "source_type": "pakistan",
                "source_url":  url,
                "hash":        hashlib.md5(link.encode()).hexdigest()
            })
            count += 1
        print(f"  ✓ {url.split('/')[2]} → {count} articles")

    print("Fetching World sources...")
    for url in WORLD_SOURCES:
        feed = fetch_feed(url)
        if not feed:
            continue
        count = 0
        for entry in feed.entries:
            if not is_fresh(entry):
                continue
            link = getattr(entry, "link", None)
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            articles.append({
                "title":       clean_text(entry.title),
                "summary":     clean_text(entry.get("summary", entry.title)),
                "url":         link,
                "source_type": "world",
                "source_url":  url,
                "hash":        hashlib.md5(link.encode()).hexdigest()
            })
            count += 1
        print(f"  ✓ {url.split('/')[2]} → {count} articles")

    print(f"\nTotal fetched: {len(articles)} articles")
    return articles