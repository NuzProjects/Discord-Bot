import discord
from utils.emojis import Emojis
from discord.ext import commands

# ===============================
# CONFIGURATION
# ===============================

# Set this to the ID of the role you want boosters to receive
BOOSTER_ROLE_ID = 123456789012345678  # <-- Replace with your role ID

EMBED_COLOR = discord.Color.from_rgb(252, 252, 55)
ERROR_COLOR = discord.Color.red()
SUCCESS_COLOR = discord.Color.from_rgb(40, 167, 69)
WARNING_COLOR = discord.Color.from_rgb(255, 193, 7)


# ===============================
# Booster Roles Cog
# ===============================

class BoosterRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Detect boost status changes by comparing premium_since
        was_boosting = before.premium_since is not None
        is_boosting = after.premium_since is not None

        # No change in boost status — nothing to do
        if was_boosting == is_boosting:
            return

        role = after.guild.get_role(BOOSTER_ROLE_ID)
        if role is None:
            print(f"[BoosterRoles] Role ID {BOOSTER_ROLE_ID} not found in guild '{after.guild.name}'.")
            return

        # ── Member just started boosting ──
        if not was_boosting and is_boosting:
            try:
                await after.add_roles(role, reason="Member started boosting the server.")
            except discord.Forbidden:
                print(f"[BoosterRoles] Missing permissions to add role to {after}.")
                return
            except discord.HTTPException as e:
                print(f"[BoosterRoles] Failed to add role to {after}: {e}")
                return

            # Send to the server's system channel
            channel_embed = discord.Embed(
                title=f"{self.e.booster} New Booster!",
                description=(
                    f'**{member} just boosted the server!**\n'
                    f'> Total Boost: {boost_count}\n'
                    f'> Current Level: {guild.premium_tier}'
                ),
                color=EMBED_COLOR
            )
            channel_embed.set_footer(text=after.guild.name)

            channel = after.guild.system_channel
            if channel is not None:
                try:
                    await channel.send(embed=channel_embed)
                except discord.Forbidden:
                    print(f"[BoosterRoles] Missing permissions to send in #{channel.name}.")

            # DM the member
            dm_embed = discord.Embed(
                title="{self.e.booster} Thank You for Boosting!",
                description=(
                    f"> You've been given the **{role.name}** role in **{after.guild.name}** "
                    f"as a thank-you for boosting!\n"
                    f"> We really appreciate your support."
                ),
                color=EMBED_COLOR
            )
            dm_embed.set_footer(text=after.guild.name)

            try:
                await after.send(embed=dm_embed)
            except discord.Forbidden:
                pass

        # ── Member stopped boosting ──
        elif was_boosting and not is_boosting:
            if role in after.roles:
                try:
                    await after.remove_roles(role, reason="Member stopped boosting the server.")
                except discord.Forbidden:
                    print(f"[BoosterRoles] Missing permissions to remove role from {after}.")
                    return
                except discord.HTTPException as e:
                    print(f"[BoosterRoles] Failed to remove role from {after}: {e}")
                    return

            embed = discord.Embed(
                title="Booster Role Removed",
                description=(
                    f"> Your **{role.name}** role in **{after.guild.name}** has been removed "
                    f"because your boost has ended.\n"
                    f"> Boost again any time to get it back!"
                ),
                color=WARNING_COLOR
            )
            embed.set_footer(text=after.guild.name)

            try:
                await after.send(embed=embed)
            except discord.Forbidden:
                pass


# ===============================
# Setup
# ===============================

async def setup(bot: commands.Bot):
    await bot.add_cog(BoosterRoles(bot))