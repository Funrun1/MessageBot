# MessageBot
A Discord message tracking bot that records message counts per user and provides a simple dashboard API.

## Setup

1. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Create a `.env` file in the repo root (next to `discord_tracker_bot.py`) with your bot token.

   You can start by copying the provided example:

```bash
cp .env.example .env
```

   And then edit `.env` to set your token:

```env
# Either of these will work:
DISCORD_TOKEN=your_token_here
# or
DISCORD_BOT_TOKEN=your_token_here
```

3. Run the bot:

```bash
python discord_tracker_bot.py
```

## Features

- Tracks message counts per user across all channels/guilds
- Serves a simple dashboard API at `http://localhost:5000`
- Supports basic Discord chat commands: `!leaderboard`, `!stats`, `!rising`

