import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
import psutil
import os
import sys
import platform
import datetime
import asyncio
import json
from pathlib import Path

LOG_FILE = Path("logs/bot.log")
RESTART_FILE = Path("data/restart.json")

EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
ERROR_COLOR = discord.Color.red()
SUCCESS_COLOR = discord.Color.from_rgb(40, 167, 69)
WARNING_COLOR = discord.Color.from_rgb(255, 193, 7)

# ===============================
# Restart Confirmation View
# ===============================
class RestartView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=30)
        self.bot = bot
        self.e = Emojis(bot)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            embed = discord.Embed(
                title=f"{self.e.error} Unauthorized",
                description="> Only the command author can confirm this action.",
                color=ERROR_COLOR
            )
            await interaction.response.send_message(embed=embed)
            return False
        return True

    @discord.ui.button(label="Confirm Restart", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        public_embed = discord.Embed(
            title=f"{self.e.down} Bot Restarting",
            description="> The bot is restarting...\n> Please wait.",
            color=WARNING_COLOR
        )
        public_message = await interaction.channel.send(embed=public_embed)
        RESTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RESTART_FILE, "w") as f:
            json.dump({
                "channel_id": interaction.channel.id,
                "message_id": public_message.id
            }, f)
        await interaction.response.defer()
        await interaction.delete_original_response()
        await asyncio.sleep(1)
        await self.bot.close()
        sys.exit(0)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=f"{self.e.error} Restart Cancelled",
            description="> The bot restart has been cancelled.",
            color=ERROR_COLOR
        )
        await interaction.response.edit_message(embed=embed, view=None)


# ===============================
# Admin Cog
# ===============================

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        self.process = psutil.Process(os.getpid())
        self.process.cpu_percent()  # Prime the first reading so it never returns 0.0

    # ===============================
    # /uptime
    # ===============================

    @app_commands.command(name="uptime", description="View how long the bot has been online.")
    async def uptime(self, interaction: discord.Interaction):

        delta = datetime.datetime.utcnow() - self.bot.launch_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        embed = discord.Embed(
            title=f"{self.e.uptime} Bot Uptime",
            description=(
                f"> **Days:** `{days}`\n"
                f"> **Hours:** `{hours}`\n"
                f"> **Minutes:** `{minutes}`\n"
                f"> **Seconds:** `{seconds}`"
            ),
            color=EMBED_COLOR
        )

        await interaction.response.send_message(embed=embed)

    # ===============================
    # /status
    # ===============================

    @app_commands.command(name="status", description="View detailed bot resource usage.")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Run the blocking cpu_percent(interval=1) in a thread so it doesn't
        # block the event loop, while still measuring over a real 1-second window
        loop = asyncio.get_event_loop()
        raw_cpu = await loop.run_in_executor(
            None, lambda: self.process.cpu_percent(interval=1)
        )
        cpu_usage = raw_cpu / psutil.cpu_count()  # Normalize to total system CPU %

        # RAM usage calculation
        mem_info = self.process.memory_info()
        ram_used_mb = mem_info.rss / (1024 ** 2)

        # Try to fetch the container's memory limit
        ram_limit = os.getenv("SERVER_MEMORY", "Unknown")

        # Calculate the size of the bot's current directory for disk usage
        def get_dir_size(path='.'):
            total = 0
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat().st_size
                        elif entry.is_dir(follow_symlinks=False):
                            total += get_dir_size(entry.path)
            except PermissionError:
                pass
            return total

        # Disk usage calculation
        disk_used_mb = get_dir_size() / (1024 ** 2)

        # --- SET YOUR PLAN'S STORAGE LIMIT HERE ---
        PLAN_DISK_LIMIT_MB = 1024

        # Try to get the limit from the host, fallback to manual limit
        disk_limit = os.getenv("SERVER_DISK", PLAN_DISK_LIMIT_MB)

        latency = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title=f"{self.e.uptime} Bot System Status",
            color=EMBED_COLOR,
            timestamp=datetime.datetime.utcnow()
        )

        embed.description = (
            f"> **Bot CPU Usage:** `{cpu_usage:.2f}%`\n"
            f"> **Bot RAM Usage:** `{ram_used_mb:.2f} MB / {ram_limit} MB`\n"
            f"> **Storage Used:** `{disk_used_mb:.2f} MB / {disk_limit} MB`\n"
            f"> **Bot Latency:** `{latency}ms`"
        )

        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed)

    # ===============================
    # /botinfo
    # ===============================

    @app_commands.command(name="botinfo", description="View information about the bot.")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count for g in self.bot.guilds)
        uptime = datetime.datetime.utcnow() - self.bot.launch_time

        embed = discord.Embed(
            title=f"{self.e.uptime} Bot Information",
            color=EMBED_COLOR,
            timestamp=datetime.datetime.utcnow()
        )

        embed.description = (
            f"> **Bot Name:** `{self.bot.user}`\n"
            f"> **Servers:** `{guild_count}`\n"
            f"> **Users:** `{user_count}`\n"
            f"> **Python Version:** `{platform.python_version()}`\n"
            f"> **discord.py Version:** `{discord.__version__}`\n"
            f"> **Uptime:** `{str(uptime).split('.')[0]}`"
        )

        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed)

    # ===============================
    # /logs (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="logs", description="View the latest bot logs.")
    @app_commands.describe(lines="Number of lines to display (default: 20)")
    async def logs(self, interaction: discord.Interaction, lines: int = 20):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can view logs.",
                color=ERROR_COLOR
            )
            return await interaction.response.send_message(embed=embed)

        await interaction.response.defer()

        if not LOG_FILE.exists():
            embed = discord.Embed(
                title=f"{self.e.fail} Log File Not Found",
                description="> The file `logs/bot.log` does not exist.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.readlines()

        last_lines = "".join(content[-lines:])
        if len(last_lines) > 1900:
            last_lines = last_lines[-1900:]

        embed = discord.Embed(
            title=f"{self.e.logs} Latest Bot Logs",
            description=f"```{last_lines}```",
            color=EMBED_COLOR
        )

        await interaction.followup.send(embed=embed)

    # ===============================
    # /sync (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="sync", description="Sync application commands.")
    @app_commands.describe(guild="Whether to sync only for this server (default: False)")
    async def sync(self, interaction: discord.Interaction, guild: bool = False):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can sync commands.",
                color=ERROR_COLOR
            )
            return await interaction.response.send_message(embed=embed)

        await interaction.response.defer()

        if guild:
            synced = await self.bot.tree.sync(guild=interaction.guild)
            scope = "This Server Only"
        else:
            synced = await self.bot.tree.sync()
            scope = "Global"

        embed = discord.Embed(
            title=f"{self.e.success} Command Sync Complete",
            description=(
                f"> **Scope:** `{scope}`\n"
                f"> **Commands Synced:** `{len(synced)}`"
            ),
            color=SUCCESS_COLOR
        )

        await interaction.followup.send(embed=embed)

    # ===============================
    # /restart (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="restart", description="Restart the bot safely.")
    async def restart(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can restart the bot.",
                color=ERROR_COLOR
            )
            return await interaction.response.send_message(embed=embed)

        embed = discord.Embed(
            title=f"{self.e.down} Confirm Bot Restart",
            description="> Are you sure you want to restart the bot?\n> This will temporarily disconnect it.",
            color=WARNING_COLOR
        )

        view = RestartView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    # ===============================
    # /reload (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="reload", description="Reload a cog without restarting the bot.")
    @app_commands.describe(cog="The name of the cog to reload (without .py extension)")
    async def reload_cog(self, interaction: discord.Interaction, cog: str):

        await interaction.response.defer()

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can reload cogs.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Validate cog name
        if not cog or cog.startswith('.') or cog.endswith('.'):
            embed = discord.Embed(
                title="Invalid Cog Name",
                description="> Please provide a valid cog name without file extensions.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Check if cog exists in loaded cogs
        cog_name = f"cogs.{cog}"
        if cog_name not in self.bot.extensions:
            embed = discord.Embed(
                title="Cog Not Loaded",
                description=f"> The cog `{cog}` is not currently loaded.\n> Use `/load` to load it first.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        try:
            await self.bot.reload_extension(cog_name)

            embed = discord.Embed(
                title=f"{self.e.success} Cog Reloaded Successfully",
                description=f"> **Cog:** `{cog}`\n> **Status:** Reloaded without restart",
                color=SUCCESS_COLOR
            )

        except Exception as e:
            embed = discord.Embed(
                title=f"{self.e.fail} Reload Failed",
                description=f"> **Cog:** `{cog}`\n> **Error:** {str(e)}",
                color=ERROR_COLOR
            )

        await interaction.followup.send(embed=embed)

    # ===============================
    # /load (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="load", description="Load a cog that is not currently loaded.")
    @app_commands.describe(cog="The name of the cog to load (without .py extension)")
    async def load_cog(self, interaction: discord.Interaction, cog: str):

        await interaction.response.defer()

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can load cogs.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Validate cog name
        if not cog or cog.startswith('.') or cog.endswith('.'):
            embed = discord.Embed(
                title="Invalid Cog Name",
                description="> Please provide a valid cog name without file extensions.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Check if cog is already loaded
        cog_name = f"cogs.{cog}"
        if cog_name in self.bot.extensions:
            embed = discord.Embed(
                title="Cog Already Loaded",
                description=f"> The cog `{cog}` is already loaded.\n> Use `/reload` to reload it.",
                color=WARNING_COLOR
            )
            return await interaction.followup.send(embed=embed)

        try:
            await self.bot.load_extension(cog_name)

            embed = discord.Embed(
                title=f"{self.e.success} Cog Loaded Successfully",
                description=f"> **Cog:** `{cog}`\n> **Status:** Loaded and ready",
                color=SUCCESS_COLOR
            )

        except Exception as e:
            embed = discord.Embed(
                title=f"{self.e.fail} Load Failed",
                description=f"> **Cog:** `{cog}`\n> **Error:** {str(e)}",
                color=ERROR_COLOR
            )

        await interaction.followup.send(embed=embed)

    # ===============================
    # /unload (ADMIN ONLY)
    # ===============================

    @app_commands.command(name="unload", description="Unload a cog without restarting the bot.")
    @app_commands.describe(cog="The name of the cog to unload (without .py extension)")
    async def unload_cog(self, interaction: discord.Interaction, cog: str):

        await interaction.response.defer()

        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title=f"{self.e.fail} Permission Denied",
                description="> Only Administrators can unload cogs.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Validate cog name
        if not cog or cog.startswith('.') or cog.endswith('.'):
            embed = discord.Embed(
                title=f"{self.e.fail} Invalid Cog Name",
                description="> Please provide a valid cog name without file extensions.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Prevent unloading the admin cog
        if cog.lower() == "bot_info":
            embed = discord.Embed(
                title=f"{self.e.fail} Cannot Unload Admin Cog",
                description="> The admin cog cannot be unloaded for security reasons.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        # Check if cog exists in loaded cogs
        cog_name = f"cogs.{cog}"
        if cog_name not in self.bot.extensions:
            embed = discord.Embed(
                title=f"{self.e.fail} Cog Not Loaded",
                description=f"> The cog `{cog}` is not currently loaded.",
                color=ERROR_COLOR
            )
            return await interaction.followup.send(embed=embed)

        try:
            await self.bot.unload_extension(cog_name)

            embed = discord.Embed(
                title=f"{self.e.success} Cog Unloaded Successfully",
                description=f"> **Cog:** `{cog}`\n> **Status:** Unloaded",
                color=SUCCESS_COLOR
            )

        except Exception as e:
            embed = discord.Embed(
                title=f"{self.e.fail} Unload Failed",
                description=f"> **Cog:** `{cog}`\n> **Error:** {str(e)}",
                color=ERROR_COLOR
            )

        await interaction.followup.send(embed=embed)


# ===============================
# Setup + Restart Message Editor
# ===============================

async def setup(bot: commands.Bot):

    if not hasattr(bot, "launch_time"):
        bot.launch_time = datetime.datetime.utcnow()

    await bot.add_cog(Admin(bot))

    if RESTART_FILE.exists():
        try:
            with open(RESTART_FILE, "r") as f:
                data = json.load(f)

            channel = await bot.fetch_channel(data["channel_id"])
            message = await channel.fetch_message(data["message_id"])

            embed = discord.Embed(
                title=f"{self.e.uptime} Bot Back Online",
                description="> The bot has successfully restarted and is now online.",
                color=SUCCESS_COLOR
            )

            await message.edit(embed=embed)
            RESTART_FILE.unlink()

        except Exception as e:
            print("Restart edit failed:", e)