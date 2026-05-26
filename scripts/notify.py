import os
import requests
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# Email config
EMAIL_SENDER    = os.environ.get("EMAIL_SENDER")    # your Gmail
EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD")  # Gmail app password
EMAIL_RECEIVER  = os.environ.get("EMAIL_RECEIVER")  # where to receive alerts

# ─── TELEGRAM ─────────────────────────────────────────────
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "text":       message,
                "parse_mode": "HTML"
            },
            timeout=10
        )
        if r.status_code == 200:
            print("✅ Telegram sent!")
            return True
        print(f"Telegram failed: {r.status_code}")
        return False
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ─── EMAIL ────────────────────────────────────────────────
def send_email(subject, body_html, body_text=""):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        print("⚠️ Email not configured")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"MindBlownFacts Bot <{EMAIL_SENDER}>"
        msg["To"]      = EMAIL_RECEIVER

        # Plain text fallback
        if not body_text:
            body_text = body_html.replace("<b>","").replace("</b>","").replace("<br>","\n")

        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Send via Gmail SMTP
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())

        print("✅ Email sent!")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ─── SEND TO ALL CHANNELS ─────────────────────────────────
def notify(subject, telegram_msg, email_html):
    """Send to both Telegram and Email"""
    send_telegram(telegram_msg)
    send_email(subject, email_html)

# ─── NOTIFICATION TYPES ───────────────────────────────────
def notify_success(video_type, title, youtube_url=""):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    telegram_msg = (
        f"✅ <b>MindBlownFacts - Video Posted!</b>\n\n"
        f"📹 Type: {video_type}\n"
        f"🎬 Title: {title[:60]}\n"
        f"🔗 {youtube_url}\n"
        f"🕐 Time: {now}"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="background:#00aa44;padding:20px;border-radius:10px;text-align:center;">
            <h1 style="color:white;margin:0;">✅ Video Posted!</h1>
        </div>
        <div style="background:#f9f9f9;padding:20px;border-radius:10px;margin-top:20px;">
            <table style="width:100%;">
                <tr><td><b>📹 Type:</b></td><td>{video_type}</td></tr>
                <tr><td><b>🎬 Title:</b></td><td>{title}</td></tr>
                <tr><td><b>🕐 Time:</b></td><td>{now}</td></tr>
                <tr><td><b>🔗 URL:</b></td><td><a href="{youtube_url}">{youtube_url}</a></td></tr>
            </table>
        </div>
        <div style="text-align:center;margin-top:20px;color:#666;">
            MindBlownFacts Automation Bot
        </div>
    </div>
    """

    notify(
        subject    = f"✅ MindBlownFacts - {video_type} Posted!",
        telegram_msg = telegram_msg,
        email_html = email_html
    )

def notify_failure(video_type, error):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    telegram_msg = (
        f"❌ <b>MindBlownFacts - WORKFLOW FAILED!</b>\n\n"
        f"📹 Type: {video_type}\n"
        f"💥 Error: {str(error)[:200]}\n"
        f"🕐 Time: {now}\n\n"
        f"⚠️ Check GitHub Actions immediately!\n"
        f"🔗 https://github.com"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="background:#cc0000;padding:20px;border-radius:10px;text-align:center;">
            <h1 style="color:white;margin:0;">❌ WORKFLOW FAILED!</h1>
        </div>
        <div style="background:#fff0f0;padding:20px;border-radius:10px;margin-top:20px;border:1px solid #ffcccc;">
            <table style="width:100%;">
                <tr><td><b>📹 Type:</b></td><td>{video_type}</td></tr>
                <tr><td><b>🕐 Time:</b></td><td>{now}</td></tr>
                <tr><td><b>💥 Error:</b></td><td style="color:red;">{str(error)[:300]}</td></tr>
            </table>
        </div>
        <div style="background:#fff3cd;padding:15px;border-radius:10px;margin-top:15px;">
            <b>⚠️ Action Required:</b><br>
            1. Check GitHub Actions for full error log<br>
            2. Fix the issue<br>
            3. Re-run the workflow manually
        </div>
        <div style="text-align:center;margin-top:20px;">
            <a href="https://github.com" 
               style="background:#0066cc;color:white;padding:10px 20px;
                      border-radius:5px;text-decoration:none;">
                Check GitHub Actions
            </a>
        </div>
    </div>
    """

    notify(
        subject      = f"❌ MindBlownFacts FAILED - {video_type}!",
        telegram_msg = telegram_msg,
        email_html   = email_html
    )

def notify_token_warning(service, days_left=0):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    telegram_msg = (
        f"⚠️ <b>TOKEN WARNING - Action Required!</b>\n\n"
        f"🔑 Service: {service}\n"
        f"📅 Expires in: {days_left} days\n"
        f"🕐 Time: {now}\n\n"
        f"Please refresh your token!"
    )

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="background:#ff8800;padding:20px;border-radius:10px;text-align:center;">
            <h1 style="color:white;margin:0;">⚠️ Token Expiring Soon!</h1>
        </div>
        <div style="background:#fff8f0;padding:20px;border-radius:10px;margin-top:20px;border:1px solid #ffcc88;">
            <table style="width:100%;">
                <tr><td><b>🔑 Service:</b></td><td>{service}</td></tr>
                <tr><td><b>📅 Expires in:</b></td><td style="color:red;">{days_left} days</td></tr>
                <tr><td><b>🕐 Checked:</b></td><td>{now}</td></tr>
            </table>
        </div>
        <div style="background:#fff3cd;padding:15px;border-radius:10px;margin-top:15px;">
            <b>⚠️ Action Required:</b><br>
            Refresh your {service} token before it expires!
        </div>
    </div>
    """

    notify(
        subject      = f"⚠️ {service} Token Expiring in {days_left} Days!",
        telegram_msg = telegram_msg,
        email_html   = email_html
    )

def notify_weekly_report(channel_stats, best_video):
    now = datetime.utcnow().strftime("%Y-%m-%d")
    subs   = int(channel_stats.get("subscribers", 0))
    views  = int(channel_stats.get("total_views", 0))
    videos = channel_stats.get("video_count", 0)

    telegram_msg = (
        f"📊 <b>Weekly Report - {now}</b>\n\n"
        f"👥 Subscribers: {subs:,}\n"
        f"👁️ Total Views: {views:,}\n"
        f"🎬 Total Videos: {videos}\n"
    )

    if best_video:
        telegram_msg += (
            f"\n🏆 <b>Best Video:</b>\n"
            f"📹 {best_video['title'][:50]}\n"
            f"👁️ {best_video['views']:,} views\n"
        )

    bv_title  = best_video["title"]  if best_video else "N/A"
    bv_views  = f"{best_video['views']:,}" if best_video else "0"
    bv_likes  = f"{best_video['likes']:,}" if best_video else "0"

    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="background:#6600cc;padding:20px;border-radius:10px;text-align:center;">
            <h1 style="color:white;margin:0;">📊 Weekly Analytics Report</h1>
            <p style="color:#ddd;margin:5px 0 0 0;">{now}</p>
        </div>

        <div style="display:flex;gap:10px;margin-top:20px;">
            <div style="flex:1;background:#e8f5e9;padding:15px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#00aa44;">{subs:,}</div>
                <div style="color:#666;">👥 Subscribers</div>
            </div>
            <div style="flex:1;background:#e3f2fd;padding:15px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#0066cc;">{views:,}</div>
                <div style="color:#666;">👁️ Total Views</div>
            </div>
            <div style="flex:1;background:#fff3e0;padding:15px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#ff8800;">{videos}</div>
                <div style="color:#666;">🎬 Videos</div>
            </div>
        </div>

        <div style="background:#f9f9f9;padding:20px;border-radius:10px;margin-top:20px;">
            <h3 style="margin:0 0 15px 0;">🏆 Best Performing Video</h3>
            <table style="width:100%;">
                <tr><td><b>Title:</b></td><td>{bv_title}</td></tr>
                <tr><td><b>Views:</b></td><td>{bv_views}</td></tr>
                <tr><td><b>Likes:</b></td><td>{bv_likes}</td></tr>
            </table>
        </div>

        <div style="text-align:center;margin-top:20px;color:#666;font-size:12px;">
            MindBlownFacts Automation Bot • Weekly Report
        </div>
    </div>
    """

    notify(
        subject      = f"📊 MindBlownFacts Weekly Report - {now}",
        telegram_msg = telegram_msg,
        email_html   = email_html
    )

# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing notifications...")
    send_telegram("🤖 MindBlownFacts bot notifications working!")
    send_email(
        subject   = "✅ MindBlownFacts - Email Test",
        body_html = "<h2>Email notifications are working!</h2><p>Your MindBlownFacts bot is ready.</p>"
    )
    print("Done!")