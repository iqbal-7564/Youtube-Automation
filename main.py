from trending import get_trending_topics

def run_pipeline():
    now = datetime.now(PKT)
    print(f"\n{'='*50}")
    print(f"Pipeline started: {now.strftime('%d %b %Y %I:%M %p PKT')}")
    print(f"{'='*50}")

    # Fetch trending topics first
    print("\nFetching trending topics...")
    trending_topics = get_trending_topics()

    conn = init_db()
    try:
        fb_count = get_today_count(conn, "facebook")
        print(f"FB: {fb_count}/{FB_DAILY_LIMIT}")

        if fb_count >= FB_DAILY_LIMIT:
            print(f"Daily FB limit reached. Stopping.")
            return

        articles = fetch_articles()
        if not articles:
            print("No articles fetched. Stopping.")
            return

        merged = deduplicate(articles)

        fresh = []
        for a in merged:
            if already_posted(conn, a["hash"]):
                continue
            # Pass trending topics to scorer
            score, level = score_article(a, trending_topics)
            if level == 5:
                continue
            if title_already_posted(conn, a["title"]):
                continue
            a["score"] = score
            a["level"] = level
            fresh.append(a)

        fresh.sort(key=lambda x: x["score"], reverse=True)
        print(f"Qualified articles: {len(fresh)}")

        # rest of pipeline unchanged...