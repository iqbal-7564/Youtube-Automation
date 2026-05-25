import re

PAKISTAN_KEYWORDS = [
    "pakistan", "karachi", "lahore", "islamabad", "rawalpindi",
    "peshawar", "quetta", "sindh", "punjab", "kpk", "balochistan",
    "rupee", "sbp", "imran", "pmln", "pti", "army", "ispr",
    "shehbaz", "nawaz", "zardari", "bilawal", "pakistan army",
    "pakistan cricket", "pcb", "shaheen", "babar azam",
    "pakistan economy", "pakistan flood", "pakistan election"
]

# Pakistan news must also match at least one of these "worth posting" topics
PAKISTAN_IMPORTANT_TOPICS = [
    # Politics & governance
    "election", "vote", "parliament", "senate", "assembly", "cabinet",
    "prime minister", "president", "chief minister", "governor",
    "verdict", "court", "supreme court", "arrest", "resign", "impeach",
    "imran khan", "shehbaz", "nawaz sharif", "zardari", "bilawal",
    "pti", "pmln", "ppp", "ispr",

    # Security & military
    "army", "military", "operation", "attack", "blast", "bomb",
    "terrorist", "terrorism", "ttp", "killed", "dead", "casualties",
    "border", "loc", "india pakistan", "afghanistan",

    # Economy
    "imf", "rupee", "inflation", "budget", "economy", "economic",
    "sbp", "interest rate", "gdp", "debt", "loan", "bailout",
    "cpec", "investment", "trade", "oil prices", "fuel prices",
    "electricity", "power crisis", "gas",

    # Disasters & crises
    "flood", "earthquake", "disaster", "drought", "heatwave",
    "emergency", "relief", "rescue",

    # International / diplomacy
    "india", "china", "us", "united states", "iran", "saudi",
    "un", "nato", "foreign minister", "diplomat", "sanction",
    "visit", "summit",

    # Cricket & major sports
    "test match", "odi", "t20", "world cup", "series", "babar azam",
    "shaheen", "pcb", "cricket board",
]

BREAKING_KEYWORDS = [
    "breaking", "urgent", "killed", "dead", "attack", "blast",
    "bomb", "earthquake", "flood", "fire", "crash", "arrested",
    "resign", "war", "missile", "strike", "crisis", "election",
    "verdict", "protest", "emergency", "explosion", "rescue",
    "hostage", "shooting", "violence", "collapse", "disaster",
    "death toll", "casualties", "ceasefire", "offensive", "invasion",
    "vote", "referendum", "sanctions", "airstrike", "bombing"
]

WORLD_MAJOR_KEYWORDS = [
    "war", "nuclear", "nato", "tsunami", "earthquake",
    "assassination", "coup", "pandemic", "us president",
    "china", "russia", "israel", "gaza", "iran",
    "ceasefire", "sanctions", "un security council",
    "world leader", "climate crisis", "recession",
    "terror attack", "genocide", "famine", "refugee crisis",
    "missile strike", "drone attack", "peace deal",
    "economic crisis", "oil prices", "global summit"
]

BLOCKED_KEYWORDS = [
    # Sexual content
    "sex", "sex tape", "sex work", "sex scandal", "sex crime", "sex trafficking",
    "sexual", "sexuality", "intercourse", "nude", "naked", "porn", "pornography",
    "adult content", "explicit content", "erotic", "xxx", "onlyfans",
    "prostitution", "rape", "sexual assault", "sex differences", "sex difference",
    "seductive", "lingerie model", "strip club", "striptease",
    "escort service", "escort agency",
    "hookup", "affair details", "intimate photos",
    "leaked photos", "private video", "nsfw",

    # Entertainment gossip
    "actress", "singer", "musician",
    "taylor swift", "beyonce", "kardashian", "hollywood",
    "bollywood", "netflix series", "movie trailer", "box office",
    "grammy", "oscar", "emmy", "golden globe", "red carpet",
    "star wars", "marvel", "disney", "anime", "sitcom",
    "reality show", "talk show", "comedy special",

    # Gossip
    "rumour", "rumor", "gossip", "breakup", "divorce",
    "baby shower", "affair details", "badmouthing",
    "speaks out", "breaks silence", "claps back",
    "responds to haters", "reveals dating",
    "meghan markle", "prince harry drama",
    "prince george", "princess anne gossip",

    # Useless
    "horoscope", "zodiac", "viral video", "meme",
    "tiktok", "instagram reel", "influencer",
    "sponsored", "advertisement", "listicle",
    "best restaurants", "travel tips", "recipe",

    # Sports entertainment
    "fans furious", "fans react", "fan theory",
]

def _is_blocked(text, keyword):
    if " " in keyword:
        return keyword in text
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))

def score_article(article):
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

    # Minimum content check
    if len(article.get("summary", "")) < 80:
        return 0, 5

    # Pakistan news — must be about an important topic, not just any Pakistan story
    if source == "pakistan":
        has_pk_keyword   = any(kw in text for kw in PAKISTAN_KEYWORDS)
        has_important    = any(kw in text for kw in PAKISTAN_IMPORTANT_TOPICS)
        has_breaking     = any(kw in text for kw in BREAKING_KEYWORDS)

        if not has_pk_keyword:
            return 0, 5

        # Must match an important topic OR be genuinely breaking
        if not has_important and not has_breaking:
            print(f"  ✗ Pakistan skip (not important enough): '{article['title'][:60]}'")
            return 0, 5

        # Require important topic to appear in the TITLE (not just buried in summary)
        title_has_important = any(kw in title for kw in PAKISTAN_IMPORTANT_TOPICS)
        title_has_breaking  = any(kw in title for kw in BREAKING_KEYWORDS)
        if not title_has_important and not title_has_breaking:
            print(f"  ✗ Pakistan skip (important keyword only in summary): '{article['title'][:60]}'")
            return 0, 5

        score += 50
        level  = 2
        if has_breaking:
            score += 40
            level  = 1

    # World news — keyword must appear in the TITLE, not just the summary
    elif source == "world":
        title_match = (
            any(kw in title for kw in WORLD_MAJOR_KEYWORDS) or
            any(kw in title for kw in BREAKING_KEYWORDS)
        )
        if not title_match:
            return 0, 5
        score += 30
        level  = 3
        if any(kw in text for kw in BREAKING_KEYWORDS):
            score += 30
            level  = 2

    # Multiple sources covering = more important
    score += len(article.get("sources", [])) * 10

    # Longer summary = more detail = more important
    score += min(len(article["summary"]) // 80, 15)

    return score, level
