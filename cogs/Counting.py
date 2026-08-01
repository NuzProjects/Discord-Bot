import discord
import asyncio
from utils.emojis import Emojis, _DEFAULTS as _E
from discord.ext import commands, tasks
from discord import app_commands
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

# =========================================================
# STORAGE
# =========================================================

DATA_DIR  = Path("data/counting")
DATA_FILE = DATA_DIR / "data.json"

EMBED_COLOR   = discord.Color.from_rgb(0, 0, 0)
ERROR_COLOR   = discord.Color.from_rgb(255, 0, 0)
SUCCESS_COLOR = discord.Color.from_rgb(40, 167, 69)
INFO_COLOR    = discord.Color.from_rgb(23, 162, 184)


class EmbedFactory:
    @staticmethod
    def base(title, description, color):
        return discord.Embed(title=title, description=description, color=color,
                             timestamp=datetime.now(timezone.utc))
    @staticmethod
    def success(title, description):
        return EmbedFactory.base(title, f"> {_E['success']} {description}", SUCCESS_COLOR)
    @staticmethod
    def error(title, description):
        return EmbedFactory.base(title, f"> {_E['error']} {description}", ERROR_COLOR)
    @staticmethod
    def info(title, description):
        return EmbedFactory.base(title, f"> {_E['info']} {description}", INFO_COLOR)
    @staticmethod
    def permission():
        return EmbedFactory.error(f"{_E['error']} Permission Denied",
                                  "You do not have permission to use this command.")


class CountingStorage:
    @staticmethod
    def ensure():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not DATA_FILE.exists():
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)

    @staticmethod
    def load() -> Dict:
        try:
            if not DATA_FILE.exists():
                return {}
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    @staticmethod
    def save(data: Dict):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)


# =========================================================
# UI COMPONENTS
# =========================================================

class LeaderboardView(discord.ui.View):
    def __init__(self, pages: List[str], user_id: int, requester: discord.Member):
        super().__init__(timeout=120)
        self.pages = pages
        self.index = 0
        self.user_id = user_id
        self.requester = requester
        self._update_state()
        self.prev_page.emoji = discord.PartialEmoji.from_str(_E["left"])
        self.next_page.emoji = discord.PartialEmoji.from_str(_E["right"])

    def _update_state(self):
        self.prev_page.disabled = (self.index == 0)
        self.next_page.disabled = (self.index >= len(self.pages) - 1)

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Counting Leaderboard",
            description=self.pages[self.index],
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"Requested by {self.requester} • Page {self.index + 1}/{len(self.pages)}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=EmbedFactory.error("Unauthorized",
                    "Only the user who requested this leaderboard can navigate."),
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="counting_lb_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self._update_state()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="counting_lb_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self._update_state()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


# =========================================================
# MAIN COG
# =========================================================

class Counting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        CountingStorage.ensure()
        self.update_top_counter_role.start()

    def cog_unload(self):
        self.update_top_counter_role.cancel()

    async def _update_counting_sticky(self, channel: discord.TextChannel, next_count: int):
        """Delete the previous sticky and post a cv2 sticky showing the next expected count."""
        import discord.http as _dhttp

        guild_id = str(channel.guild.id)
        data = CountingStorage.load()
        cfg = data.get(guild_id)
        if not cfg:
            return

        old_id = cfg.get("sticky_message_id")

        # Clean up any orphaned sticky messages in the last 25 messages of the channel
        try:
            async for msg in channel.history(limit=25):
                if msg.author.id == self.bot.user.id:
                    is_sticky = False
                    if msg.content and ("Counting" in msg.content or "The next number is" in msg.content):
                        is_sticky = True
                    if not is_sticky and msg.components:
                        for row in msg.components:
                            row_str = str(row)
                            if "Counting" in row_str or "next number" in row_str or "only count once" in row_str:
                                is_sticky = True
                                break
                    if msg.id == old_id:
                        is_sticky = True
                    if is_sticky:
                        try:
                            await msg.delete()
                        except Exception:
                            pass
        except Exception as e:
            print(f"[Counting] Error cleaning up sticky history: {e}")

        # Ensure database is clean of old sticky id
        if old_id:
            cfg["sticky_message_id"] = None
            CountingStorage.save(data)

        # Post new sticky using raw components v2 payload (no accent color, correct format)
        components = [
            {
                "type": 17,
                "accent_color": None,
                "spoiler": False,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            f"## Counting\n"
                            f"> The next number is **`{next_count}`**\n"
                            f"-# You can only count once in a row!"
                        ),
                    }
                ],
            }
        ]
        try:
            route = _dhttp.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id)
            resp = await self.bot.http.request(route, json={"components": components, "flags": 32768})
            new_id = int(resp["id"])
            
            # Reload and save to avoid race conditions
            data = CountingStorage.load()
            if guild_id in data:
                data[guild_id]["sticky_message_id"] = new_id
                CountingStorage.save(data)
        except Exception as exc:
            print(f"[Counting] sticky post error: {exc}")

    def _get_guild_cfg(self, guild_id: str) -> Dict:
        """Get guild config from data.json, falling back to config.yaml counting section."""
        data = CountingStorage.load()
        cfg = data.get(guild_id, {})
        # Pull counting settings from the bot configuration.
        bot_cfg = (getattr(self.bot, "config", {}) or {}).get("counting") or {}
        # These keys can be overridden per-guild in data.json or globally in config.yaml
        defaults = {
            "emoji":        bot_cfg.get("emoji", "✅"),
            "fail_emoji":   bot_cfg.get("fail_emoji", "❌"),
            "reset_on_fail": str(bot_cfg.get("reset_on_fail", "false")).lower() == "true",
            "reaction_role": bot_cfg.get("reaction_role", None),
            "top_counter_role": bot_cfg.get("top_counter_role", None),
        }
        for k, v in defaults.items():
            if k not in cfg:
                cfg[k] = v
        return cfg

    # --------------------------------------------------
    # BACKGROUND TASKS
    # --------------------------------------------------

    @tasks.loop(hours=24)
    async def update_top_counter_role(self):
        data = CountingStorage.load()
        if not data:
            return
        for guild_id_str, cfg in data.items():
            scores = cfg.get("scores")
            if not scores:
                continue
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                continue
            role_id = cfg.get("top_counter_role") or 0
            if not role_id:
                continue
            role = guild.get_role(int(role_id))
            if not role:
                continue
            try:
                top_uid_str = max(scores, key=lambda k: scores[k])
                top_uid = int(top_uid_str)
            except (ValueError, TypeError):
                continue
            for member in role.members:
                if member.id != top_uid:
                    try:
                        await member.remove_roles(role, reason="Counting: No longer top counter.")
                    except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                        pass
            top_member = guild.get_member(top_uid)
            if top_member and role not in top_member.roles:
                try:
                    await top_member.add_roles(role, reason="Counting: Reached #1 on leaderboard.")
                except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                    pass

    @update_top_counter_role.before_loop
    async def before_update_top_counter_role(self):
        await self.bot.wait_until_ready()

    # --------------------------------------------------
    # ADMIN COMMANDS
    # --------------------------------------------------

    @app_commands.command(name="csetup", description="Set up or update counting configuration")
    @app_commands.describe(
        channel="The counting channel",
        emoji="Emoji to react with for correct counts",
        fail_emoji="Emoji to react with on wrong count",
        reset_on_fail="Restart count from 0 when someone messes up",
        reaction_role="Role to give to users when they count (optional)"
    )
    async def csetup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        emoji: Optional[str] = None,
        fail_emoji: Optional[str] = None,
        reset_on_fail: Optional[bool] = None,
        reaction_role: Optional[discord.Role] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(embed=EmbedFactory.permission(), ephemeral=True)

        data = CountingStorage.load()
        guild_id = str(interaction.guild_id)
        existing = data.get(guild_id, {})

        # Pull defaults from bot config
        bot_cfg = (getattr(self.bot, "config", {}) or {}).get("counting") or {}

        data[guild_id] = {
            "channel":        channel.id,
            "current":        existing.get("current", 0),
            "emoji":          emoji or existing.get("emoji") or bot_cfg.get("emoji", "✅"),
            "fail_emoji":     fail_emoji or existing.get("fail_emoji") or bot_cfg.get("fail_emoji", "❌"),
            "reset_on_fail":  reset_on_fail if reset_on_fail is not None else existing.get("reset_on_fail", False),
            "reaction_role":  reaction_role.id if reaction_role else existing.get("reaction_role"),
            "top_counter_role": existing.get("top_counter_role"),
            "scores":         existing.get("scores", {}),
            "last_user":      existing.get("last_user"),
            "last_message":   existing.get("last_message"),
        }
        CountingStorage.save(data)

        reset_label = "Restart" if data[guild_id]["reset_on_fail"] else "Continue (just delete)"
        role_label = reaction_role.mention if reaction_role else (
            f"<@&{existing['reaction_role']}>" if existing.get("reaction_role") else "None"
        )

        await interaction.response.send_message(embed=EmbedFactory.success(
            "Counting Setup",
            f"Channel: {channel.mention}\n"
            f"✅ Emoji: {data[guild_id]['emoji']} | ❌ Fail: {data[guild_id]['fail_emoji']}\n"
            f"On fail: {reset_label} | Reaction role: {role_label}"
        ))

    @app_commands.command(name="creset", description="Reset the count to 0")
    async def creset(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(embed=EmbedFactory.permission(), ephemeral=True)
        data = CountingStorage.load()
        guild_id = str(interaction.guild_id)
        if guild_id not in data:
            return await interaction.response.send_message(
                embed=EmbedFactory.error("Not Set Up", "Use /csetup first."), ephemeral=True)
        data[guild_id]["current"] = 0
        data[guild_id]["last_user"] = None
        data[guild_id]["last_message"] = None
        CountingStorage.save(data)
        await interaction.response.send_message(embed=EmbedFactory.success("Count Reset", "The count has been reset to 0."))

    @app_commands.command(name="cimport", description="Import data from Countr JSON export")
    @app_commands.describe(channel="Target channel", file="The JSON file")
    async def cimport(self, interaction: discord.Interaction, channel: discord.TextChannel, file: discord.Attachment):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(embed=EmbedFactory.permission(), ephemeral=True)
        if not file.filename.endswith(".json"):
            return await interaction.response.send_message(
                embed=EmbedFactory.error("Invalid File", "Please upload a .json file."), ephemeral=True)
        try:
            content = await file.read()
            raw_data = json.loads(content.decode("utf-8"))
        except Exception:
            return await interaction.response.send_message(
                embed=EmbedFactory.error("Parse Error", "Failed to read the JSON file."), ephemeral=True)
        channel_data = raw_data.get("channels", {}).get(str(channel.id))
        if not channel_data:
            return await interaction.response.send_message(
                embed=EmbedFactory.error("Data Missing", f"No data found for channel {channel.id}."), ephemeral=True)
        data = CountingStorage.load()
        data[str(interaction.guild_id)] = {
            "channel":      channel.id,
            "current":      channel_data.get("count", {}).get("number", 0),
            "emoji":        "✅",
            "fail_emoji":   "❌",
            "reset_on_fail": False,
            "reaction_role": None,
            "scores":       channel_data.get("scores", {}),
            "last_user":    int(channel_data.get("count", {}).get("userId", 0)) or None,
            "last_message": None,
        }
        CountingStorage.save(data)
        await interaction.response.send_message(
            embed=EmbedFactory.success("Import Successful", f"Imported scores and count for {channel.mention}."))

    # --------------------------------------------------
    # GAMEPLAY LISTENERS
    # --------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        data = CountingStorage.load()
        guild_id = str(message.guild.id)
        cfg = data.get(guild_id)

        if not cfg or message.channel.id != cfg.get("channel"):
            return

        # Block commands and non-digits
        if message.content.startswith(("/", "!", "?", ".")) or not message.content.strip().isdigit():
            try:
                await message.delete()
            except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                pass
            return

        user_val = int(message.content.strip())
        expected = cfg["current"] + 1

        # Wrong number
        if user_val != expected:
            await self._handle_fail(message, cfg, data, guild_id, "wrong_number")
            return

        # Double count
        if message.author.id == cfg.get("last_user"):
            try:
                await message.delete()
            except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                pass
            return

        # Valid count
        cfg["current"] = user_val
        cfg["last_user"] = message.author.id
        cfg["last_message"] = message.id
        uid_str = str(message.author.id)
        cfg["scores"][uid_str] = cfg["scores"].get(uid_str, 0) + 1
        CountingStorage.save(data)

        # React with success emoji
        try:
            await message.add_reaction(cfg.get("emoji", "✅"))
        except discord.NotFound:
            pass
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            try:
                await message.add_reaction("✅")
            except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                pass

        # Update counting sticky with the next expected number
        await self._update_counting_sticky(message.channel, user_val + 1)

        # Assign reaction role if configured
        role_id = cfg.get("reaction_role")
        if role_id:
            role = message.guild.get_role(int(role_id))
            if role and isinstance(message.author, discord.Member):
                try:
                    if role not in message.author.roles:
                        await message.author.add_roles(role, reason="Counted successfully")
                except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                    pass

    async def _handle_fail(self, message: discord.Message, cfg: dict, data: dict, guild_id: str, reason: str):
        """Handle a counting failure."""
        fail_emoji = cfg.get("fail_emoji", "❌")
        reset = cfg.get("reset_on_fail", False)

        # React with fail emoji before deleting
        try:
            await message.add_reaction(fail_emoji)
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            pass

        await asyncio.sleep(1.5)

        try:
            await message.delete()
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            pass

        if reset:
            old_count = cfg["current"]
            cfg["current"] = 0
            cfg["last_user"] = None
            cfg["last_message"] = None
            CountingStorage.save(data)
            try:
                await message.channel.send(
                    f"❌ {message.author.mention} ruined the count at **{old_count}**! Starting over from **0**.",
                    delete_after=8
                )
            except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
                pass
            # Update sticky to show next expected count (1 after reset)
            await self._update_counting_sticky(message.channel, 1)
        else:
            CountingStorage.save(data)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        data = CountingStorage.load()
        cfg = data.get(str(message.guild.id))
        if not cfg or message.id != cfg.get("last_message"):
            return
        channel = message.channel
        member = message.author
        name = member.display_name if member else "Unknown"
        try:
            resend = await channel.send(f"**{name}:** {cfg['current']}")
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            return
        try:
            await resend.add_reaction(cfg.get("emoji", "✅"))
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            pass
        cfg["last_message"] = resend.id
        CountingStorage.save(data)
        # Refresh sticky so it remains the last message
        await self._update_counting_sticky(channel, cfg["current"] + 1)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild:
            return
        data = CountingStorage.load()
        cfg = data.get(str(after.guild.id))
        if not cfg or after.id != cfg.get("last_message"):
            return
        try:
            await after.delete()
        except (discord.HTTPException, asyncio.TimeoutError, TimeoutError):
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        data = CountingStorage.load()
        cfg = data.get(str(interaction.guild.id))
        if cfg and interaction.channel_id == cfg.get("channel"):
            if interaction.type == discord.InteractionType.application_command:
                cmd_name = getattr(interaction.command, "name", "")
                if cmd_name not in ["csetup", "cimport", "creset"]:
                    await interaction.response.send_message(
                        embed=EmbedFactory.error("Restricted", "Commands are not allowed in this channel."),
                        ephemeral=True
                    )

    # --------------------------------------------------
    # LEADERBOARD
    # --------------------------------------------------

    @app_commands.command(name="lbcounts", description="View the counting leaderboard")
    async def lbcounts(self, interaction: discord.Interaction):
        data = CountingStorage.load()
        cfg = data.get(str(interaction.guild_id))
        if not cfg or not cfg.get("scores"):
            return await interaction.response.send_message(
                embed=EmbedFactory.info("No Data", "No counting data recorded yet."), ephemeral=True)

        sorted_scores = sorted(cfg["scores"].items(), key=lambda x: x[1], reverse=True)
        trophy_map = {
            1: "<a:gold:1494064565531443351>",
            2: "<a:silver:1494064563086299347>",
            3: "<a:bronze:1494064564604633293>",
        }
        pages = []
        for i in range(0, len(sorted_scores), 10):
            chunk = sorted_scores[i:i + 10]
            lines = []
            for rank, (uid_str, score) in enumerate(chunk, start=i + 1):
                member = interaction.guild.get_member(int(uid_str))
                name = member.display_name if member else f"User({uid_str})"
                icon = trophy_map.get(rank, f"`#{rank:02}`")
                line = f"{icon} **{name}** — {score:,} counts"
                if interaction.user.id == int(uid_str):
                    line += " **(You)**"
                lines.append(line)
            pages.append("\n".join(lines))

        view = LeaderboardView(pages, interaction.user.id, interaction.user)
        await interaction.response.send_message(embed=view.create_embed(), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
