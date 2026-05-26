import re

PAKISTAN_KEYWORDS = [
    "pakistan", "karachi", "lahore", "islamabad", "rawalpindi",
    "peshawar", "quetta", "sindh", "punjab", "kpk", "balochistan",
    "rupee", "sbp", "imran", "pmln", "pti", "army", "ispr",
    "shehbaz", "nawaz", "zardari", "bilawal",
    "pakistan army", "pakistan cricket", "pcb",
    "shaheen", "babar azam", "pakistan economy",
    "pakistan flood", "pakistan election"
]

PAKISTAN_IMPORTANT_TOPICS = [
    # Politics
    "election", "parliament", "senate", "assembly", "cabinet",
    "prime minister", "president", "chief minister", "governor",
    "verdict", "court", "supreme court", "arrest", "resign",
    "imran khan", "shehbaz", "nawaz sharif", "zardari", "bilawal",
    "pti", "pmln", "ppp", "ispr",
    # Security
    "army", "military", "operation", "attack", "blast", "bomb",
    "terrorist", "terrorism", "ttp", "killed", "dead", "casualties",
    "border", "india pakistan", "afghanistan",
    # Economy
    "imf", "rupee", "inflation", "budget", "economy", "economic",
    "sbp", "interest rate", "gdp", "debt", "loan", "bailout",
    "cpec", "investment", "trade", "fuel prices", "electricity",
    "power crisis",
    # Disasters
    "flood", "earthquake", "disaster", "drought", "heatwave",
    "emergency", "relief", "rescue",
    # Diplomacy
    "india", "china", "us", "iran", "saudi", "un",
    "foreign minister", "diplomat", "sanction", "summit",
    # Sports (major only)
    "test match", "world cup", "babar azam", "shaheen",
]

# Trending/viral important topics globally
TRENDING_KEYWORDS = [
    "breaking", "just in", "developing", "urgent", "alert",
    "live updates", "exclusive", "confirmed", "official",
    "world record", "historic", "unprecedented", "first ever",
    "major", "massive", "huge", "significant",
]

BREAKING_KEYWORDS = [
    "breaking", "urgent", "killed", "dead", "attack", "blast",
    "bomb", "earthquake", "flood", "fire", "crash", "arrested",
    "resign", "war", "missile", "strike", "crisis", "election",
    "verdict", "protest", "emergency", "explosion", "rescue",
    "hostage", "shooting", "violence", "collapse", "disaster",
    "death toll", "casualties", "ceasefire", "offensive", "invasion",
    "vote", "referendum", "sanctions", "airstrike", "bombing",
    "massacre", "genocide", "famine", "assassination", "coup",
]

WORLD_MAJOR_KEYWORDS = [
    "war", "nuclear", "nato", "tsunami", "earthquake",
    "assassination", "coup", "pandemic", "us president",
    "china", "russia", "israel", "gaza", "iran",
    "ceasefire", "sanctions", "un security council",
    "world leader", "climate crisis", "recession",
    "terror attack", "genocide", "famine", "refugee crisis",
    "missile strike", "drone attack", "peace deal",
    "economic crisis", "global summit", "world war",
    "invasion", "occupation", "airstrike", "chemical weapon",
    "nuclear weapon", "mass shooting", "natural disaster",
]

# Useless/low quality — never post
BLOCKED_KEYWORDS = [
    # Sexual content
    "sex tape", "sex work", "sex scandal", "sex crime",
    "sex trafficking", "sexual", "sexuality", "intercourse",
    "nude", "naked", "porn", "pornography", "adult content",
    "explicit content", "erotic", "xxx", "onlyfans",
    "prostitution", "rape", "sexual assault", "sex differences",
    "seductive", "lingerie", "strip club", "escort service",
    "hookup", "intimate photos", "leaked photos",
    "private video", "nsfw",

    # Celebrity gossip
    "taylor swift", "beyonce", "kardashian",
    "meghan markle", "prince harry drama",
    "bollywood gossip", "hollywood gossip",
    "grammy", "oscar", "emmy", "golden globe", "red carpet",
    "star wars", "marvel", "disney movie", "anime",
    "box office", "movie trailer", "netflix series",
    "sitcom", "reality show", "talk show",

    # Gossip
    "rumour", "rumor", "gossip", "breakup", "baby shower",
    "badmouthing", "speaks out", "breaks silence",
    "claps back", "responds to haters", "reveals dating",

    # Useless
    "horoscope", "zodiac", "viral video", "funny video",
    "meme", "tiktok trend", "instagram reel",
    "sponsored content", "advertisement", "listicle",
    "best restaurants", "travel tips", "recipe",
    "fashion tips", "beauty tips", "weight loss",

    # Low quality Pakistan news
    "property award", "real estate award", "housing society",
    "launches project", "inaugurates", "ribbon cutting",
    "corporate news", "product launch",
]

def _is_blocked(text, keyword):
    if " " in keyword:
        return keyword in text
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))

def score_article(article, trending_topics=None):
    title   = article["title"].lower()
    summary = article["summary"].lower()
    text    = title + " " + summary
    source  = article.get("source_type", "world")
    score   = 0
    level   = 5

    # Block immediately
    for kw in BLOCKED_KEYWORDS:
        if _is_blocked(text, kw):
            print(f"  ✗ Blocked: '{article['title'][:50]}' [{kw}]")
            return 0, 5

    # Minimum content
    if len(article.get("summary", "").strip()) < 100:
        return 0, 5

    # ── Trending boost (real Google Trends) ──────────────
    if trending_topics:
        for trend in trending_topics:
            if len(trend) > 3 and trend in text:
                score += 35
                print(f"  🔥 Trending match: '{trend}'")
                break

    # Pakistan news scoring
    if source == "pakistan":
        has_pk_keyword = any(kw in text for kw in PAKISTAN_KEYWORDS)
        if not has_pk_keyword:
            return 0, 5

        has_important = any(kw in text for kw in PAKISTAN_IMPORTANT_TOPICS)
        has_breaking  = any(kw in text for kw in BREAKING_KEYWORDS)
        has_trending  = any(kw in title for kw in TRENDING_KEYWORDS)

        if not has_important and not has_breaking:
            print(f"  ✗ Pakistan skip (not important): '{article['title'][:50]}'")
            return 0, 5

        title_important = any(kw in title for kw in PAKISTAN_IMPORTANT_TOPICS)
        title_breaking  = any(kw in title for kw in BREAKING_KEYWORDS)
        if not title_important and not title_breaking:
            print(f"  ✗ Pakistan skip (keyword only in summary): '{article['title'][:50]}'")
            return 0, 5

        score += 50
        level  = 2
        if has_breaking:
            score += 40
            level  = 1
        if has_trending:
            score += 20

    # World news scoring
    elif source == "world":
        title_major    = any(kw in title for kw in WORLD_MAJOR_KEYWORDS)
        title_breaking = any(kw in title for kw in BREAKING_KEYWORDS)
        title_trending = any(kw in title for kw in TRENDING_KEYWORDS)

        if not title_major and not title_breaking:
            return 0, 5

        score += 30
        level  = 3
        if title_breaking:
            score += 30
            level  = 2
        if title_trending:
            score += 15
        if title_major and title_breaking:
            score += 20
            level  = 1

    # Multi-source boost
    score += len(article.get("sources", [])) * 10

    # Detail boost
    score += min(len(article["summary"]) // 100, 15)

    return score, level