import sqlite3
from sklearn.metrics.pairwise import cosine_similarity
from deduplicator import model

def init_db():
    conn = sqlite3.connect("state.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posted (
            url_hash  TEXT,
            platform  TEXT,
            title     TEXT,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (url_hash, platform)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_posted_at
        ON posted(posted_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_platform
        ON posted(platform)
    """)
    conn.execute("""
        DELETE FROM posted
        WHERE posted_at < datetime('now', '-30 days')
    """)
    conn.commit()
    return conn

def already_posted(conn, url_hash):
    return conn.execute(
        "SELECT 1 FROM posted WHERE url_hash=?", (url_hash,)
    ).fetchone() is not None

def title_already_posted(conn, title, threshold=0.78):
    rows = conn.execute("""
        SELECT title FROM posted
        WHERE posted_at >= datetime('now', '-3 days')
    """).fetchall()
    if not rows:
        return False
    posted_titles = [r[0] for r in rows]
    all_texts     = [title] + posted_titles
    all_embs      = model.encode(all_texts, show_progress_bar=False)
    new_emb       = all_embs[:1]
    old_embs      = all_embs[1:]
    sims          = cosine_similarity(new_emb, old_embs)[0]
    return float(sims.max()) >= threshold

def mark_posted(conn, url_hash, title, platform):
    conn.execute(
        "INSERT OR IGNORE INTO posted (url_hash, platform, title) VALUES (?,?,?)",
        (url_hash, platform, title)
    )
    conn.commit()

def get_today_count(conn, platform):
    """Count posts made today in PKT timezone (UTC+5)"""
    from datetime import datetime, timezone, timedelta
    PKT     = timezone(timedelta(hours=5))
    now_pkt = datetime.now(PKT)
    # Today start in PKT converted to UTC for SQLite
    today_start_pkt = now_pkt.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_pkt.astimezone(timezone.utc)
    today_str       = today_start_utc.strftime("%Y-%m-%d %H:%M:%S")

    return conn.execute("""
        SELECT COUNT(*) FROM posted
        WHERE platform=?
        AND posted_at >= ?
    """, (platform, today_str)).fetchone()[0]