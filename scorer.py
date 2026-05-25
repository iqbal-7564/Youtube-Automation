import re

PAKISTAN_KEYWORDS = [
    "pakistan", "karachi", "lahore", "islamabad", "rawalpindi",
    "peshawar", "quetta", "sindh", "punjab", "kpk", "balochistan",
    "rupee", "sbp", "imran", "pmln", "pti", "army", "ispr",
    "shehbaz", "nawaz", "zardari", "bilawal", "pakistan army",
    "pakistan cricket", "pcb", "shaheen", "babar azam",
    "pakistan economy", "pakistan flood", "pakistan election"
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
    # Sexual content — 100% blocked (use full phrases to avoid false positives)
    "sex tape", "sex work", "sex scandal", "sex crime", "sex trafficking",
    "sexual", "nude", "naked", "porn", "pornography",
    "adult content", "explicit content", "erotic", "xxx", "onlyfans",
    "prostitution", "rape", "sexual assault",
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
    "meghan", "markle", "royal gossip",
"nightmare", "exposed",

    # Gossip
    "rumour", "rumor", "gossip", "breakup", "divorce",
    "baby shower", "affair details", "badmouthing",
    "speaks out", "breaks silence", "claps back",
    "responds to haters", "reveals dating",

    # Useless
    "horoscope", "zodiac", "viral video", "meme",
    "tiktok", "instagram reel", "influencer",
    "sponsored", "advertisement", "listicle",
    "best restaurants", "travel tips", "recipe",

    # Royal gossip
    "prince george", "princess anne gossip",
    "meghan markle", "prince harry drama",

    # Sports entertainment
    "fans furious", "fans react", "fan theory",
    # Academic/controversial gender content
"sex differences",
"sex difference",
"billion years of sex",
"evolutionary psychology",
"nature vs nurture",
"gender differences",
"men and women differences",
"stewart-williams",

# Any sex-related content
"sex",
"sexual",
"sexuality",
"intercourse",

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
     if kw in text:
        print(f"  ✗ Blocked: '{article['title'][:50]}' [{kw}]")
        return 0, 5

    # Minimum content check
    if len(article.get("summary", "")) < 80:
        return 0, 5

    # Pakistan news
    if source == "pakistan":
        if any(kw in text for kw in PAKISTAN_KEYWORDS):
            score += 50
            level  = 2
            if any(kw in text for kw in BREAKING_KEYWORDS):
                score += 40
                level  = 1
        elif any(kw in text for kw in BREAKING_KEYWORDS):
            score += 40
            level  = 2
        else:
            return 0, 5

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
