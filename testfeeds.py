import feedparser
import requests

PAKISTAN_SOURCES = [
    "https://www.geo.tv/rss/1/0",
    "https://arynews.tv/feed/",
    "https://tribune.com.pk/feed/breaking-news",
    "https://www.thenews.com.pk/rss/1/16",
    "https://www.pakistantoday.com.pk/feed/",
    "https://brecorder.com/feed",
]

for url in PAKISTAN_SOURCES:
    try:
        feed = feedparser.parse(url)
        print(f"\n{url}")
        print(f"  Status: {feed.status if hasattr(feed, 'status') else 'unknown'}")
        print(f"  Articles: {len(feed.entries)}")
        if feed.entries:
            print(f"  Latest: {feed.entries[0].title}")
            print(f"  Date: {feed.entries[0].get('published', 'NO DATE')}")
    except Exception as e:
        print(f"  Error: {e}")