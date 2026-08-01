# Discord Bot

A modular, all-in-one Discord community bot built with [discord.py](https://discordpy.readthedocs.io/). It provides moderation, tickets, automation, giveaways, leveling, AI assistance, server utilities, and more through Discord slash commands.


## Features

- **Moderation** — warnings, kicks, bans, timeouts, message purging, slowmode, channel locks, reports, and moderation logs.
- **Tickets** — configurable ticket panels, custom questions, staff access controls, transcripts, blacklisting, and auto-close.
- **Community tools** — welcome messages, AFK status, invite tracking, sticky messages, counting channels, giveaways, boost notifications, translations, and ghost-ping detection.
- **Leveling** — XP, level cards, server leaderboards, and administrator XP controls.
- **Server management** — role and nickname tools, server/member profile lookups, backup and restore, plus emoji and sticker utilities.
- **Automation and logging** — AutoMod configuration and per-event audit logging for joins, leaves, message changes, roles, and profile updates.
- **Optional integrations** — Groq-powered AI chat with image support and on-demand Google Translate lookups.
- **Built-in operations** — command directory, status, uptime, bot diagnostics, logs, and cog load/reload controls.

## Requirements

- Python 3.10 or newer is recommended
- A Discord application and bot token from the [Discord Developer Portal](https://discord.com/developers/applications)

Optional services are only needed for their related features:

- A Groq API key for `/ask`, `/feed`, and AI moderation controls

## Installation

1. Clone the project and enter its folder.

   ```bash
   git clone https://github.com/NuzProjects/Discord-Bot.git
   cd Discord-Bot
   ```

2. Create and activate a virtual environment.

   ```bash
   python -m venv .venv
   ```

   **Windows (PowerShell)**

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS / Linux**

   ```bash
   source .venv/bin/activate
   ```

3. Install the dependencies.

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file from the example and add your bot token.

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   At a minimum, set:

   ```dotenv
   DISCORD_BOT_TOKEN=your_bot_token_here
   ```

5. Review `config.yaml` and tailor the bot status, ticket panel, logging channels, and AI settings to your server.

6. Start the bot.

   ```bash
   python main.py
   ```

The bot discovers and loads the modules in `cogs/` at startup, then synchronizes its application commands.

## Discord application setup

In the Discord Developer Portal, enable the privileged gateway intents the bot uses:

- **Message Content Intent**
- **Server Members Intent**
- **Presence Intent**

When inviting the bot, grant only the permissions needed for the modules you intend to use. Moderation, ticket management, channel locks, role management, emoji/sticker copying, and backups can require powerful permissions; test them in a non-production server first.

## Configuration

`config.yaml` provides sensible defaults and supports environment-variable references such as `${DISCORD_BOT_TOKEN}` and `${GROQ_API_KEY}`.

| Area | What to configure |
| --- | --- |
| `bot` | Token, status, activity text, and command prefix |
| `appearance` | Default embed colour |
| `logging` | Log level, file, and formatting |
| `channels` | Moderation, appeal, ticket, and AutoMod log channels |
| `tickets` | Panel channel, category, buttons, questions, transcripts, and auto-close behavior |
| `ai` | Groq API key, AI channel, cooldown, and model |

Channel IDs are set to `0` by default. Replace them with real Discord channel IDs for features that post to a configured channel.

## Command overview

Use `/help` in Discord to browse the complete command directory. Common commands include:

| Category | Commands |
| --- | --- |
| Moderation | `/warn`, `/warnlist`, `/kick`, `/ban`, `/temp-ban`, `/mute`, `/purge`, `/slowmode`, `/lock`, `/report` |
| Tickets | `/close`, `/autoclose`, `/add`, `/remove`, `/ticket-blacklist` |
| Community | `/afk`, `/unafk`, `/gstart`, `/greroll`, `/gend`, `/invites`, `/sticky set`, `/csetup`, reply with `!t <language>` |
| Utility | `/ping`, `/serverinfo`, `/userinfo`, `/avatar`, `/banner`, `/role add`, `/massrole type` |
| Leveling | `/level`, `/lblevel`, `/setxp`, `/resetxp` |
| AI | `/ask`, `/feed`, `/blacklist` |
| Administration | `/backup`, `/import-backup`, `/del-backup`, `/logger set`, `/status`, `/sync`, `/reload` |

Some commands are restricted to members with administrator permissions or to staff roles configured by the relevant module.

## Data and backups

Most module data is stored locally as JSON files under `data/` and configuration files under `config/`; these folders are created as features run. Back up these folders before moving or redeploying the bot.

The repository also includes an asynchronous MongoDB helper under `database/`, but the active feature modules currently persist their own JSON data.

## Project structure

```text
.
├── cogs/          # Feature modules and slash commands
├── config.yaml    # Bot-wide configuration
├── database/      # Optional MongoDB helper
├── tests/         # Test suite
├── utils/         # Shared helpers, embeds, permissions, logging
├── .env.example   # Environment variable template
├── requirements.txt
└── main.py         # Application entry point
```

## Development

Run the test suite with:

```bash
pytest
```

Keep tokens, API keys, generated logs, and server data out of version control. The provided `.gitignore` is intended to help with this, but always check staged changes before committing.

## License

This project is distributed under the [Apache License 2.0](LICENSE).
