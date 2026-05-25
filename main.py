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
from publisher    import post_to_facebook, post_to_instagram

PKT            = pytz.timezone("Asia/Karachi")
FB_DAILY_LIMIT = 10
IG_DAILY_LIMIT = 5
# IG_POST_HOURS  = {8, 11, 14, 17, 20}

# def should_post_instagram():
#     return datetime.now(PKT).hour in IG_POST_HOURS

def run_pipeline():
    now = datetime.now(PKT)
    print(f"\n{'='*50}")
    print(f"Pipeline started: {now.strftime('%d %b %Y %I:%M %p PKT')}")
    print(f"{'='*50}")

    conn = init_db()
    try:
        fb_count = get_today_count(conn, "facebook")
        ig_count = get_today_count(conn, "instagram")
        post_ig = ig_count < IG_DAILY_LIMIT

        print(f"FB: {fb_count}/10 | IG: {ig_count}/5 | IG hour: {post_ig}")

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

            print(f"Post: {content['post_text'][:100]}...")
            print(f"Keywords: {content['image_keywords']}")

            try:
                image_path = generate_image(
                    content["image_keywords"],
                    content.get("image_headline", article["title"]),
                    article["source_type"],
                    article.get("level", 3) == 1
                )
            except Exception as e:
                print(f"Image error: {e}")
                image_path = None

            if not image_path:
                print("Image failed. Trying next article...")
                continue

            # Post to Facebook
            success = post_to_facebook(content["post_text"], image_path)

            if success is None:
                print("Fatal token error. Stopping.")
                return
            elif success:
                mark_posted(conn, article["hash"], article["title"], "facebook")
                fb_count += 1
                print(f"[FB {fb_count}/10] Posted")

                # Post to Instagram at specific hours only
                if post_ig:
                    ig_success = post_to_instagram(
                        content["post_text"],
                        image_path
                    )
                    if ig_success:
                        mark_posted(conn, article["hash"], article["title"], "instagram")
                        ig_count += 1
                        print(f"[IG {ig_count}/5] Posted")
                    post_ig = False

                try:
                    os.unlink(image_path)
                except:
                    pass
                break
            else:
                print("Facebook failed. Trying next article...")
                try:
                    os.unlink(image_path)
                except:
                    pass
                continue

        print(f"\n{'='*50}")
        print(f"Facebook: {fb_count}/10 | Instagram: {ig_count}/5")
        print(f"Finished: {datetime.now(PKT).strftime('%I:%M %p PKT')}")
        print(f"{'='*50}")

    finally:
        conn.close()

if __name__ == "__main__":
    run_pipeline()