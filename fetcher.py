import feedparser
import hashlib
import requests
from html import unescape
import re
from datetime import datetime, timedelta

PAKISTAN_SOURCES = [
    "https://tribune.com.pk/feed/breaking-news",     # Express Tribune
    "https://www.thenews.com.pk/rss/1/16",          # The News International
    "https://www.pakistantoday.com.pk/feed/",        # Pakistan Today
    "https://brecorder.com/feed",                    # Business Recorder
]

WORLD_SOURCES = [
    # BBC
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/rss.xml",
    # Al Jazeera
    "https://www.aljazeera.com/xml/rss/all.xml",
    # France 24
    "https://www.france24.com/en/rss",
    # The Guardian
    "https://www.theguardian.com/world/rss",
    "https://www.theguardian.com/international/rss",
    # The Independent
    "https://www.independent.co.uk/news/world/rss",
    # DW (fixed URL)
    "https://rss.dw.com/atom/rss-en-all",
    # Sky News
    "https://feeds.skynews.com/feeds/rss/world.xml",
    # NPR
    "https://feeds.npr.org/1001/rss.xml",
    # Spiegel International
    "https://www.spiegel.de/international/index.rss",
    # Sydney Morning Herald
    "https://www.smh.com.au/rss/world.xml",
    # NYT World
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    # CBS News World
    "https://www.cbsnews.com/latest/rss/world",
]

def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def is_fresh(entry):
    # No date = reject (don't allow unknown age articles)
    if not hasattr(entry, "published_parsed") or not entry.published_parsed:
        return False

    try:
        published = datetime(*entry.published_parsed[:6])
        age = datetime.utcnow() - published

        # Only accept articles from last 6 hours
        return age <= timedelta(hours=6)

    except:
        return False  # reject if date parsing fails
def fetch_articles():
    articles = []
    seen_urls = set()

    def fetch_feed(url):
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return feedparser.parse(r.content)
        except requests.exceptions.Timeout:
            print(f"  ✗ Timeout: {url}")
            return None
        except Exception as e:
            print(f"  ✗ Error {url}: {e}")
            return None

    print("Fetching Pakistan sources...")
    for url in PAKISTAN_SOURCES:
        feed = fetch_feed(url)
        if not feed:
            continue
        count = 0
        for entry in feed.entries:
            if not is_fresh(entry):
                continue
            if entry.link in seen_urls:
                continue
            seen_urls.add(entry.link)
            articles.append({
                "title":       clean_text(entry.title),
                "summary":     clean_text(entry.get("summary", entry.title)),
                "url":         entry.link,
                "source_type": "pakistan",
                "source_url":  url,
                "hash":        hashlib.md5(entry.link.encode()).hexdigest()
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
            if entry.link in seen_urls:
                continue
            seen_urls.add(entry.link)
            articles.append({
                "title":       clean_text(entry.title),
                "summary":     clean_text(entry.get("summary", entry.title)),
                "url":         entry.link,
                "source_type": "world",
                "source_url":  url,
                "hash":        hashlib.md5(entry.link.encode()).hexdigest()
            })
            count += 1
        print(f"  ✓ {url.split('/')[2]} → {count} articles")

    print(f"\nTotal fetched: {len(articles)} articles")
    return articles