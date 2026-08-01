import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
import json
import time
from pathlib import Path

# Define the path for our AFK storage
AFK_FILE = Path("data/afk.json")

class AFK(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        self.afk_data = {}
        self._load_afk_data()

    def _load_afk_data(self):
        """Loads AFK data from the JSON file into memory."""
        AFK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AFK_FILE.exists():
            try:
                with open(AFK_FILE, "r", encoding="utf-8") as f:
                    self.afk_data = json.load(f)
            except json.JSONDecodeError:
                self.afk_data = {}
        else:
            self._save_afk_data()

    def _save_afk_data(self):
        """Saves the current AFK data from memory to the JSON file."""
        with open(AFK_FILE, "w", encoding="utf-8") as f:
            json.dump(self.afk_data, f, indent=4)

    # ===============================
    # /afk Command
    # ===============================
    @app_commands.command(name="afk", description="Set your AFK status. Removes automatically when you chat.")
    @app_commands.describe(message="The reason you are away from the keyboard (optional)")
    @app_commands.checks.cooldown(1, 180, key=lambda i: i.user.id) # 1 use per 3 minutes per user
    async def set_afk(self, interaction: discord.Interaction, message: str = "AFK"):
        user = interaction.user
        user_id = str(user.id)
        current_time = int(time.time())

        # Store the user's data
        self.afk_data[user_id] = {
            "message": message,
            "time": current_time,
            "original_nick": user.display_name
        }
        self._save_afk_data()

        # Handle Nickname Change
        safe_name = user.display_name[:26]
        new_nick = f"AFK | {safe_name}"
        
        nickname_changed = False
        try:
            await user.edit(nick=new_nick)
            nickname_changed = True
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title=f"{self.e.afk} AFK Status Enabled",
            description=(
                f"> You have been marked as Away From Keyboard (AFK).\n"
                f"> **Provided Reason:** `{message}`"
            ),
            color=discord.Color.from_rgb(252, 252, 55)
        )
        
        embed.set_footer(text="Sending a message will automatically remove your AFK status.")

        await interaction.response.send_message(embed=embed)

    # ===============================
    # Error Handler for /afk Cooldowns
    # ===============================
    @set_afk.error
    async def set_afk_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            minutes, seconds = divmod(int(error.retry_after), 60)
            embed = discord.Embed(
                title=f"{self.e.fail} AFK Cooldown",
                description=f"> You are setting your AFK status too frequently.\n> Please wait **{minutes}m {seconds}s** before using this command again.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            print(f"An error occurred in the /afk command: {error}")

    # ===============================
    # /unafk Command (Manual Removal)
    # ===============================
    @app_commands.command(name="unafk", description="Manually remove your AFK status without sending a message.")
    async def remove_afk(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        if user_id not in self.afk_data:
            return await interaction.response.send_message("You are not currently marked as AFK.", ephemeral=True)

        data = self.afk_data.pop(user_id)
        self._save_afk_data()

        # Attempt to revert their nickname
        try:
            if interaction.user.display_name.startswith("AFK | "):
                await interaction.user.edit(nick=data["original_nick"])
        except discord.Forbidden:
            pass
            
        await interaction.response.send_message("Your AFK status has been manually removed.", ephemeral=True)


    # ===============================
    # Message Listener (Auto-Remove & Mentions)
    # ===============================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        user_id = str(message.author.id)

        # 1. Check if the author is returning from AFK
        if user_id in self.afk_data:
            data = self.afk_data.pop(user_id)
            self._save_afk_data()

            # Attempt to revert their nickname
            try:
                if message.author.display_name.startswith("AFK | "):
                    await message.author.edit(nick=data["original_nick"])
            except discord.Forbidden:
                pass

            # Calculate how long they were gone
            time_gone = int(time.time()) - data["time"]
            minutes, seconds = divmod(time_gone, 60)
            hours, minutes = divmod(minutes, 60)
            
            duration_str = ""
            if hours > 0: duration_str += f"{hours} hours, "
            if minutes > 0: duration_str += f"{minutes} minutes, "
            duration_str += f"{seconds} seconds"

            welcome_embed = discord.Embed(
                title=f"{self.e.online} AFK Status Removed",
                description=(
                    f"> **Previous AFK Reason:** `{data['message']}`\n"
                    f"> **Total Time Away:** `{duration_str}`"
                ),
                color=discord.Color.from_rgb(40, 167, 69)
            )
            # Send as a reply only visible to the returning user via a temp message
            try:
                reply = await message.reply(embed=welcome_embed, mention_author=False)
                await reply.delete(delay=8.0)
            except Exception:
                pass

        # 2. Check if the message mentions anyone who is AFK
        if message.mentions:
            for mentioned_user in message.mentions:
                mentioned_id = str(mentioned_user.id)
                if mentioned_id in self.afk_data:
                    afk_info = self.afk_data[mentioned_id]
                    afk_time = afk_info["time"]
                    
                    embed = discord.Embed(
                        title=f"{self.e.afk} User is Currently AFK",
                        description=(
                            f"**{mentioned_user.display_name}** is currently away and may not respond immediately.\n\n"
                            f"> **Reason Provided:** `{afk_info['message']}`\n"
                            f"> **AFK Since:** <t:{afk_time}:f> (<t:{afk_time}:R>)"
                        ),
                        color=discord.Color.from_rgb(255, 193, 7)
                    )
                    await message.channel.send(embed=embed, delete_after=20.0)

async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))