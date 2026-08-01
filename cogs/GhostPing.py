"""
cogs/GhostPing.py
─────────────────────────────────────────────────────────────────
Ghost Ping detector.

When someone mentions a user/role and then deletes the message within
GRACE_WINDOW seconds, the bot calls them out in the same channel using
a Components v2 (raw HTTP, flags=32768) message with the server's
custom emojis.
"""

from __future__ import annotations

import asyncio
import logging
import time

import discord
import discord.http as _dhttp
from discord.ext import commands

from utils.emojis import Emojis

_log = logging.getLogger("bot.ghostping")

# ── Tunable constants ─────────────────────────────────────────────────────────
GRACE_WINDOW   = 30     # seconds — deletions older than this are ignored
MAX_CACHE_AGE  = 120    # seconds to keep messages in cache before pruning
MAX_CACHE_SIZE = 2000   # hard cap on cached messages


# ── Raw CV2 sender ────────────────────────────────────────────────────────────

async def _send_cv2(http_client, channel_id: int, components: list) -> None:
    """POST a Components v2 message (flag 32768) directly via the REST API."""
    route = _dhttp.Route(
        "POST", "/channels/{channel_id}/messages", channel_id=channel_id
    )
    await http_client.request(route, json={"components": components, "flags": 32768})


# ── CV2 payload builder ───────────────────────────────────────────────────────

def _build_payload(
    author:  discord.Member,
    mentions: list[discord.Member],
    roles:    list[discord.Role],
    channel:  discord.TextChannel,
    content:  str,
    e:        Emojis,
) -> list[dict]:
    """
    Build a Components v2 container (type 17) that calls out the ghost ping.
    Uses the custom ping + report emojis from the server's emoji registry.
    """
    # Human-readable targets (keep mentions as plain text so they still ping)
    user_parts = [m.mention for m in mentions[:10]]
    role_parts = [r.mention for r in roles[:5]]
    targets_str = ", ".join(user_parts + role_parts) or "someone"

    # Preview the deleted message content
    preview = content.strip()
    if preview:
        preview = (preview[:160] + "…") if len(preview) > 160 else preview
        preview_block = f'\n> *"{discord.utils.escape_markdown(preview)}"*'
    else:
        preview_block = ""

    body = (
        f"## {e.ping} Ghost Ping Detected\n"
        f"{e.report} **{author.display_name}** (`{author}`) "
        f"pinged {targets_str} in {channel.mention} "
        f"and deleted the message.{preview_block}\n"
        f"-# Message deleted within {GRACE_WINDOW}s of being sent."
    )

    return [
        {
            "type": 17,             # Container
            "accent_color": 0xf59e0b,   # amber
            "spoiler": False,
            "components": [
                {
                    "type": 10,     # TextDisplay
                    "content": body
                }
            ]
        }
    ]


# ── Cog ───────────────────────────────────────────────────────────────────────

class GhostPing(commands.Cog):
    """Detects ghost pings and calls them out with a styled CV2 message."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot  = bot
        self.e    = Emojis(bot)
        # message_id → {author, sent_at, channel, mentions, role_mentions, content}
        self._cache: dict[int, dict] = {}
        self._prune_task = bot.loop.create_task(self._prune_loop())

    def cog_unload(self) -> None:
        self._prune_task.cancel()

    # ── Background pruner ─────────────────────────────────────────────────────

    async def _prune_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(30)
            now   = time.monotonic()
            stale = [mid for mid, d in self._cache.items()
                     if now - d["sent_at"] > MAX_CACHE_AGE]
            for mid in stale:
                self._cache.pop(mid, None)
            # Hard cap: evict oldest entries
            if len(self._cache) > MAX_CACHE_SIZE:
                for mid in list(self._cache)[: len(self._cache) - MAX_CACHE_SIZE]:
                    self._cache.pop(mid, None)

    # ── Listeners ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return
        if not (message.mentions or message.role_mentions):
            return

        self._cache[message.id] = {
            "author":        message.author,
            "sent_at":       time.monotonic(),
            "channel":       message.channel,
            "mentions":      list(message.mentions),
            "role_mentions": list(message.role_mentions),
            "content":       message.content or "",
        }

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        data = self._cache.pop(message.id, None)
        if not data:
            return

        # Only act within the grace window
        if time.monotonic() - data["sent_at"] > GRACE_WINDOW:
            return

        author:   discord.Member       = data["author"]
        channel:  discord.TextChannel  = data["channel"]
        mentions: list[discord.Member] = [m for m in data["mentions"] if m.id != author.id and not m.bot]
        roles:    list[discord.Role]   = data["role_mentions"]
        content:  str                  = data["content"]

        # Nothing left after filtering self / bots? Skip.
        if not mentions and not roles:
            return

        _log.info(
            "[GhostPing] %s ghost-pinged %s role(s)=%s in #%s",
            author,
            [str(m) for m in mentions],
            [r.name for r in roles],
            channel.name,
        )

        try:
            payload = _build_payload(author, mentions, roles, channel, content, self.e)
            await _send_cv2(self.bot.http, channel.id, payload)
        except discord.Forbidden:
            _log.warning("[GhostPing] Missing send permission in #%s.", channel.name)
        except Exception as exc:
            _log.error("[GhostPing] Failed to send ghost-ping alert: %s", exc, exc_info=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GhostPing(bot))
