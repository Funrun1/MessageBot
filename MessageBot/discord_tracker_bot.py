import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# ── ENVIRONMENT ───────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
FLASK_PORT = int(os.getenv("PORT", 5000))

if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN is missing in environment variables.")

# ── DATABASE ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "message_stats.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            timestamp TEXT NOT NULL
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

# ── STATS FUNCTIONS ───────────────────────────────────────────────────────────
def get_leaderboard(guild_id=None, limit=20):
    conn = get_db()
    if guild_id:
        rows = conn.execute(
            "SELECT username, user_id, COUNT(*) as total FROM messages WHERE guild_id=? GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (str(guild_id), limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT username, user_id, COUNT(*) as total FROM messages GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_summary_stats(guild_id=None):
    conn = get_db()
    if guild_id:
        total = conn.execute("SELECT COUNT(*) FROM messages WHERE guild_id=?", (str(guild_id),)).fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages WHERE guild_id=?", (str(guild_id),)).fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM messages WHERE guild_id=? AND DATE(timestamp)=DATE('now', 'utc')", (str(guild_id),)).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages").fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM messages WHERE DATE(timestamp)=DATE('now', 'utc')").fetchone()[0]
    conn.close()
    return {"total_messages": total, "unique_users": users, "today": today}

def get_daily_counts(guild_id=None, days=30):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if guild_id:
        rows = conn.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as count FROM messages WHERE timestamp >= ? AND guild_id=? GROUP BY day ORDER BY day",
            (since, str(guild_id))
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as count FROM messages WHERE timestamp >= ? GROUP BY day ORDER BY day",
            (since,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_trend(user_id, guild_id=None, days=14):
    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if guild_id:
        rows = conn.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as count FROM messages WHERE user_id=? AND timestamp>=? AND guild_id=? GROUP BY day ORDER BY day",
            (str(user_id), since, str(guild_id))
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as count FROM messages WHERE user_id=? AND timestamp>=? GROUP BY day ORDER BY day",
            (str(user_id), since)
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
            "SELECT user_id, username, COUNT(*) as cnt FROM messages WHERE timestamp>=? AND guild_id=? GROUP BY user_id",
            (recent_start, str(guild_id))
        ).fetchall()
        prev = conn.execute(
            "SELECT user_id, COUNT(*) as cnt FROM messages WHERE timestamp>=? AND timestamp<? AND guild_id=? GROUP BY user_id",
            (prev_start, recent_start, str(guild_id))
        ).fetchall()
    else:
        recent = conn.execute(
            "SELECT user_id, username, COUNT(*) as cnt FROM messages WHERE timestamp>=? GROUP BY user_id",
            (recent_start,)
        ).fetchall()
        prev = conn.execute(
            "SELECT user_id, COUNT(*) as cnt FROM messages WHERE timestamp>=? AND timestamp<? GROUP BY user_id",
            (prev_start, recent_start)
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
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)

# ── Discord Bot ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class BotClient(commands.Bot):
    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            print(f"🌍 Synced {len(synced)} slash commands globally!")
        except Exception as e:
            print(f"❌ Failed to sync commands: {e}")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        print(f"📊 Dashboard API: http://localhost:{FLASK_PORT}")
        print(f"📁 Database: {DB_PATH}")

    async def on_message(self, message):
        if message.author.bot:
            return
        record_message(
            user_id=message.author.id,
            username=str(message.author),
            guild_id=message.guild.id if message.guild else "DM",
            channel_id=message.channel.id
        )
        if message.content.startswith("!"):
            await self.process_commands(message)

bot = BotClient(command_prefix="!", intents=intents)

# ── Slash Commands ───────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Show top chatters")
async def leaderboard(interaction: discord.Interaction):
    data = get_leaderboard(guild_id=interaction.guild.id if interaction.guild else None)
    if not data:
        await interaction.response.send_message("No data yet!")
        return
    text = "\n".join([f"{i+1}. {u['username']} - {u['total']}" for i, u in enumerate(data[:10])])
    await interaction.response.send_message(f"📊 Top Chatters:\n{text}")

@bot.tree.command(name="stats", description="Show server stats")
async def stats(interaction: discord.Interaction):
    data = get_summary_stats(guild_id=interaction.guild.id if interaction.guild else None)
    await interaction.response.send_message(
        f"📈 Total Messages: {data['total_messages']}\n"
        f"👥 Unique Users: {data['unique_users']}\n"
        f"🗓️ Today: {data['today']}"
    )

@bot.tree.command(name="rising", description="Show rising chatters")
async def rising(interaction: discord.Interaction):
    data = get_rising_users(guild_id=interaction.guild.id if interaction.guild else None)
    if not data:
        await interaction.response.send_message("Not enough data yet!")
        return
    text = "\n".join([f"{u['username']}: +{u['growth_pct']}%" for u in data[:10]])
    await interaction.response.send_message(f"🚀 Rising Stars:\n{text}")

@bot.tree.command(name="daily", description="Show daily message counts")
async def daily(interaction: discord.Interaction):
    data = get_daily_counts(guild_id=interaction.guild.id if interaction.guild else None)
    if not data:
        await interaction.response.send_message("No data yet!")
        return
    text = "\n".join([f"{r['day']}: {r['count']}" for r in data])
    await interaction.response.send_message(f"🗓️ Daily Messages:\n{text}")

@bot.tree.command(name="user_trend", description="Show a user's message trend")
@app_commands.describe(user="Select a user")
async def user_trend(interaction: discord.Interaction, user: discord.User):
    data = get_user_trend(user_id=user.id, guild_id=interaction.guild.id if interaction.guild else None)
    if not data:
        await interaction.response.send_message(f"No data found for {user}.")
        return
    text = "\n".join([f"{r['day']}: {r['count']}" for r in data])
    await interaction.response.send_message(f"📈 Message Trend for {user}:\n{text}")

@bot.tree.command(name="backfill", description="Backfill message history from all channels (admin only)")
async def backfill(interaction: discord.Interaction):
    # Only allow server admins to run this
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need to be an admin to run this.", ephemeral=True)
        return

    await interaction.response.send_message("⏳ Starting backfill... this may take a while!", ephemeral=True)

    guild = interaction.guild
    total = 0
    skipped = 0

    for channel in guild.text_channels:
        # Check if bot has permission to read this channel
        if not channel.permissions_for(guild.me).read_message_history:
            skipped += 1
            continue
        try:
            async for message in channel.history(limit=1000, oldest_first=True):
                if message.author.bot:
                    continue
                record_message(
                    user_id=message.author.id,
                    username=str(message.author),
                    guild_id=str(guild.id),
                    channel_id=str(channel.id)
                )
                total += 1
        except discord.Forbidden:
            skipped += 1
        except Exception as e:
            print(f"❌ Error backfilling #{channel.name}: {e}")

    await interaction.followup.send(
        f"✅ Backfill complete!\n"
        f"📥 Imported: {total} messages\n"
        f"⏭️ Skipped channels (no access): {skipped}",
        ephemeral=True
    )

@bot.command(name="backfill")
@commands.has_permissions(administrator=True)
async def backfill_prefix(ctx):
    msg = await ctx.send("⏳ Starting backfill... this may take a while!")
    guild = ctx.guild
    total = 0
    skipped = 0

    for channel in guild.text_channels:
        if not channel.permissions_for(guild.me).read_message_history:
            skipped += 1
            continue
        try:
            async for message in channel.history(limit=1000, oldest_first=True):
                if message.author.bot:
                    continue
                record_message(
                    user_id=message.author.id,
                    username=str(message.author),
                    guild_id=str(guild.id),
                    channel_id=str(channel.id)
                )
                total += 1
        except discord.Forbidden:
            skipped += 1
        except Exception as e:
            print(f"❌ Error backfilling #{channel.name}: {e}")

    await msg.edit(content=(
        f"✅ Backfill complete!\n"
        f"📥 Imported: {total} messages\n"
        f"⏭️ Skipped channels (no access): {skipped}"
    ))

# ── Run main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
