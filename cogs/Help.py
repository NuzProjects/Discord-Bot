import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from utils.emojis import Emojis

# V2 Settings
DARK_GOLD = 0

def _get_cog_commands(cog: commands.Cog) -> list[str]:
    """
    Collect all slash command lines from a cog.
    """
    lines = []
    for attr in dir(cog.__class__):
        obj = getattr(cog.__class__, attr, None)
        if isinstance(obj, app_commands.Command):
            desc = obj.description or "No description provided."
            lines.append(f"`/{obj.name}` — {desc}")
        elif isinstance(obj, app_commands.Group):
            for subcmd in obj.commands:
                desc = subcmd.description or "No description provided."
                lines.append(f"`/{obj.name} {subcmd.name}` — {desc}")
    
    lines.sort()
    return lines

class HelpViewV2(discord.ui.LayoutView):
    def __init__(self, user_id: int, bot: commands.Bot):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.bot = bot
        self.e = Emojis(bot)
        self.index = 0
        
        # Filter cogs and prepare data
        self.cogs = [c for n, c in bot.cogs.items() if n.lower() != "help"]
        self.total = len(self.cogs) + 1
        
        self.refresh_layout()

    def refresh_layout(self):
        """Rebuilds the UI components for the current page index."""
        self.clear_items()
        
        if self.index == 0:
            title = "Bot Command Directory"
            content = "Advanced management system. Use the buttons below to browse modules."
        else:
            cog = self.cogs[self.index - 1]
            title = f"{cog.qualified_name} Commands"
            cmds = _get_cog_commands(cog)
            content = "\n".join(cmds) if cmds else "No commands found."

        # Components V2 footer style (using -# small text markdown)
        footer = f"-# Requested by {self.user_id} • Page {self.index + 1} of {self.total}"

        # 1. Text Element (Replaces Embed Body)
        text = discord.ui.TextDisplay(f"## {title}\n{content}\n\n{footer}")

        # 2. ActionRow with Custom Emojis
        nav_row = discord.ui.ActionRow()
        
        # Left Button
        btn_back = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji.from_str(self.e.left),
            disabled=self.index == 0,
            custom_id=f"h_prev_{self.index}"
        )
        btn_back.callback = self.go_back

        # Right Button
        btn_next = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji.from_str(self.e.right),
            disabled=self.index == self.total - 1,
            custom_id=f"h_next_{self.index}"
        )
        btn_next.callback = self.go_next
        
        nav_row.add_item(btn_back)
        nav_row.add_item(btn_next)

        # 3. Container (Replaces Embed Frame)
        container = discord.ui.Container(
            text, 
            nav_row, 
            accent_color=DARK_GOLD
        )
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This session is not yours.", ephemeral=True)
            return False
        return True

    async def go_back(self, interaction: discord.Interaction):
        self.index -= 1
        self.refresh_layout()
        await interaction.response.edit_message(view=self)

    async def go_next(self, interaction: discord.Interaction):
        self.index += 1
        self.refresh_layout()
        await interaction.response.edit_message(view=self)

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="View the command directory")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # We pass the bot instance to handle cog logic inside the view
        view = HelpViewV2(interaction.user.id, self.bot)
        
        # We send ONLY the view. Discord API rejects mixed Embed + LayoutView payloads.
        await interaction.followup.send(view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))