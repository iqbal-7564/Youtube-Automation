import os
import pytz
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from db           import init_db, already_posted, title_already_posted, mark_posted, get_today_count
from fetcher      import fetch_articles
from deduplicator import deduplicate
from scorer       import score_article
from generator    import generate_post, generate_image
from publisher    import post_to_facebook

PKT            = pytz.timezone("Asia/Karachi")
FB_DAILY_LIMIT = 10

def run_pipeline():
    now = datetime.now(PKT)
    print(f"\n{'='*50}")
    print(f"Pipeline started: {now.strftime('%d %b %Y %I:%M %p PKT')}")
    print(f"{'='*50}")

    conn = init_db()
    try:
        fb_count = get_today_count(conn, "facebook")

        if fb_count >= FB_DAILY_LIMIT:
            print(f"Daily limit reached ({fb_count}/10). Stopping.")
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
            score, level = score_article(a)
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
                print("Content generation failed. Trying next article...")
                continue

            print(f"Post text: {content['post_text'][:100]}...")
            print(f"Image keywords: {content['image_keywords']}")

            image_path = generate_image(
                content["image_keywords"],
                content.get("image_headline", article["title"]),
                article["source_type"],
                article.get("level", 3) == 1
            )
            if not image_path:
                print("Image generation failed. Trying next article...")
                continue

            success = post_to_facebook(content["post_text"], image_path)

            try:
                os.unlink(image_path)
            except:
                pass

            if success is None:
                print("Token expired — stopping pipeline. Update FB_PAGE_TOKEN in secrets.")
                return
            elif success:
                mark_posted(conn, article["hash"], article["title"], "facebook")
                fb_count += 1
                print(f"[FB {fb_count}/10] Successfully posted")
                break
            else:
                print("Facebook posting failed. Trying next article...")
                continue

        print(f"\n{'='*50}")
        print(f"Facebook today: {fb_count}/10")
        print(f"Pipeline finished: {datetime.now(PKT).strftime('%I:%M %p PKT')}")
        print(f"{'='*50}")

    finally:
        conn.close()

if __name__ == "__main__":
    run_pipeline()
