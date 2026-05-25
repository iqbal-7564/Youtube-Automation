import feedparser
import hashlib
from html import unescape
import re
from datetime import datetime, timedelta

PAKISTAN_SOURCES = [
    "https://www.geo.tv/rss/1/0",    # Geo News — 50 articles
    "https://arynews.tv/feed/",       # ARY News — 224 articles
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

def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def is_fresh(entry):
    if not hasattr(entry, "published_parsed") or not entry.published_parsed:
        return False
    try:
        published = datetime(*entry.published_parsed[:6])
        age = datetime.utcnow() - published
        return age <= timedelta(hours=6)
    except:
        return False

def fetch_articles():
    articles = []
    seen_urls = set()

    print("Fetching Pakistan sources...")
    for url in PAKISTAN_SOURCES:
        try:
            feed = feedparser.parse(url)
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
        except Exception as e:
            print(f"  ✗ Error {url}: {e}")

    print("Fetching World sources...")
    for url in WORLD_SOURCES:
        try:
            feed = feedparser.parse(url)
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
        except Exception as e:
            print(f"  ✗ Error {url}: {e}")

    print(f"\nTotal fetched: {len(articles)} articles")
    return articles