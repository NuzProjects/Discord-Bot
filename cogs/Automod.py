import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
import time
import re
from pathlib import Path
import json
import datetime
from typing import Optional

# ================== CONSTANTS ==================

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = BASE_DIR / "data" / "automod.json"

COLORS = {
    "invite":  discord.Color.from_rgb(255, 165, 0),
    "spam":    discord.Color.from_rgb(220, 53, 69),
    "mention": discord.Color.from_rgb(255, 193, 7),
    "slur":    discord.Color.from_rgb(153, 0, 0),
    "keyword": discord.Color.from_rgb(138, 43, 226),
}

INVITE_RE = re.compile(
    r"(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)[\w-]+",
    re.IGNORECASE,
)

SLUR_PATTERNS = [
    re.compile(r"\bn+\s*[i!1]+\s*[g6]+\s*[g6]+\s*[e3]*\s*r*\b", re.IGNORECASE),
    re.compile(r"\bn+\s*[i!1]+\s*[g6]+\s*[g6]+\s*a+\b",          re.IGNORECASE),
    re.compile(r"\bn+\s*[i!1]+\s*[g6]+\s*[g6]+\b",                re.IGNORECASE),
]

ACTION_LABELS = {
    "delete":  "Delete message",
    "warn":    "Delete + warn in channel",
    "timeout": "Delete + timeout",
    "kick":    "Delete + kick",
    "ban":     "Delete + ban",
}

# ================== CONFIG HELPERS ==================

DEFAULT_CONFIG = {
    "log_channel":        0,
    "spam_count":         5,
    "spam_window":        5,
    "max_role_mentions":  3,
    "timeout_seconds":    600,
    "block_invites":      True,
    "block_slurs":        True,
    "invite_action":      "delete",
    "slur_action":        "timeout",
    "spam_action":        "timeout",
    "mention_action":     "timeout",
    "keyword_filters":    [],
}

CONFIG_KEYS = set(DEFAULT_CONFIG)


def _split_config_store(raw: dict) -> tuple[dict, dict]:
    if not isinstance(raw, dict):
        return {}, {}
    legacy = {k: v for k, v in raw.items() if k in CONFIG_KEYS}
    guilds = {k: v for k, v in raw.items() if k not in CONFIG_KEYS and isinstance(v, dict)}
    return guilds, legacy


def load_config(guild_id: Optional[str] = None) -> dict:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({}, indent=4))
    try:
        raw_cfg = json.loads(CONFIG_FILE.read_text())
    except Exception:
        raw_cfg = {}
    all_cfg, legacy_cfg = _split_config_store(raw_cfg)
    if guild_id is None:
        return all_cfg
    return {**DEFAULT_CONFIG, **legacy_cfg, **all_cfg.get(str(guild_id), {})}


def save_guild_config(guild_id: str, cfg: dict):
    all_cfg = load_config()
    all_cfg[str(guild_id)] = cfg
    CONFIG_FILE.write_text(json.dumps(all_cfg, indent=4))


def get_log_channel_id(bot, guild_id: int) -> int:
    cfg = load_config(str(guild_id))
    ch_id = int(cfg.get("log_channel") or 0)
    if ch_id:
        return ch_id
    # Fallback to global config.yaml
    bot_cfg = getattr(bot, "config", None) or {}
    return int((bot_cfg.get("channels") or {}).get("automod_log") or 0)


# ================== COG ==================

class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        self._msg_times: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    # ================== LOGGING ==================

    async def _log(self, guild: discord.Guild, embed: discord.Embed):
        ch_id = get_log_channel_id(self.bot, guild.id)
        if not ch_id:
            return
        channel = guild.get_channel(ch_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass

    # ================== HELPERS ==================

    async def _apply_action(self, message: discord.Message, action: str, reason: str):
        """Apply a moderation action to a message author."""
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        member = message.author
        if not isinstance(member, discord.Member):
            return

        cfg = load_config(str(message.guild.id))
        timeout_secs = int(cfg.get("timeout_seconds", 600))

        if action == "timeout":
            try:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=timeout_secs)
                await member.timeout(until, reason=reason)
            except (discord.Forbidden, discord.HTTPException):
                pass
        elif action == "kick":
            try:
                await member.kick(reason=reason)
            except (discord.Forbidden, discord.HTTPException):
                pass
        elif action == "ban":
            try:
                await member.ban(reason=reason, delete_message_days=0)
            except (discord.Forbidden, discord.HTTPException):
                pass

    def _is_immune(self, member: discord.Member) -> bool:
        return (member.guild_permissions.administrator or
                member.guild_permissions.manage_messages)

    # ================== LISTENERS ==================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.author, discord.Member):
            return
        if self._is_immune(message.author):
            return

        cfg = load_config(str(message.guild.id))

        if cfg.get("block_invites", True) and await self._check_invite(message, cfg):
            return
        if cfg.get("block_slurs", True) and await self._check_slur(message, cfg):
            return
        if await self._check_keywords(message, cfg):
            return
        if await self._check_role_mentions(message, cfg):
            return
        await self._check_spam(message, cfg)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or not after.guild:
            return
        if not isinstance(after.author, discord.Member):
            return
        if self._is_immune(after.author):
            return
        cfg = load_config(str(after.guild.id))
        if cfg.get("block_invites", True):
            await self._check_invite(after, cfg)
        if cfg.get("block_slurs", True):
            await self._check_slur(after, cfg)
        await self._check_keywords(after, cfg)

    # ================== CHECKS ==================

    async def _check_invite(self, message: discord.Message, cfg: dict) -> bool:
        if not INVITE_RE.search(message.content):
            return False
        action = cfg.get("invite_action", "delete")
        await self._apply_action(message, action, "Posted a Discord invite link")
        embed = discord.Embed(
            title=f"{self.e.link} Invite Link Blocked",
            description=(
                f"> **User:** {message.author.mention} (`{message.author}`)\n"
                f"> **Channel:** {message.channel.mention}\n"
                f"> **Action:** {ACTION_LABELS.get(action, action)}\n"
                f"> **Content:**\n```{message.content[:800]}```"
            ),
            color=COLORS["invite"],
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._log(message.guild, embed)
        try:
            await message.channel.send(
                f"{message.author.mention} {self.e.link} Discord invite links are not allowed.",
                delete_after=5,
            )
        except discord.Forbidden:
            pass
        return True

    async def _check_slur(self, message: discord.Message, cfg: dict) -> bool:
        content_clean = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\uFEFF]", "", message.content)
        if not any(p.search(content_clean) for p in SLUR_PATTERNS):
            return False
        timeout_mins = int(cfg.get("timeout_seconds", 600)) // 60
        action = cfg.get("slur_action", "timeout")
        await self._apply_action(message, action, "Used a racial slur")
        embed = discord.Embed(
            title=f"{self.e.unlock} Racial Slur Detected",
            description=(
                f"> **User:** {message.author.mention} (`{message.author}`)\n"
                f"> **Channel:** {message.channel.mention}\n"
                f"> **Action:** {ACTION_LABELS.get(action, action)}"
            ),
            color=COLORS["slur"],
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._log(message.guild, embed)
        try:
            await message.channel.send(
                f"{message.author.mention} {self.e.fail} Racial slurs are not tolerated.",
                delete_after=6,
            )
        except discord.Forbidden:
            pass
        return True

    async def _check_keywords(self, message: discord.Message, cfg: dict) -> bool:
        """Check against custom keyword filters."""
        filters = cfg.get("keyword_filters", [])
        if not filters:
            return False
        content_lower = message.content.lower()
        for f in filters:
            keyword = f.get("keyword", "").lower()
            action  = f.get("action", "delete")
            if not keyword:
                continue
            # Support wildcard matching: *word* means contains
            if keyword.startswith("*") and keyword.endswith("*"):
                matched = keyword[1:-1] in content_lower
            elif keyword.startswith("*"):
                matched = content_lower.endswith(keyword[1:])
            elif keyword.endswith("*"):
                matched = content_lower.startswith(keyword[:-1])
            else:
                matched = re.search(r"\b" + re.escape(keyword) + r"\b", content_lower) is not None

            if matched:
                await self._apply_action(message, action, f"Keyword filter: {keyword}")
                embed = discord.Embed(
                    title=f"{self.e.shield} Keyword Filter Triggered",
                    description=(
                        f"> **User:** {message.author.mention} (`{message.author}`)\n"
                        f"> **Channel:** {message.channel.mention}\n"
                        f"> **Keyword:** `{keyword}`\n"
                        f"> **Action:** {ACTION_LABELS.get(action, action)}"
                    ),
                    color=COLORS["keyword"],
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                embed.set_footer(text=f"User ID: {message.author.id}")
                await self._log(message.guild, embed)
                return True
        return False

    async def _check_role_mentions(self, message: discord.Message, cfg: dict) -> bool:
        max_mentions = int(cfg.get("max_role_mentions", 3))
        if len(message.role_mentions) < max_mentions:
            return False
        action = cfg.get("mention_action", "timeout")
        await self._apply_action(message, action, "Role mention spam")
        timeout_mins = int(cfg.get("timeout_seconds", 600)) // 60
        embed = discord.Embed(
            title=f"{self.e.ping} Role Mention Spam",
            description=(
                f"> **User:** {message.author.mention} (`{message.author}`)\n"
                f"> **Channel:** {message.channel.mention}\n"
                f"> **Mentions:** {len(message.role_mentions)}\n"
                f"> **Action:** {ACTION_LABELS.get(action, action)}"
            ),
            color=COLORS["mention"],
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._log(message.guild, embed)
        return True

    async def _check_spam(self, message: discord.Message, cfg: dict) -> bool:
        spam_count  = int(cfg.get("spam_count", 5))
        spam_window = int(cfg.get("spam_window", 5))
        guild_id = message.guild.id
        user_id  = message.author.id
        now = time.time()
        timestamps = self._msg_times[guild_id][user_id]
        timestamps.append(now)
        cutoff = now - spam_window
        self._msg_times[guild_id][user_id] = [t for t in timestamps if t > cutoff]
        if len(self._msg_times[guild_id][user_id]) < spam_count:
            return False
        self._msg_times[guild_id][user_id] = []
        action = cfg.get("spam_action", "timeout")
        await self._apply_action(message, action, "Message spam")
        try:
            await message.channel.purge(limit=20, check=lambda m: m.author.id == user_id, bulk=True)
        except (discord.Forbidden, discord.HTTPException):
            pass
        embed = discord.Embed(
            title=f"{self.e.announce} Spam Detected",
            description=(
                f"> **User:** {message.author.mention} (`{message.author}`)\n"
                f"> **Channel:** {message.channel.mention}\n"
                f"> **Action:** {ACTION_LABELS.get(action, action)}"
            ),
            color=COLORS["spam"],
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._log(message.guild, embed)
        try:
            await message.channel.send(
                f"{message.author.mention} {self.e.fail} Please stop spamming.",
                delete_after=6,
            )
        except discord.Forbidden:
            pass
        return True


    # Configuration is read from the local bot configuration and data store.


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
