import os
import sys
import pytz
from datetime import datetime
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

from db           import init_db, already_posted, title_already_posted, mark_posted, get_today_count
from fetcher      import fetch_articles
from deduplicator import deduplicate
from scorer       import score_article
from generator    import generate_post, generate_image
from publisher    import post_to_facebook
from trending     import get_trending_topics
# from publisher import post_to_instagram  # uncomment when ready
# from publisher import post_to_twitter    # uncomment when ready
# from publisher import post_to_telegram   # uncomment when ready

PKT            = pytz.timezone("Asia/Karachi")
FB_DAILY_LIMIT = 10

def run_pipeline():
    now = datetime.now(PKT)
    print(f"\n{'='*50}")
    print(f"Pipeline started: {now.strftime('%d %b %Y %I:%M %p PKT')}")
    print(f"{'='*50}")

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

        if not fresh:
            print("No new important articles found.")
            return

        for article in fresh:
            if fb_count >= FB_DAILY_LIMIT:
                break

            print(f"\nProcessing: {article['title']}")
            print(f"Score: {article['score']} | Type: {article['source_type']}")

            content = generate_post(article)
            if not content:
                print("Content failed. Trying next...")
                continue

            print(f"Post: {content.get('post_text','')[:100]}...")

            image_path = None
            try:
                image_path = generate_image(
                    content["image_keywords"],
                    content.get("image_headline", article["title"]),
                    article["source_type"],
                    article.get("level", 3) == 1
                )
            except Exception as e:
                print(f"Image error: {e}")

            if not image_path:
                print("Image failed. Trying next...")
                continue

            fb_result = post_to_facebook(content["post_text"], image_path)

            if fb_result is None:
                print("Fatal FB token error. Stopping.")
                return
            elif fb_result:
                mark_posted(conn, article["hash"], article["title"], "facebook")
                fb_count += 1
                print(f"[FB {fb_count}/{FB_DAILY_LIMIT}] Posted ✅")

                # ── Instagram (uncomment when ready) ──────
                # ig_result = post_to_instagram(content["post_text"], image_path)
                # if ig_result:
                #     mark_posted(conn, article["hash"], article["title"], "instagram")
                #     print(f"[IG] Posted ✅")

                # ── Twitter (uncomment when ready) ────────
                # tw_result = post_to_twitter(content["post_text"], image_path)
                # if tw_result:
                #     mark_posted(conn, article["hash"], article["title"], "twitter")
                #     print(f"[TW] Posted ✅")

                # ── Telegram (uncomment when ready) ───────
                # tg_result = post_to_telegram(content["post_text"], image_path)
                # if tg_result:
                #     mark_posted(conn, article["hash"], article["title"], "telegram")
                #     print(f"[TG] Posted ✅")

            else:
                print("Facebook failed. Trying next...")

            try:
                os.unlink(image_path)
            except:
                pass

            if fb_result:
                break

        print(f"\n{'='*50}")
        print(f"Facebook: {fb_count}/{FB_DAILY_LIMIT}")
        print(f"Finished: {datetime.now(PKT).strftime('%I:%M %p PKT')}")
        print(f"{'='*50}")

    finally:
        conn.close()

if __name__ == "__main__":
    run_pipeline()