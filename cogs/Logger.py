"""
Logger Cog — logs events to configurable per-guild channels.

Events logged:
  - Avatar / username / display-name changes
  - Server nickname changes
  - Role add / remove  (debounced, with audit-log actor + reason)
  - Message edit / delete  (deleted images are re-uploaded)
  - Member join / leave
  - Member kick (via audit log, fires alongside on_member_remove)
  - Member ban / unban   (native events)
  - Member timeout (via on_member_update, checks timed_out_until)
"""

import asyncio
import io
import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

BASE_DIR    = Path(__file__).resolve().parents[1]
CONFIG_FILE = BASE_DIR / "data" / "logger.json"

EMBED_COLOR   = discord.Color.from_rgb(0, 0, 0)
SUCCESS_COLOR = discord.Color.from_rgb(40, 167, 69)
ERROR_COLOR   = discord.Color.from_rgb(220, 53, 69)
WARN_COLOR    = discord.Color.from_rgb(255, 165, 0)

LOG_TYPES = [
    "default_log",
    "avatar_log",
    "username_log",
    "nickname_log",
    "message_edit_log",
    "message_delete_log",
    "join_leave_log",
    "role_log",
]
LOG_TYPE_KEYS = set(LOG_TYPES)

EMOJI_TRASH  = "<:trash:1494796123003424879>"
EMOJI_EDIT   = "<:edit:1503908815416852601>"
EMOJI_ADD    = "<:add:1496975643051688017>"
EMOJI_REMOVE = "<:remove:1496975641348931776>"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}

_NO_MENTIONS = discord.AllowedMentions.none()


def _quote_content(content: str | None, limit: int = 1000) -> str:
    text = (content or "*empty*")[:limit]
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines()) or "> *empty*"


# ── Config helpers ─────────────────────────────────────────────────────────────

def _split_config_store(raw: dict) -> tuple[dict, dict]:
    if not isinstance(raw, dict):
        return {}, {}
    legacy = {k: v for k, v in raw.items() if k in LOG_TYPE_KEYS}
    guilds = {k: v for k, v in raw.items() if k not in LOG_TYPE_KEYS and isinstance(v, dict)}
    return guilds, legacy


def load_config() -> dict:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({}, indent=4))
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}
    guilds, legacy = _split_config_store(raw)
    return {**legacy, **guilds}


def save_config(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data, indent=4))


def get_guild_config(data: dict, guild_id: int) -> dict:
    legacy    = {k: v for k, v in data.items() if k in LOG_TYPE_KEYS}
    guild_cfg = data.get(str(guild_id), {})
    if not isinstance(guild_cfg, dict):
        guild_cfg = {}
    return {**legacy, **guild_cfg}


# ── Cog ───────────────────────────────────────────────────────────────────────

class Logger(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # role debounce: (guild_id, user_id) → TimerHandle
        self._role_debounce: dict[tuple[int, int], asyncio.TimerHandle] = {}
        # role pending: (guild_id, user_id) → {added, removed, member}
        self._role_pending:  dict[tuple[int, int], dict] = {}

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator

    def _get_channel(self, guild_id: int, log_type: str) -> Optional[discord.TextChannel]:
        cfg       = load_config()
        guild_cfg = get_guild_config(cfg, guild_id)
        ch_id     = guild_cfg.get(log_type) or guild_cfg.get("default_log")
        if not ch_id:
            return None
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        return guild.get_channel(int(ch_id))

    async def _send_log(
        self,
        guild_id: int,
        log_type: str,
        embed: discord.Embed,
        *,
        files: list[discord.File] | None = None,
    ) -> None:
        channel = self._get_channel(guild_id, log_type)
        if not channel:
            return
        try:
            await channel.send(
                embed=embed,
                files=files or [],
                allowed_mentions=_NO_MENTIONS,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _get_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        *,
        max_age_seconds: int = 8,
        limit: int = 6,
    ) -> Optional[discord.AuditLogEntry]:
        """Return the most recent audit log entry matching action + target within max_age_seconds."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
            async for entry in guild.audit_logs(limit=limit, action=action):
                if entry.created_at < cutoff:
                    break
                if entry.target and getattr(entry.target, "id", None) == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    # ── Role-log debounce flush ───────────────────────────────────────────────

    async def _flush_role_log(self, key: tuple[int, int]) -> None:
        pending = self._role_pending.pop(key, None)
        self._role_debounce.pop(key, None)
        if not pending:
            return

        guild_id, user_id = key
        member: discord.Member = pending["member"]
        guild  = member.guild

        added:   list[discord.Role] = list({r.id: r for r in pending["added"]}.values())
        removed: list[discord.Role] = list({r.id: r for r in pending["removed"]}.values())

        # One audit-log lookup covers both add and remove since they share the action type
        await asyncio.sleep(0.2)  # small extra wait after the debounce period
        entry = await self._get_audit_entry(
            guild, discord.AuditLogAction.member_role_update, user_id
        )
        actor  = entry.user   if entry else None
        reason = entry.reason if entry else None

        def build_embed(title: str, roles: list[discord.Role], color: discord.Color) -> discord.Embed:
            roles_str = ", ".join(r.mention for r in roles)
            actor_str = f"> **By:** {actor.mention} (`{actor.id}`)" if actor else "> **By:** Automated"
            reason_str = f"\n> **Reason:** {reason}" if reason else ""
            embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.description = (
                f"> **User:** {member.mention} (`{member.id}`)\n"
                f"{actor_str}{reason_str}\n"
                f"> **Role(s):** {roles_str}"
            )
            embed.set_footer(text=f"User ID: {user_id}")
            return embed

        if added:
            await self._send_log(guild_id, "role_log", build_embed(f"{EMOJI_ADD} Role Added", added, SUCCESS_COLOR))
        if removed:
            await self._send_log(guild_id, "role_log", build_embed(f"{EMOJI_REMOVE} Role Removed", removed, ERROR_COLOR))

    # ── Listeners ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        for guild in self.bot.guilds:
            if not guild.get_member(after.id):
                continue

            if before.display_avatar.url != after.display_avatar.url:
                embed = discord.Embed(
                    title="🖼️ Avatar Changed",
                    color=EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.title = f"{EMOJI_EDIT} Avatar Changed"
                embed.description = f"> **User:** {after.mention} (`{after.id}`)"
                embed.set_image(url=after.display_avatar.url)
                embed.set_footer(text="Avatar updated")
                await self._send_log(guild.id, "avatar_log", embed)

            if before.name != after.name:
                embed = discord.Embed(
                    title=f"{EMOJI_EDIT} Username Changed",
                    color=EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.description = (
                    f"> **User:** {after.mention} (`{after.id}`)\n"
                    f"> **Before:** `{before.name}`\n"
                    f"> **After:** `{after.name}`"
                )
                embed.set_footer(text="Username updated")
                await self._send_log(guild.id, "username_log", embed)

            b_display = getattr(before, "global_name", None) or before.name
            a_display = getattr(after,  "global_name", None) or after.name
            if b_display != a_display and before.name == after.name:
                embed = discord.Embed(
                    title=f"{EMOJI_EDIT} Display Name Changed",
                    color=EMBED_COLOR,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_author(name=str(after), icon_url=after.display_avatar.url)
                embed.description = (
                    f"> **User:** {after.mention} (`{after.id}`)\n"
                    f"> **Before:** `{b_display}`\n"
                    f"> **After:** `{a_display}`"
                )
                embed.set_footer(text="Display name updated")
                await self._send_log(guild.id, "username_log", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        # ── Nickname ──
        b_timeout = getattr(before, "timed_out_until", None)
        a_timeout = getattr(after, "timed_out_until", None)

        if before.nick != after.nick:
            embed = discord.Embed(
                title=f"{EMOJI_EDIT} Nickname Changed",
                color=EMBED_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.description = (
                f"> **User:** {after.mention} (`{after.id}`)\n"
                f"> **Before:** `{before.nick or 'None'}`\n"
                f"> **After:** `{after.nick or 'None'}`"
            )
            embed.set_footer(text="Nickname updated")
            await self._send_log(after.guild.id, "nickname_log", embed)

        if b_timeout and not a_timeout:
            # Timeout removed early
            await asyncio.sleep(0.8)
            entry = await self._get_audit_entry(
                after.guild, discord.AuditLogAction.member_update, after.id
            )
            actor = entry.user if entry else None
            actor_str = f"> **By:** {actor.mention} (`{actor.id}`)" if actor else "> **By:** Unknown"
            embed = discord.Embed(
                title="🔊 Timeout Removed",
                color=SUCCESS_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.description = (
                f"> **User:** {after.mention} (`{after.id}`)\n"
                f"{actor_str}"
            )
            embed.set_footer(text=f"User ID: {after.id}")
            await self._send_log(after.guild.id, "moderation_log", embed)

        elif a_timeout and a_timeout != b_timeout:
            await asyncio.sleep(0.8)
            entry = await self._get_audit_entry(
                after.guild, discord.AuditLogAction.member_update, after.id
            )
            actor = entry.user if entry else None
            actor_str = f"> **By:** {actor.mention} (`{actor.id}`)" if actor else "> **By:** Unknown"
            embed = discord.Embed(
                title="🔇 Timeout Added",
                color=WARN_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            embed.description = (
                f"> **User:** {after.mention} (`{after.id}`)\n"
                f"> **Until:** <t:{int(a_timeout.timestamp())}:F>\n"
                f"{actor_str}"
            )
            embed.set_footer(text=f"User ID: {after.id}")
            await self._send_log(after.guild.id, "moderation_log", embed)

        # ── Roles (debounced) ──
        roles_added   = [r for r in after.roles if r not in before.roles]
        roles_removed = [r for r in before.roles if r not in after.roles]
        if roles_added or roles_removed:
            key = (after.guild.id, after.id)
            pending = self._role_pending.setdefault(
                key, {"added": [], "removed": [], "member": after}
            )
            pending["added"].extend(roles_added)
            pending["removed"].extend(roles_removed)
            pending["member"] = after
            if key in self._role_debounce:
                self._role_debounce[key].cancel()
            loop = asyncio.get_event_loop()
            self._role_debounce[key] = loop.call_later(
                1.5,
                lambda k=key: asyncio.ensure_future(self._flush_role_log(k)),
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title=f"{EMOJI_ADD} Member Joined",
            color=SUCCESS_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.description = (
            f"> **User:** {member.mention} (`{member.id}`)\n"
            f"> **Account Created:** <t:{int(member.created_at.timestamp())}:R>\n"
            f"> **Member Count:** {member.guild.member_count}"
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await self._send_log(member.guild.id, "join_leave_log", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title=f"{EMOJI_REMOVE} Member Left",
            color=ERROR_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed.description = (
            f"> **User:** {member.mention} (`{member.id}`)\n"
            f"> **Joined:** <t:{int(member.joined_at.timestamp())}:R>\n"
            f"> **Roles:** {', '.join(roles) if roles else 'None'}"
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await self._send_log(member.guild.id, "join_leave_log", embed)



    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not after.guild or after.author.bot:
            return
        if before.content == after.content:
            return
        embed = discord.Embed(
            title=f"{EMOJI_EDIT} Message Edited",
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(after.author), icon_url=after.author.display_avatar.url)
        embed.description = (
            f"> **User:** {after.author.mention} (`{after.author.id}`)\n"
            f"> **Channel:** {after.channel.mention}\n"
            f"> **Message ID:** [`{after.id}`]({after.jump_url})\n"
            f"> **Before:**\n"
            f"{_quote_content(before.content)}\n"
            f"> **After:**\n"
            f"{_quote_content(after.content)}"
        )
        await self._send_log(after.guild.id, "message_edit_log", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        channel = self._get_channel(message.guild.id, "message_delete_log")
        if not channel:
            return

        # Collect image attachments to re-upload
        image_files: list[discord.File] = []
        non_image_names: list[str] = []
        for att in message.attachments:
            if Path(att.filename).suffix.lower() in IMAGE_EXTS:
                try:
                    image_files.append(discord.File(
                        fp=io.BytesIO(await att.read()),
                        filename=att.filename,
                    ))
                except Exception:
                    non_image_names.append(att.filename)
            else:
                non_image_names.append(att.filename)

        embed = discord.Embed(
            title=f"{EMOJI_TRASH} Message Deleted",
            color=ERROR_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.description = (
            f"> **User:** {message.author.mention} (`{message.author.id}`)\n"
            f"> **Channel:** {message.channel.mention}\n"
            f"> **Message ID:** [`{message.id}`]({message.jump_url})\n"
            f"> **Content:** {message.content[:1500] or '*no text content*'}"
        )
        if non_image_names:
            embed.add_field(name="Files", value="\n".join(non_image_names), inline=False)

        try:
            # Send each image as a standalone message BEFORE the embed so they
            # appear above the delete log card in Discord's chat history.
            for img_file in image_files:
                try:
                    await channel.send(file=img_file, allowed_mentions=_NO_MENTIONS)
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await channel.send(embed=embed, allowed_mentions=_NO_MENTIONS)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── Slash commands ─────────────────────────────────────────────────────────

    logger_group = app_commands.Group(name="logger", description="Logger configuration")

    _LOG_CHOICES = [
        app_commands.Choice(name="Default (all events)", value="default_log"),
        app_commands.Choice(name="Avatar changes",       value="avatar_log"),
        app_commands.Choice(name="Username changes",     value="username_log"),
        app_commands.Choice(name="Nickname changes",     value="nickname_log"),
        app_commands.Choice(name="Message edits",        value="message_edit_log"),
        app_commands.Choice(name="Message deletes",      value="message_delete_log"),
        app_commands.Choice(name="Join / Leave",         value="join_leave_log"),
        app_commands.Choice(name="Role add / remove",    value="role_log"),    ]

    @logger_group.command(name="set", description="Set a log channel for a specific event type")
    @app_commands.describe(log_type="The type of events to log", channel="The channel to send logs to")
    @app_commands.choices(log_type=_LOG_CHOICES)
    async def logger_set(self, interaction: discord.Interaction, log_type: str, channel: discord.TextChannel):
        if not self._is_admin(interaction):
            return await interaction.response.send_message(
                embed=discord.Embed(title="Permission Denied",
                    description="> You need Administrator permission.", color=ERROR_COLOR),
                ephemeral=True,
            )
        cfg = load_config()
        gid = str(interaction.guild.id)
        if gid not in cfg:
            cfg[gid] = {}
        cfg[gid][log_type] = channel.id
        save_config(cfg)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Logger Updated",
                description=f"> **Type:** `{log_type}`\n> **Channel:** {channel.mention}",
                color=SUCCESS_COLOR,
                timestamp=datetime.now(timezone.utc),
            ), ephemeral=True,
        )

    @logger_group.command(name="status", description="View current logger configuration")
    async def logger_status(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            return await interaction.response.send_message(
                embed=discord.Embed(title="Permission Denied",
                    description="> You need Administrator permission.", color=ERROR_COLOR),
                ephemeral=True,
            )
        cfg = load_config()
        guild_cfg = get_guild_config(cfg, interaction.guild.id)
        lines = []
        for lt in LOG_TYPES:
            ch_id = guild_cfg.get(lt)
            val = f"<#{ch_id}>" if ch_id else "`Not set`"
            lines.append(f"> **{lt.replace('_', ' ').title()}:** {val}")
        embed = discord.Embed(
            title="📋 Logger Configuration",
            description="\n".join(lines),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @logger_group.command(name="clear", description="Clear the log channel for an event type")
    @app_commands.describe(log_type="The event type to clear")
    @app_commands.choices(log_type=_LOG_CHOICES)
    async def logger_clear(self, interaction: discord.Interaction, log_type: str):
        if not self._is_admin(interaction):
            return await interaction.response.send_message(
                embed=discord.Embed(title="Permission Denied",
                    description="> You need Administrator permission.", color=ERROR_COLOR),
                ephemeral=True,
            )
        cfg = load_config()
        gid = str(interaction.guild.id)
        if gid in cfg and log_type in cfg[gid]:
            del cfg[gid][log_type]
            save_config(cfg)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Logger Cleared",
                description=f"> `{log_type}` log channel removed.",
                color=SUCCESS_COLOR,
            ), ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logger(bot))
