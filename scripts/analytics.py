import os
import json
import requests
from pathlib import Path
from datetime import datetime
from notify import send_telegram

OUTPUT_DIR            = Path("output")
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")
ANALYTICS_FILE        = Path("analytics.json")

def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    })
    return r.json().get("access_token")

def load_analytics():
    if ANALYTICS_FILE.exists():
        try:
            with open(ANALYTICS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"videos": [], "total_views": 0, "best_video": None}

def save_analytics(data):
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_channel_stats(token):
    """Get channel overview stats"""
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        headers={"Authorization": f"Bearer {token}"},
        params={"part": "statistics", "mine": "true"},
        timeout=10
    )
    data = r.json()
    if "items" in data and data["items"]:
        stats = data["items"][0]["statistics"]
        return {
            "subscribers":  stats.get("subscriberCount", 0),
            "total_views":  stats.get("viewCount", 0),
            "video_count":  stats.get("videoCount", 0),
        }
    return {}

def get_recent_video_stats(token):
    """Get stats for recent videos"""
    # Get recent videos
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "part":       "snippet",
            "forMine":    "true",
            "type":       "video",
            "maxResults": "10",
            "order":      "date",
        },
        timeout=10
    )
    items    = r.json().get("items", [])
    video_ids = [i["id"]["videoId"] for i in items if "videoId" in i.get("id", {})]
    if not video_ids:
        return []

    # Get stats for these videos
    r2 = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "part": "statistics,snippet",
            "id":   ",".join(video_ids),
        },
        timeout=10
    )
    videos = []
    for item in r2.json().get("items", []):
        stats = item.get("statistics", {})
        videos.append({
            "id":          item["id"],
            "title":       item["snippet"]["title"],
            "views":       int(stats.get("viewCount", 0)),
            "likes":       int(stats.get("likeCount", 0)),
            "comments":    int(stats.get("commentCount", 0)),
            "published":   item["snippet"]["publishedAt"],
        })
    return sorted(videos, key=lambda x: x["views"], reverse=True)

def generate_weekly_report():
    """Generate and send weekly analytics report"""
    print("📊 Generating analytics report...")
    try:
        token   = get_access_token()
        channel = get_channel_stats(token)
        videos  = get_recent_video_stats(token)

        analytics = load_analytics()

        best_video = videos[0] if videos else None
        worst_video = videos[-1] if videos else None

        report = (
            f"📊 <b>MindBlownFacts Weekly Report</b>\n\n"
            f"👥 Subscribers: {int(channel.get('subscribers',0)):,}\n"
            f"👁️ Total Views: {int(channel.get('total_views',0)):,}\n"
            f"🎬 Total Videos: {channel.get('video_count',0)}\n\n"
        )

        if best_video:
            report += (
                f"🏆 <b>Best Recent Video:</b>\n"
                f"📹 {best_video['title'][:50]}\n"
                f"👁️ Views: {best_video['views']:,}\n"
                f"👍 Likes: {best_video['likes']:,}\n\n"
            )

        if worst_video and worst_video != best_video:
            report += (
                f"📉 <b>Needs Improvement:</b>\n"
                f"📹 {worst_video['title'][:50]}\n"
                f"👁️ Views: {worst_video['views']:,}\n\n"
            )

        # Save analytics
        analytics["channel"]    = channel
        analytics["last_check"] = datetime.utcnow().isoformat()
        analytics["videos"]     = videos[:10]
        save_analytics(analytics)

        send_telegram(report)
        print("✅ Report sent!")

    except Exception as e:
        print(f"Analytics failed: {e}")

if __name__ == "__main__":
    generate_weekly_report()