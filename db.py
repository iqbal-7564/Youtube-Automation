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
    conn.commit()
    return conn

def already_posted(conn, url_hash):
    return conn.execute(
        "SELECT 1 FROM posted WHERE url_hash=?", (url_hash,)
    ).fetchone() is not None

def title_already_posted(conn, title, threshold=0.85):
    rows = conn.execute("""
        SELECT title FROM posted
        WHERE posted_at >= datetime('now', '-7 days')
    """).fetchall()
    if not rows:
        return False
    posted_titles = [r[0] for r in rows]
    new_emb  = model.encode([title])
    old_embs = model.encode(posted_titles)
    sims = cosine_similarity(new_emb, old_embs)[0]
    return float(sims.max()) >= threshold

def mark_posted(conn, url_hash, title, platform):
    conn.execute(
        "INSERT OR IGNORE INTO posted (url_hash, platform, title) VALUES (?,?,?)",
        (url_hash, platform, title)
    )
    conn.commit()

def get_today_count(conn, platform):
    return conn.execute("""
        SELECT COUNT(*) FROM posted
        WHERE platform=? AND DATE(posted_at)=DATE('now')
    """, (platform,)).fetchone()[0]