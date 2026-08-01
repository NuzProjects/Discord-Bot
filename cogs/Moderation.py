import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml
import json
import re
import asyncio
from utils.appeals import create_appeal_record
from utils.emojis import Emojis

# ================== CONSTANTS ==================

DATA_DIR  = Path("data")
DATA_FILE = DATA_DIR / "moderation.json"
GUILD_CONFIGS_DIR = DATA_DIR / "guild_configs"

COLOR_SUCCESS = discord.Color.from_rgb(40, 167, 69)
COLOR_ERROR   = discord.Color.from_rgb(220, 53, 69)
COLOR_NEUTRAL = discord.Color.from_rgb(0, 0, 0)
COLOR_WARNING = discord.Color.orange()

DURATION_REGEX = re.compile(r"(\d+)([smhd])")

EMOJI_MUTED = "<:muted:1504298051903164509>"

_NO_MENTIONS = discord.AllowedMentions.none()


def _get_log_channel_id(bot, guild_id: int | str) -> int:
    """Read moderation_log channel from the per-guild YAML, fall back to global config."""
    try:
        path = GUILD_CONFIGS_DIR / f"{guild_id}.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                gcfg = yaml.safe_load(f) or {}
            ch = int((gcfg.get("channels") or {}).get("moderation_log") or 0)
            if ch:
                return ch
    except Exception:
        pass
    cfg = getattr(bot, "config", {}) or {}
    return int((cfg.get("channels") or {}).get("moderation_log") or 0)


# ================== HELPERS ==================

def now():
    return datetime.now(timezone.utc)


def parse_duration(text: str | None):
    if not text:
        return None
    seconds = 0
    for amount, unit in DURATION_REGEX.findall(text.lower()):
        seconds += int(amount) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return timedelta(seconds=seconds) if seconds > 0 else None


def fmt_duration(td: timedelta) -> str:
    s = int(td.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


# ================== STORAGE ==================

def load_data():
    DATA_DIR.mkdir(exist_ok=True)
    default = {"cases": 0, "guilds": {}}
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps(default, indent=4))
        return default
    try:
        data = json.loads(DATA_FILE.read_text() or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    changed = False
    if not isinstance(data.get("cases"), int):
        data["cases"] = 0
        changed = True
    if not isinstance(data.get("guilds"), dict):
        data["guilds"] = {}
        changed = True
    if changed:
        save_data(data)
    return data


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=4))


def new_case(data):
    data.setdefault("cases", 0)
    data.setdefault("guilds", {})
    data["cases"] += 1
    save_data(data)
    return data["cases"]


# ================== REPORT MODAL ==================

class ReportModal(discord.ui.Modal, title="Submit a Report"):
    def __init__(self, cog: "Moderation"):
        super().__init__()
        self.cog = cog

    subject = discord.ui.TextInput(
        label="Report Subject",
        placeholder="Briefly summarize what happened",
        max_length=120, required=True
    )
    reported_user = discord.ui.TextInput(
        label="Reported User (ID or Username)",
        placeholder="Required: @user, username, or user ID",
        max_length=120, required=True
    )
    details = discord.ui.TextInput(
        label="Details", style=discord.TextStyle.paragraph,
        placeholder="Explain what happened with as much detail as possible.",
        max_length=1500, required=True
    )
    evidence = discord.ui.TextInput(
        label="Evidence (optional)", style=discord.TextStyle.paragraph,
        placeholder="Message links, screenshots, timestamps, etc.",
        max_length=1000, required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{self.cog.e.error} Invalid Location",
                    description="> Reports can only be submitted inside a server.",
                    color=COLOR_ERROR
                ), ephemeral=True
            )

        report_channel = self.cog.bot.get_channel(
            _get_log_channel_id(self.cog.bot, interaction.guild.id)
        )
        if not report_channel:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{self.cog.e.error} Report Channel Not Set",
                    description="> A staff report channel is not configured yet.",
                    color=COLOR_ERROR
                ), ephemeral=True
            )

        report_embed = discord.Embed(
            title=f"{self.cog.e.report} New User Report",
            description="\n".join([
                f"> Subject: {self.subject.value}",
                f"> Reporter: {interaction.user.mention} (`{interaction.user.id}`)",
                f"> Reported User: {self.reported_user.value}",
                f"> Channel: {interaction.channel.mention if interaction.channel else 'Unknown'}",
                f"> Details: {self.details.value}",
                f"> Evidence: {self.evidence.value or 'None provided'}"
            ]),
            color=COLOR_WARNING,
            timestamp=now()
        )
        report_embed.set_footer(
            text=f"Reported from {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        try:
            await report_channel.send(embed=report_embed)
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{self.cog.e.error} Cannot Send Report",
                    description="> I don't have permission to send messages in the report channel.",
                    color=COLOR_ERROR
                ), ephemeral=True
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"{self.cog.e.report} Report Submitted",
                description="> Your report has been sent to staff.",
                color=COLOR_SUCCESS
            ), ephemeral=True
        )


# ================== COG ==================

class Moderation(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e   = Emojis(bot)
        load_data()

    # ── Permission checks ──────────────────────────────────────────────────────

    async def check_perms(self, interaction: discord.Interaction, *permissions: str) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        for perm in permissions:
            if getattr(interaction.user.guild_permissions, perm, False):
                return True
        readable = " or ".join(f"`{p.replace('_', ' ').title()}`" for p in permissions)
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"{self.e.error} Permission Denied",
                description="\n".join([
                    "You do not have permission to use this command.",
                    f"> Required: {readable}",
                    f"> Attempted By: {interaction.user.mention}"
                ]),
                color=COLOR_ERROR
            ), ephemeral=True
        )
        return False

    def invalid_target(self, interaction: discord.Interaction, user: discord.Member) -> bool:
        if user.id == interaction.user.id or user.id == self.bot.user.id:
            return True
        if user.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return True
        return False

    # ── Embed builders ─────────────────────────────────────────────────────────

    def _mod_embed(
        self,
        title: str,
        lines: list[str],
        interaction: discord.Interaction,
        color: discord.Color,
        total_warnings: int | None = None,
    ) -> discord.Embed:
        """Embed shown to moderator (ephemeral) and sent to log channel."""
        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=color,
            timestamp=now(),
        )
        footer_parts = [f"Actioned by {interaction.user.display_name}"]
        if total_warnings is not None:
            footer_parts.append(f"Total warnings: {total_warnings}")
        embed.set_footer(
            text=" · ".join(footer_parts),
            icon_url=interaction.user.display_avatar.url,
        )
        return embed

    def _log_embed(
        self,
        title: str,
        lines: list[str],
        interaction: discord.Interaction,
        color: discord.Color,
    ) -> discord.Embed:
        """
        Log-channel embed — matches Logger.py visual style:
        black background color, blockquote lines, moderator as author.
        """
        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=COLOR_NEUTRAL,
            timestamp=now(),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        return embed

    async def dm_user(self, user: discord.Member, embed: discord.Embed) -> None:
        """Send a DM silently — never raises."""
        try:
            await user.send(embed=embed)
        except Exception:
            pass

    async def log_action(
        self,
        interaction: discord.Interaction,
        title: str,
        lines: list[str],
        color: discord.Color = COLOR_NEUTRAL,
    ) -> None:
        """Build a log embed and post it to the moderation log channel."""
        channel_id = _get_log_channel_id(self.bot, interaction.guild.id)
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        embed = self._log_embed(title, lines, interaction, color)
        try:
            await channel.send(embed=embed, allowed_mentions=_NO_MENTIONS)
        except Exception:
            pass

    async def _get_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        *,
        max_age_seconds: int = 12,
        limit: int = 12,
    ) -> discord.AuditLogEntry | None:
        """Return the nearest recent audit log entry for this target."""
        try:
            cutoff = now() - timedelta(seconds=max_age_seconds)
            async for entry in guild.audit_logs(limit=limit, action=action):
                if entry.created_at < cutoff:
                    break
                if entry.target and getattr(entry.target, "id", None) == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    def _event_embed(self, title: str, lines: list[str], color: discord.Color) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=color,
            timestamp=now(),
        )
        return embed

    async def log_event(
        self,
        guild: discord.Guild,
        title: str,
        lines: list[str],
        color: discord.Color = COLOR_NEUTRAL,
    ) -> None:
        channel_id = _get_log_channel_id(self.bot, guild.id)
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        embed = self._event_embed(title, lines, color)
        try:
            await channel.send(embed=embed, allowed_mentions=_NO_MENTIONS)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        b_timeout = getattr(before, "timed_out_until", None)
        a_timeout = getattr(after, "timed_out_until", None)

        if a_timeout and a_timeout != b_timeout:
            await asyncio.sleep(0.8)
            entry = await self._get_audit_entry(
                after.guild, discord.AuditLogAction.member_update, after.id
            )
            if entry and getattr(entry.user, "id", None) == self.bot.user.id:
                return
            actor = entry.user if entry else None
            reason = str(entry.reason).strip() if entry and entry.reason else "No reason provided"

            lines = [
                f"> User: {after.mention} (`{after.id}`)",
                f"> Until: <t:{int(a_timeout.timestamp())}:F>",
                f"> Reason: {reason}",
                f"> By: {actor.mention if actor else 'Unknown'} ({actor.id if actor else 'Unknown'})",
            ]
            await self.log_event(after.guild, f"{EMOJI_MUTED} Member Timed Out", lines, COLOR_WARNING)

            dm_lines = [
                f"> Server: {after.guild.name}",
                f"> Duration Until: <t:{int(a_timeout.timestamp())}:F>",
                f"> Reason: {reason}",
                f"> Actioned by: {actor.mention if actor else 'Unknown'}",
            ]
            dm_embed = self._event_embed(f"{EMOJI_MUTED} You were timed out", dm_lines, COLOR_WARNING)
            await self.dm_user(after, dm_embed)

        elif b_timeout and not a_timeout:
            await asyncio.sleep(0.8)
            entry = await self._get_audit_entry(
                after.guild, discord.AuditLogAction.member_update, after.id
            )
            if entry and getattr(entry.user, "id", None) == self.bot.user.id:
                return
            actor = entry.user if entry else None
            actor_str = f"> By: {actor.mention} (`{actor.id}`)" if actor else "> By: Unknown"
            lines = [
                f"> User: {after.mention} (`{after.id}`)",
                actor_str,
            ]
            await self.log_event(after.guild, f"{EMOJI_MUTED} Timeout Removed", lines, COLOR_SUCCESS)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        await asyncio.sleep(0.8)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.kick, member.id)
        if not entry or getattr(entry.user, "id", None) == self.bot.user.id:
            return
        actor = entry.user
        reason = str(entry.reason).strip() if entry.reason else "No reason provided"
        lines = [
            f"> User: {member} (`{member.id}`)",
            f"> Reason: {reason}",
            f"> By: {actor.mention if actor else 'Unknown'} ({actor.id if actor else 'Unknown'})",
        ]
        await self.log_event(guild, f"{self.e.kick} Member Kicked", lines, COLOR_ERROR)

        dm_lines = [
            f"> Server: {guild.name}",
            f"> Reason: {reason}",
            f"> Actioned by: {actor.mention if actor else 'Unknown'}",
        ]
        dm_embed = self._event_embed(f"{self.e.kick} You were kicked", dm_lines, COLOR_ERROR)
        await self.dm_user(member, dm_embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await asyncio.sleep(0.8)
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry and getattr(entry.user, "id", None) == self.bot.user.id:
            return
        actor = entry.user if entry else None
        reason = str(entry.reason).strip() if entry and entry.reason else "No reason provided"
        lines = [
            f"> User: {user} (`{user.id}`)",
            f"> Reason: {reason}",
            f"> By: {actor.mention if actor else 'Unknown'} ({actor.id if actor else 'Unknown'})",
        ]
        await self.log_event(guild, f"{self.e.ban} Member Banned", lines, COLOR_ERROR)

        dm_lines = [
            f"> Server: {guild.name}",
            f"> Reason: {reason}",
            f"> Actioned by: {actor.mention if actor else 'Unknown'}",
        ]
        dm_embed = self._event_embed(f"{self.e.ban} You were banned", dm_lines, COLOR_ERROR)
        await self.dm_user(user, dm_embed)

    @app_commands.command(name="report", description="Submit a report to server staff")
    async def report(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReportModal(self))

    # ── Purge ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Delete 1–100 messages from this channel")
    @app_commands.describe(amount="Number of messages to delete (1–100)")
    async def purge(self, interaction: discord.Interaction, amount: int):
        if not await self.check_perms(interaction, "manage_messages"):
            return
        if amount < 1 or amount > 100:
            return await interaction.response.send_message(
                embed=self._mod_embed(
                    f"{self.e.error} Invalid Amount",
                    [f"> Provided: `{amount}`", "> Limit: 1–100"],
                    interaction, COLOR_ERROR
                ), ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount, before=interaction.created_at)
        embed = self._mod_embed(
            f"{self.e.trash} Purge Successful",
            [f"> Deleted: `{len(deleted)}` messages", f"> Channel: {interaction.channel.mention}"],
            interaction, COLOR_WARNING
        )
        msg = await interaction.followup.send(embed=embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.trash} Messages Purged",
            [f"> Channel: {interaction.channel.mention}", f"> Amount: `{len(deleted)}` messages"],
        )

    # ── Warn ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Issue a warning to a user")
    @app_commands.describe(user="The member to warn", reason="The reason for the warning")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not await self.check_perms(interaction, "moderate_members", "kick_members", "ban_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        # Defer immediately — DM + appeal creation can take >3s
        await interaction.response.defer(ephemeral=True)

        # Save the warning first so it always persists even if appeal creation fails
        data    = load_data()
        guild   = data["guilds"].setdefault(str(interaction.guild.id), {})
        warns   = guild.setdefault(str(user.id), [])
        case_id = new_case(data)           # increments + saves
        warns.append({"id": case_id, "reason": reason, "by": interaction.user.id, "time": now().isoformat()})
        save_data(data)                    # persist the appended warn

        # Appeal link — never let a failure here break the command
        link = None
        try:
            appeal = create_appeal_record(
                case_id=case_id, guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                user_id=user.id, user_name=str(user), action="warn", reason=reason,
                moderator_id=interaction.user.id,
            )
            link = None  # Appeals are retained locally for staff records.
        except Exception:
            pass

        dm_embed = self._mod_embed(
            f"{self.e.report} User Warned",
            [
                f"> Server: {interaction.guild.name}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                *([ f"> Appeal: [Submit Appeal]({link})" ] if link else []),
            ],
            interaction, COLOR_WARNING
        )
        await self.dm_user(user, dm_embed)

        resp_embed = self._mod_embed(
            f"{self.e.report} User Warned",
            [
                f"> User: {user.mention}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            interaction, COLOR_WARNING,
            total_warnings=len(warns),
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.report} Member Warned",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                f"> Total Warnings: `{len(warns)}`",
            ],
            COLOR_WARNING,
        )

    # ── Warnlist ───────────────────────────────────────────────────────────────

    @app_commands.command(name="warnlist", description="View warnings for a user")
    @app_commands.describe(user="The member to view warnings for (defaults to yourself)")
    async def warnlist(self, interaction: discord.Interaction, user: discord.Member = None):
        user = user or interaction.user
        if user.id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Permission Denied", ["You can only view your own warnings."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        data  = load_data()
        warns = data["guilds"].get(str(interaction.guild.id), {}).get(str(user.id), [])
        if not warns:
            return await interaction.response.send_message(
                embed=self._mod_embed("No Warnings Found", ["This user has no warnings."], interaction, COLOR_SUCCESS)
            )
        formatted = "\n".join(f"`#{w['id']}` • {w['reason']}" for w in warns)
        embed = discord.Embed(
            title=f"{len(warns)} Warning(s) — {user}",
            description=f">>> {formatted}",
            color=COLOR_NEUTRAL
        )
        await interaction.response.send_message(embed=embed)

    # ── Unwarn ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="unwarn", description="Remove a specific warning from a user by case ID")
    @app_commands.describe(user="The member to remove a warning from", case_id="The case ID of the warning to remove")
    async def unwarn(self, interaction: discord.Interaction, user: discord.Member, case_id: int):
        if not await self.check_perms(interaction, "moderate_members", "kick_members", "ban_members"):
            return
        data  = load_data()
        guild = data["guilds"].setdefault(str(interaction.guild.id), {})
        warns = guild.get(str(user.id), [])
        original_count = len(warns)
        new_warns = [w for w in warns if w.get("id") != case_id]
        if len(new_warns) == original_count:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Not Found", [f"> Case ID `{case_id}` not found for {user.mention}."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        guild[str(user.id)] = new_warns
        save_data(data)
        await interaction.response.send_message(
            embed=self._mod_embed(
                f"{self.e.success} Warning Removed",
                [f"> User: {user.mention}", f"> Removed Case ID: `{case_id}`", f"> Remaining warnings: `{len(new_warns)}`"],
                interaction, COLOR_SUCCESS
            ), ephemeral=True
        )
        await self.log_action(interaction, f"{self.e.success} Warning Removed",
            [f"> User: {user.mention} (`{user.id}`)", f"> Removed Case ID: `{case_id}`"],
            COLOR_SUCCESS)

    # ── Clear warns ────────────────────────────────────────────────────────────

    @app_commands.command(name="clearwarns", description="Clear all warnings for a user")
    @app_commands.describe(user="The member to clear warnings for")
    async def clearwarns(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.check_perms(interaction, "moderate_members", "kick_members", "ban_members"):
            return
        data  = load_data()
        guild = data["guilds"].setdefault(str(interaction.guild.id), {})
        count = len(guild.get(str(user.id), []))
        guild.pop(str(user.id), None)
        save_data(data)
        await interaction.response.send_message(
            embed=self._mod_embed(
                f"{self.e.success} Warnings Cleared",
                [f"> User: {user.mention}", f"> Removed: `{count}` warning(s)"],
                interaction, COLOR_SUCCESS
            )
        )

    # ── Kick ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(user="The member to kick", reason="The reason for kicking")
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "kick_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        case_id = new_case(load_data())
        link = None
        try:
            appeal = create_appeal_record(
                case_id=case_id, guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                user_id=user.id, user_name=str(user), action="kick", reason=reason,
                moderator_id=interaction.user.id,
            )
            link = None  # Appeals are retained locally for staff records.
        except Exception:
            pass

        dm_embed = self._mod_embed(
            f"{self.e.kick} User Kicked",
            [
                f"> Server: {interaction.guild.name}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                *([ f"> Appeal: [Submit Appeal]({link})" ] if link else []),
            ],
            interaction, COLOR_WARNING
        )
        await self.dm_user(user, dm_embed)

        try:
            await user.kick(reason=f"{reason} | Case #{case_id}")
        except discord.Forbidden as e:
            reason_str = "I don't have permission to kick this user."
            if user.top_role >= interaction.guild.me.top_role:
                reason_str = f"I cannot kick {user.mention} — their highest role is equal to or above mine."
            elif user.guild_permissions.administrator:
                reason_str = f"I cannot kick {user.mention} — they have Administrator permissions."
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Role Hierarchy Error", [reason_str], interaction, COLOR_ERROR),
                ephemeral=True
            )

        resp_embed = self._mod_embed(
            f"{self.e.kick} User Kicked",
            [f"> User: {user.mention}", f"> Reason: {reason}", f"> Case ID: `{case_id}`"],
            interaction, COLOR_WARNING
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.kick} Member Kicked",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            COLOR_ERROR,
        )

    # ── Ban ────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Permanently ban a member from the server")
    @app_commands.describe(user="The member to ban", reason="The reason for banning")
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "ban_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Missing Bot Permission", ["I do not have permission to ban members."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        case_id = new_case(load_data())
        link = None
        try:
            appeal = create_appeal_record(
                case_id=case_id, guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                user_id=user.id, user_name=str(user), action="ban", reason=reason,
                moderator_id=interaction.user.id,
            )
            link = None  # Appeals are retained locally for staff records.
        except Exception:
            pass

        dm_embed = self._mod_embed(
            f"{self.e.ban} User Banned",
            [
                f"> Server: {interaction.guild.name}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                *([ f"> Appeal: [Submit Appeal]({link})" ] if link else []),
            ],
            interaction, COLOR_ERROR
        )
        await self.dm_user(user, dm_embed)

        try:
            await user.ban(reason=f"{reason} | Case #{case_id}", delete_message_days=0)
        except discord.Forbidden:
            reason_str = "I don't have permission to ban this user."
            if user.top_role >= interaction.guild.me.top_role:
                reason_str = f"I cannot ban {user.mention} — their highest role is equal to or above mine."
            elif user.guild_permissions.administrator:
                reason_str = f"I cannot ban {user.mention} — they have Administrator permissions."
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Role Hierarchy Error", [reason_str], interaction, COLOR_ERROR),
                ephemeral=True
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Ban Failed", [f"Discord error: {exc}"], interaction, COLOR_ERROR),
                ephemeral=True
            )

        resp_embed = self._mod_embed(
            f"{self.e.ban} User Banned",
            [f"> User: {user.mention}", f"> Reason: {reason}", f"> Case ID: `{case_id}`"],
            interaction, COLOR_ERROR
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.ban} Member Banned",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            COLOR_ERROR,
        )

    # ── Softban ────────────────────────────────────────────────────────────────

    @app_commands.command(name="softban", description="Silently ban a member without notifying them")
    @app_commands.describe(user="The member to softban", reason="The reason for the softban")
    async def softban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "ban_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Missing Bot Permission", ["I do not have permission to ban members."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        case_id = new_case(load_data())

        # Ban without DM — no appeal record, no notification to the user
        try:
            await user.ban(reason=f"{reason} | Case #{case_id} (softban)", delete_message_days=0)
        except discord.Forbidden:
            reason_str = "I don't have permission to ban this user."
            if user.top_role >= interaction.guild.me.top_role:
                reason_str = f"I cannot ban {user.mention} — their highest role is equal to or above mine."
            elif user.guild_permissions.administrator:
                reason_str = f"I cannot ban {user.mention} — they have Administrator permissions."
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Role Hierarchy Error", [reason_str], interaction, COLOR_ERROR),
                ephemeral=True
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Softban Failed", [f"Discord error: {exc}"], interaction, COLOR_ERROR),
                ephemeral=True
            )

        resp_embed = self._mod_embed(
            f"{self.e.ban} User Softbanned",
            [
                f"> User: {user.mention}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                "> Note: The user was **not** notified.",
            ],
            interaction, COLOR_ERROR
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.ban} Member Softbanned",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                "> The user was not notified.",
            ],
            COLOR_ERROR,
        )

    # ── Unban ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a user by their Discord ID")
    @app_commands.describe(user_id="The ID of the user to unban")
    async def unban(self, interaction: discord.Interaction, user_id: str):
        if not await self.check_perms(interaction, "ban_members"):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user)
        except Exception:
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Error", ["Unable to unban user. Check the ID and try again."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        dm_embed = self._mod_embed(
            f"{self.e.ban} User Unbanned",
            [f"> Server: {interaction.guild.name}"],
            interaction, COLOR_SUCCESS
        )
        await self.dm_user(user, dm_embed)

        resp_embed = self._mod_embed(
            f"{self.e.ban} User Unbanned",
            [f"> User: {user}", f"> ID: `{user.id}`"],
            interaction, COLOR_SUCCESS
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.ban} Member Unbanned",
            [f"> User: {user} (`{user.id}`)"],
            COLOR_SUCCESS,
        )

    # ── Mute ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Timeout (mute) a member for a set duration")
    @app_commands.describe(
        user="The member to mute",
        duration="Duration of the mute (e.g. 10m, 2h, 1d)",
        reason="The reason for muting"
    )
    async def mute(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "moderate_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        delta = parse_duration(duration)
        if not delta:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Invalid Duration", ["Use a format like `10m`, `2h`, or `1d`."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        case_id = new_case(load_data())
        link = None
        try:
            appeal = create_appeal_record(
                case_id=case_id, guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                user_id=user.id, user_name=str(user), action="mute", reason=reason,
                moderator_id=interaction.user.id,
            )
            link = None  # Appeals are retained locally for staff records.
        except Exception:
            pass

        try:
            await user.timeout(delta, reason=reason)
        except discord.Forbidden:
            reason_str = "I don't have permission to timeout this user."
            if user.top_role >= interaction.guild.me.top_role:
                reason_str = f"I cannot timeout {user.mention} — their highest role is equal to or above mine."
            elif user.guild_permissions.administrator:
                reason_str = f"I cannot timeout {user.mention} — they have Administrator permissions."
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Role Hierarchy Error", [reason_str], interaction, COLOR_ERROR),
                ephemeral=True
            )

        until_ts = int((datetime.now(timezone.utc) + delta).timestamp())
        dm_embed = self._mod_embed(
            f"{EMOJI_MUTED} User Muted",
            [
                f"> Server: {interaction.guild.name}",
                f"> Duration: {fmt_duration(delta)}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                *([ f"> Appeal: [Submit Appeal]({link})" ] if link else []),
            ],
            interaction, COLOR_WARNING
        )
        await self.dm_user(user, dm_embed)

        resp_embed = self._mod_embed(
            f"{EMOJI_MUTED} User Muted",
            [
                f"> User: {user.mention}",
                f"> Duration: {fmt_duration(delta)}",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            interaction, COLOR_WARNING
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{EMOJI_MUTED} Member Muted",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Duration: {fmt_duration(delta)}",
                f"> Until: <t:{until_ts}:F>",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            COLOR_WARNING,
        )

    # ── Unmute ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Remove a timeout from a member")
    @app_commands.describe(user="The member to unmute")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.check_perms(interaction, "moderate_members"):
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await user.timeout(None)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Permission Error", ["I don't have permission to remove this user's timeout."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        dm_embed = self._mod_embed(
            f"{self.e.success} User Unmuted",
            [f"> Server: {interaction.guild.name}"],
            interaction, COLOR_SUCCESS
        )
        await self.dm_user(user, dm_embed)

        resp_embed = self._mod_embed(
            f"{self.e.success} User Unmuted",
            [f"> User: {user.mention}"],
            interaction, COLOR_SUCCESS
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.success} Member Unmuted",
            [f"> User: {user.mention} (`{user.id}`)"],
            COLOR_SUCCESS,
        )

    # ── Slowmode ───────────────────────────────────────────────────────────────

    @app_commands.command(name="slowmode", description="Set a slowmode delay on the current channel")
    @app_commands.describe(duration="Delay between messages (e.g. 10s, 1m) — or 'off' to disable")
    async def slowmode(self, interaction: discord.Interaction, duration: str):
        if not await self.check_perms(interaction, "manage_channels"):
            return
        if duration.lower() in ["off", "0"]:
            seconds = 0
        else:
            delta = parse_duration(duration)
            if not delta:
                return await interaction.response.send_message(
                    embed=self._mod_embed(f"{self.e.error} Invalid Duration", ["Use a format like `10s`, `1m`, or `off` to disable."], interaction, COLOR_ERROR),
                    ephemeral=True
                )
            seconds = int(delta.total_seconds())
        await interaction.channel.edit(slowmode_delay=seconds)
        label = "Disabled" if seconds == 0 else duration
        embed = self._mod_embed(
            f"{self.e.slowmode} Slowmode Updated",
            [f"> Channel: {interaction.channel.mention}", f"> Delay: `{label}`"],
            interaction, COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.log_action(
            interaction,
            f"{self.e.slowmode} Slowmode Updated",
            [f"> Channel: {interaction.channel.mention}", f"> Delay: `{label}`"],
        )

    # ── Lock / Unlock ──────────────────────────────────────────────────────────

    async def _toggle_lock(self, channel, guild, lock: bool):
        for target, overwrite in channel.overwrites.items():
            if not isinstance(target, discord.Role):
                continue
            if target.permissions.administrator or target.managed:
                continue
            overwrite.send_messages = False if lock else None
            await channel.set_permissions(target, overwrite=overwrite)

    @app_commands.command(name="lock", description="Prevent members from sending messages in this channel")
    @app_commands.describe(reason="Reason for locking the channel")
    async def lock(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "manage_channels"):
            return
        await interaction.response.defer(ephemeral=True)
        await self._toggle_lock(interaction.channel, interaction.guild, True)
        embed = self._mod_embed(
            f"{self.e.lock} Channel Locked",
            [f"> Channel: {interaction.channel.mention}", f"> Reason: {reason}", "> Members cannot send messages."],
            interaction, COLOR_ERROR
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        # Public channel message
        public_embed = discord.Embed(
            title=f"{self.e.lock} Channel Locked",
            description=f"> This channel has been locked by {interaction.user.mention}.\n> **Reason:** {reason}",
            color=COLOR_ERROR,
        )
        try:
            await interaction.channel.send(embed=public_embed)
        except discord.Forbidden:
            pass
        await self.log_action(interaction, f"{self.e.lock} Channel Locked",
            [f"> Channel: {interaction.channel.mention}", f"> Reason: {reason}"], COLOR_ERROR)

    @app_commands.command(name="unlock", description="Allow members to send messages in this channel again")
    @app_commands.describe(reason="Reason for unlocking the channel")
    async def unlock(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "manage_channels"):
            return
        await interaction.response.defer(ephemeral=True)
        await self._toggle_lock(interaction.channel, interaction.guild, False)
        embed = self._mod_embed(
            f"{self.e.unlock} Channel Unlocked",
            [f"> Channel: {interaction.channel.mention}", f"> Reason: {reason}", "> Members can send messages again."],
            interaction, COLOR_SUCCESS
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        public_embed = discord.Embed(
            title=f"{self.e.unlock} Channel Unlocked",
            description=f"> This channel has been unlocked by {interaction.user.mention}.\n> **Reason:** {reason}",
            color=COLOR_SUCCESS,
        )
        try:
            await interaction.channel.send(embed=public_embed)
        except discord.Forbidden:
            pass
        await self.log_action(interaction, f"{self.e.unlock} Channel Unlocked",
            [f"> Channel: {interaction.channel.mention}", f"> Reason: {reason}"], COLOR_SUCCESS)

    @app_commands.command(name="lockall", description="Lock all text channels in the server")
    async def lockall(self, interaction: discord.Interaction):
        if not await self.check_perms(interaction, "administrator"):
            return
        await interaction.response.defer(ephemeral=True)
        for channel in interaction.guild.text_channels:
            await self._toggle_lock(channel, interaction.guild, True)
        embed = self._mod_embed(
            f"{self.e.lock} Server Locked",
            [f"> Channels: `{len(interaction.guild.text_channels)}`", "> Only Admins may speak."],
            interaction, COLOR_ERROR
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.log_action(interaction, f"{self.e.lock} Server Locked",
            [f"> Channels: `{len(interaction.guild.text_channels)}`"], COLOR_ERROR)

    @app_commands.command(name="unlockall", description="Unlock all text channels in the server")
    async def unlockall(self, interaction: discord.Interaction):
        if not await self.check_perms(interaction, "administrator"):
            return
        await interaction.response.defer(ephemeral=True)
        for channel in interaction.guild.text_channels:
            await self._toggle_lock(channel, interaction.guild, False)
        embed = self._mod_embed(
            f"{self.e.unlock} Server Unlocked",
            [f"> Channels: `{len(interaction.guild.text_channels)}`", "> Members can send messages again."],
            interaction, COLOR_SUCCESS
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.log_action(interaction, f"{self.e.unlock} Server Unlocked",
            [f"> Channels: `{len(interaction.guild.text_channels)}`"], COLOR_SUCCESS)


    # ── Temp-ban ────────────────────────────────────────────────────────────────

    @app_commands.command(name="temp-ban", description="Ban a member for a specified duration")
    @app_commands.describe(
        user="The member to temporarily ban",
        duration="Duration (e.g. 1h, 30m, 2d, 1h30m)",
        reason="The reason for the temporary ban"
    )
    async def tempban(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
        if not await self.check_perms(interaction, "ban_members"):
            return
        if self.invalid_target(interaction, user):
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Action Denied", ["Invalid target."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Missing Bot Permission", ["I do not have permission to ban members."], interaction, COLOR_ERROR),
                ephemeral=True
            )
        # Parse duration string e.g. "1h30m", "2d", "45m"
        import re as _re
        total_seconds = 0
        for amount, unit in _re.findall(r"(\d+)([smhd])", duration.lower()):
            amount = int(amount)
            if unit == "s": total_seconds += amount
            elif unit == "m": total_seconds += amount * 60
            elif unit == "h": total_seconds += amount * 3600
            elif unit == "d": total_seconds += amount * 86400
        if total_seconds < 60:
            return await interaction.response.send_message(
                embed=self._mod_embed(f"{self.e.error} Invalid Duration", ["Minimum duration is 60 seconds. Use formats like `1h`, `30m`, `2d`, `1h30m`."], interaction, COLOR_ERROR),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        import datetime as _dt
        unban_at = now() + _dt.timedelta(seconds=total_seconds)
        # Format duration for display
        parts = []
        remaining = total_seconds
        if remaining >= 86400: parts.append(f"{remaining // 86400}d"); remaining %= 86400
        if remaining >= 3600:  parts.append(f"{remaining // 3600}h"); remaining %= 3600
        if remaining >= 60:    parts.append(f"{remaining // 60}m"); remaining %= 60
        if remaining:          parts.append(f"{remaining}s")
        duration_str = " ".join(parts)

        case_id = new_case(load_data())
        link = None
        try:
            appeal = create_appeal_record(
                case_id=case_id, guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                user_id=user.id, user_name=str(user), action="tempban", reason=reason,
                moderator_id=interaction.user.id,
            )
            link = None  # Appeals are retained locally for staff records.
        except Exception:
            pass

        dm_embed = self._mod_embed(
            f"{self.e.ban} Temporarily Banned",
            [
                f"> Server: {interaction.guild.name}",
                f"> Duration: {duration_str}",
                f"> Expires: <t:{int(unban_at.timestamp())}:F>",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
                *([ f"> Appeal: [Submit Appeal]({link})" ] if link else []),
            ],
            interaction, COLOR_ERROR
        )
        await self.dm_user(user, dm_embed)

        try:
            await user.ban(reason=f"[TEMPBAN {duration_str}] {reason} | Case #{case_id}", delete_message_days=0)
        except discord.Forbidden:
            reason_str = "I don't have permission to ban this user."
            if user.top_role >= interaction.guild.me.top_role:
                reason_str = f"I cannot ban {user.mention} — their highest role is equal to or above mine."
            elif user.guild_permissions.administrator:
                reason_str = f"I cannot ban {user.mention} — they have Administrator permissions."
            return await interaction.followup.send(
                embed=self._mod_embed(f"{self.e.error} Role Hierarchy Error", [reason_str], interaction, COLOR_ERROR),
                ephemeral=True
            )

        resp_embed = self._mod_embed(
            f"{self.e.ban} User Temporarily Banned",
            [
                f"> User: {user.mention}",
                f"> Duration: {duration_str}",
                f"> Expires: <t:{int(unban_at.timestamp())}:F>",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            interaction, COLOR_ERROR
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self.log_action(interaction, f"{self.e.ban} Member Temporarily Banned",
            [
                f"> User: {user.mention} (`{user.id}`)",
                f"> Duration: {duration_str}",
                f"> Expires: <t:{int(unban_at.timestamp())}:F>",
                f"> Reason: {reason}",
                f"> Case ID: `{case_id}`",
            ],
            COLOR_ERROR)

        # Schedule unban
        async def _do_unban():
            await _dt.asyncio.sleep(total_seconds) if False else None
            import asyncio as _asyncio
            await _asyncio.sleep(total_seconds)
            try:
                await interaction.guild.unban(user, reason=f"Tempban expired | Case #{case_id}")
            except Exception:
                pass
        self.bot.loop.create_task(_do_unban())


# ================== SETUP ==================

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
