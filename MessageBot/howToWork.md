# Discord Message Tracker — Setup Guide

## Files
- `discord_tracker_bot.py` — Python bot + REST API server
- `discord_dashboard.html` — Browser dashboard (open directly, no server needed)

---

## 1. Create your Discord Bot

1. Go to https://discord.com/developers/applications → **New Application**
2. Click **Bot** in the sidebar → **Add Bot**
3. Under **Privileged Gateway Intents**, enable:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
4. Copy your **Bot Token** (keep it secret!)
5. Under **OAuth2 → URL Generator**, select scopes: `bot`
   - Bot permissions: **Read Messages/View Channels**, **Read Message History**
6. Open the generated URL in your browser → invite the bot to your server

---

## 2. Install dependencies

```bash
pip install discord.py flask flask-cors
```

---

## 3. Set your token & run

**Option A — environment variable (recommended):**
```bash
export DISCORD_TOKEN="your-token-here"
python discord_tracker_bot.py
```

**Option B — edit the script directly:**
Open `discord_tracker_bot.py` and replace `YOUR_BOT_TOKEN_HERE` on line ~23.

---

## 4. Open the dashboard

Open `discord_dashboard.html` in any browser.

- When the bot is running, it pulls live data from `http://localhost:5000`
- Without the bot, it displays demo data so you can preview the UI

The dashboard auto-refreshes every 30 seconds.

---

## How it works

| Component | Role |
|-----------|------|
| `discord.py` bot | Listens to every message in every channel, records `(user, guild, channel, timestamp)` in SQLite |
| `Flask` API | Exposes `/api/leaderboard`, `/api/rising`, `/api/daily`, `/api/stats` |
| `discord_dashboard.html` | Fetches from the API and renders leaderboard, rising-stars ranking, and daily activity chart |

### Rising Stars algorithm
Compares message counts in the **last 7 days** vs the **7 days before that** and ranks users by % growth. New users (no previous messages) are flagged as **NEW**.

---

## Notes
- The bot only tracks messages sent **after** it joins. It does not backfill history.
- Data is stored locally in `message_stats.db` (SQLite) — no external service required.
- To backfill history, see the Discord API `GET /channels/{id}/messages` endpoint (requires additional permissions).
