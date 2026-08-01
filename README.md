# Discord Bot

This bot runs as a single Discord process. Configure it with `config.yaml` and a local `.env` file.

## Set it up

1. Install **Python 3.12**, then open a terminal in this folder. Python 3.13
   builds several pinned dependencies from source and can exceed small hosting
   disk quotas.

2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and add your secrets. At minimum, set
   `DISCORD_BOT_TOKEN`. The values in `.env` override the `${NAME}` placeholders
   in `config.yaml`.

5. Open `config.yaml` and set your channel IDs, ticket settings, AI channel, and
   any custom emojis. Use `0` for channel IDs you do not want to use.

6. In the Discord Developer Portal, enable **Message Content Intent** and
   **Server Members Intent** for the bot. Invite it with the `bot` and
   `applications.commands` scopes, granting only the permissions needed by the
   features you enable.

7. Start the bot:

   ```powershell
   python main.py
   ```

## Configuration

`config.yaml` is the source for startup and shared feature configuration:

- `bot` — token placeholder, activity, status, prefix
- `channels` — moderation, appeal, ticket, and automod log channels
- `tickets` — ticket panel, category, questions, and auto-close behaviour
- `ai` — Groq key placeholder, channel, cooldown, and models
- `music` — Spotify and FFmpeg settings
- `emojis` — optional custom emoji overrides

Runtime data such as active tickets, warnings, levels, giveaways, and saved
welcome messages is created in `data/` while the bot runs. It is deliberately
ignored by Git; copy `config.yaml` and `data/` before changing hosts if you want
to preserve it.

## Components V2

Components V2 is implemented natively in the cogs that use rich component
layouts: Help, Invite, Ticket, and Sender. There is no global embed-conversion
bridge. Other cogs use standard Discord embeds and interactive views where those
are a better fit for their existing stateful controls.

Embeds that do not supply a colour default to Discord blurple (`#5865F2`).

## Pterodactyl hosting

Use a Python 3.12 image, set `PY_FILE` to `main.py`, and leave `PY_PACKAGES`
empty. If an earlier installation failed, delete the `.local` and `.cache`
folders in the server File Manager before starting again. The start command is:

```bash
python main.py
```

## Publish to GitHub

Install [Git](https://git-scm.com/downloads) and the
[GitHub CLI](https://cli.github.com/), then authenticate once:

```powershell
gh auth login
```

To publish this folder to `NuzProjects/Discord-Bot`, run:

```powershell
git init
git branch -M main
git add -A
git commit -m "Initial Discord bot"
git remote add origin https://github.com/NuzProjects/Discord-Bot.git
git push -u origin main
```

The target repository must exist and be empty, or you must first pull/merge its
existing history. Never commit `.env` or live credentials.

## Security note

If this project previously contained live Discord, Groq, Spotify, or OAuth
credentials, revoke and regenerate them before running the bot. Do not commit
your `.env` file.
=======
# Discord-Bot
Free and open source Discord Bot featuring Discord ComponentsV2
>>>>>>> origin/main
