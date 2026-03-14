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

import discord
from flask import Flask, jsonify
from flask_cors import CORS

# ── Config ──────────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "MTQ4MTg2MzI0MDQ0NjI1MTE2OQ.G6FzcU.h7cCo0gVnlse_01-xcA09ZBt_wJZYjzz2NvZoQ")
DB_PATH = "message_stats.db"
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
    where = f"WHERE guild_id = '{guild_id}'" if guild_id else ""
    rows = conn.execute(f"""
        SELECT username, user_id, COUNT(*) as total
        FROM messages {where}
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT {limit}
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_daily_counts(guild_id=None, days=30):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    where_guild = f"AND guild_id = '{guild_id}'" if guild_id else ""
    rows = conn.execute(f"""
        SELECT DATE(timestamp) as day, COUNT(*) as count
        FROM messages
        WHERE timestamp >= ? {where_guild}
        GROUP BY day
        ORDER BY day
    """, (since,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_trend(user_id, guild_id=None, days=14):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    where_guild = f"AND guild_id = '{guild_id}'" if guild_id else ""
    rows = conn.execute(f"""
        SELECT DATE(timestamp) as day, COUNT(*) as count
        FROM messages
        WHERE user_id = ? AND timestamp >= ? {where_guild}
        GROUP BY day
        ORDER BY day
    """, (str(user_id), since)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_rising_users(guild_id=None, days_recent=7, days_compare=7):
    conn = get_db()
    now = datetime.now(timezone.utc)
    recent_start = (now - timedelta(days=days_recent)).isoformat()
    prev_start   = (now - timedelta(days=days_recent + days_compare)).isoformat()
    where = f"AND guild_id = '{guild_id}'" if guild_id else ""

    recent = conn.execute(f"""
        SELECT user_id, username, COUNT(*) as cnt
        FROM messages
        WHERE timestamp >= ? {where}
        GROUP BY user_id
    """, (recent_start,)).fetchall()

    prev = conn.execute(f"""
        SELECT user_id, COUNT(*) as cnt
        FROM messages
        WHERE timestamp >= ? AND timestamp < ? {where}
        GROUP BY user_id
    """, (prev_start, recent_start)).fetchall()
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
    where = f"WHERE guild_id = '{guild_id}'" if guild_id else ""
    total = conn.execute(f"SELECT COUNT(*) FROM messages {where}").fetchone()[0]
    users = conn.execute(f"SELECT COUNT(DISTINCT user_id) FROM messages {where}").fetchone()[0]
    today = conn.execute(f"""
        SELECT COUNT(*) FROM messages
        {'WHERE' if not guild_id else 'WHERE guild_id = ? AND'} DATE(timestamp) = DATE('now')
    """, (guild_id,) if guild_id else ()).fetchone()[0]
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
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n⚠️  No bot token set! Set DISCORD_TOKEN env var or replace in code.")
        while True:
            time.sleep(1)
    else:
        bot.run(TOKEN)
