import time
import requests

def get_trending_topics():
    trending = []

    # Method 1 — pytrends (may fail on GitHub Actions)
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=300, timeout=(5, 10))

        try:
            pk = pytrends.trending_searches(pn="pakistan")
            trending += pk[0].tolist()[:10]
            print(f"  Pakistan trends: {pk[0].tolist()[:5]}")
            time.sleep(1)
        except:
            pass

        try:
            us = pytrends.trending_searches(pn="united_states")
            trending += us[0].tolist()[:8]
            time.sleep(1)
        except:
            pass

    except Exception as e:
        print(f"  pytrends unavailable: {e}")

    # Method 2 — RSS based trending (always works)
    # Topics covered by 3+ sources = trending
    try:
        trending_rss = _get_rss_trending()
        trending    += trending_rss
        print(f"  RSS trends found: {len(trending_rss)}")
    except Exception as e:
        print(f"  RSS trending error: {e}")

    # Method 3 — Hardcoded always-important topics as fallback
    if not trending:
        trending = [
            "pakistan", "imf", "army", "blast", "flood",
            "election", "court", "israel", "gaza", "iran",
            "ukraine", "russia", "china", "us", "war",
            "economy", "rupee", "inflation", "attack", "killed"
        ]
        print("  Using fallback trending topics")

    # Clean and deduplicate
    trending = list(set([
        t.lower().strip()
        for t in trending
        if t and len(t) > 2
    ]))

    print(f"  Total trending topics: {len(trending)}")
    return trending

def _get_rss_trending():
    """Extract trending topics from top news RSS feeds"""
    import feedparser
    from collections import Counter

    TRENDING_SOURCES = [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://feeds.reuters.com/reuters/topNews",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ]

    word_count = Counter()
    SKIP_WORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on",
        "at", "to", "for", "of", "with", "as", "by", "from",
        "that", "this", "it", "is", "are", "was", "were",
        "be", "been", "have", "has", "had", "will", "would",
        "could", "should", "may", "might", "its", "their",
        "after", "over", "about", "into", "than", "more",
        "new", "says", "said", "says", "amid"
    }

    for url in TRENDING_SOURCES:
        try:
            r    = requests.get(url, timeout=8,
                               headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(r.text)
            for entry in feed.entries[:15]:
                words = entry.title.lower().split()
                for word in words:
                    word = word.strip(".,!?:;\"'()-")
                    if word and word not in SKIP_WORDS and len(word) > 3:
                        word_count[word] += 1
        except:
            continue

    # Words appearing 3+ times across sources = trending
    return [word for word, count in word_count.items() if count >= 3]