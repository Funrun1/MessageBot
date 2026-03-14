"""
Discord Message Tracker Bot
============================
Tracks messages per user across all channels, stores stats in a local SQLite DB,
and serves a live dashboard API at http://localhost:5000
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

# Support optional python-dotenv dependency; the bot works without it.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(dotenv_path=".env", override=False):
        """Minimal .env loader (fallback when python-dotenv is not installed)."""
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if override or key not in os.environ:
                        os.environ[key] = val
            return True
        except FileNotFoundError:
            return False

import discord
from flask import Flask, jsonify
from flask_cors import CORS

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
loaded_env = load_dotenv(dotenv_path=DOTENV_PATH)
print("dotenv:", DOTENV_PATH, "exists?", os.path.exists(DOTENV_PATH), "loaded?", loaded_env)

TOKEN = (os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or "").strip()
if TOKEN == "":
    TOKEN = None

print("Loaded token:", "YES" if TOKEN else "NO")
DB_PATH = os.path.join(BASE_DIR, "message_stats.db")
FLASK_PORT = 5000

# ── Database setup ───────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            username    TEXT NOT NULL,
            guild_id    TEXT NOT NULL,
            channel_id  TEXT NOT NULL,
            timestamp   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user ON messages(user_id);
        CREATE INDEX IF NOT EXISTS idx_time ON messages(timestamp);
    """)
    conn.commit()
    conn.close()

def record_message(user_id, username, guild_id, channel_id):
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (user_id, username, guild_id, channel_id, timestamp) VALUES (?,?,?,?,?)",
        (str(user_id), username, str(guild_id), str(channel_id), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

# ── Stats queries ────────────────────────────────────────────────────────────
def get_leaderboard(guild_id=None, limit=20):
    conn = get_db()
    if guild_id:
        rows = conn.execute(
            """
            SELECT username, user_id, COUNT(*) as total
            FROM messages
            WHERE guild_id = ?
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (str(guild_id), int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT username, user_id, COUNT(*) as total
            FROM messages
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_daily_counts(guild_id=None, days=30):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if guild_id:
        rows = conn.execute(
            """
            SELECT DATE(timestamp) as day, COUNT(*) as count
            FROM messages
            WHERE timestamp >= ? AND guild_id = ?
            GROUP BY day
            ORDER BY day
            """,
            (since, str(guild_id)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DATE(timestamp) as day, COUNT(*) as count
            FROM messages
            WHERE timestamp >= ?
            GROUP BY day
            ORDER BY day
            """,
            (since,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_trend(user_id, guild_id=None, days=14):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if guild_id:
        rows = conn.execute(
            """
            SELECT DATE(timestamp) as day, COUNT(*) as count
            FROM messages
            WHERE user_id = ? AND timestamp >= ? AND guild_id = ?
            GROUP BY day
            ORDER BY day
            """,
            (str(user_id), since, str(guild_id)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DATE(timestamp) as day, COUNT(*) as count
            FROM messages
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY day
            ORDER BY day
            """,
            (str(user_id), since),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_rising_users(guild_id=None, days_recent=7, days_compare=7):
    conn = get_db()
    now = datetime.now(timezone.utc)
    recent_start = (now - timedelta(days=days_recent)).isoformat()
    prev_start = (now - timedelta(days=days_recent + days_compare)).isoformat()

    if guild_id:
        recent = conn.execute(
            """
            SELECT user_id, username, COUNT(*) as cnt
            FROM messages
            WHERE timestamp >= ? AND guild_id = ?
            GROUP BY user_id
            """,
            (recent_start, str(guild_id)),
        ).fetchall()

        prev = conn.execute(
            """
            SELECT user_id, COUNT(*) as cnt
            FROM messages
            WHERE timestamp >= ? AND timestamp < ? AND guild_id = ?
            GROUP BY user_id
            """,
            (prev_start, recent_start, str(guild_id)),
        ).fetchall()
    else:
        recent = conn.execute(
            """
            SELECT user_id, username, COUNT(*) as cnt
            FROM messages
            WHERE timestamp >= ?
            GROUP BY user_id
            """,
            (recent_start,),
        ).fetchall()

        prev = conn.execute(
            """
            SELECT user_id, COUNT(*) as cnt
            FROM messages
            WHERE timestamp >= ? AND timestamp < ?
            GROUP BY user_id
            """,
            (prev_start, recent_start),
        ).fetchall()

    conn.close()

    prev_map = {r["user_id"]: r["cnt"] for r in prev}
    results = []
    for r in recent:
        uid = r["user_id"]
        old = prev_map.get(uid, 0)
        new = r["cnt"]
        pct = ((new - old) / old * 100) if old else (100.0 if new > 0 else 0.0)
        results.append({
            "user_id": uid,
            "username": r["username"],
            "recent": new,
            "previous": old,
            "growth_pct": round(pct, 1)
        })
    results.sort(key=lambda x: x["growth_pct"], reverse=True)
    return results[:15]

def get_summary_stats(guild_id=None):
    conn = get_db()
    if guild_id:
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchone()[0]
        users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM messages WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchone()[0]
        today = conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE guild_id = ? AND DATE(timestamp) = DATE('now')
            """,
            (str(guild_id),),
        ).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE DATE(timestamp) = DATE('now')",
        ).fetchone()[0]
    conn.close()
    return {"total_messages": total, "unique_users": users, "today": today}

# ── Flask API ────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return "✅ Discord Message Tracker is running! Visit /api/leaderboard"

@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify(get_leaderboard())

@app.route("/api/daily")
def api_daily():
    return jsonify(get_daily_counts())

@app.route("/api/rising")
def api_rising():
    return jsonify(get_rising_users())

@app.route("/api/stats")
def api_stats():
    return jsonify(get_summary_stats())

@app.route("/api/user/<user_id>/trend")
def api_user_trend(user_id):
    return jsonify(get_user_trend(user_id))

def run_flask():
    app.run(port=FLASK_PORT, debug=False, use_reloader=False)

# ── Discord Bot ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"📊 Dashboard: http://localhost:{FLASK_PORT}")
    print(f"📁 Database:  {DB_PATH}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Record message in DB
    record_message(
        user_id=message.author.id,
        username=str(message.author),
        guild_id=message.guild.id if message.guild else "DM",
        channel_id=message.channel.id
    )

    # Discord commands
    if message.content.lower() == "!leaderboard":
        leaderboard = get_leaderboard(guild_id=message.guild.id if message.guild else None)
        text = "\n".join([f"{i+1}. {u['username']} - {u['total']}" for i, u in enumerate(leaderboard[:10])])
        await message.channel.send(f"📊 Top Chatters:\n{text}")

    elif message.content.lower() == "!stats":
        stats = get_summary_stats(guild_id=message.guild.id if message.guild else None)
        await message.channel.send(f"📈 Total Messages: {stats['total_messages']}\n"
                                   f"👥 Unique Users: {stats['unique_users']}\n"
                                   f"🗓️ Today: {stats['today']}")

    elif message.content.lower() == "!rising":
        rising = get_rising_users(guild_id=message.guild.id if message.guild else None)
        text = "\n".join([f"{u['username']}: +{u['growth_pct']}%" for u in rising[:10]])
        await message.channel.send(f"🚀 Rising Stars:\n{text}")

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("🗄️  Database initialized.")

    # Start Flask in a background thread
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"🌐 Dashboard API started on port {FLASK_PORT}")

    # Run the Discord bot
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n⚠️  No bot token set! Set the DISCORD_TOKEN environment variable (or add it to .env) before running.")
        while True:
            time.sleep(1)
    else:
        bot.run(TOKEN)
