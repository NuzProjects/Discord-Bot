import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
from typing import Optional, Literal
from datetime import datetime

# =========================================================
# COLORS
# =========================================================

EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
ERROR_COLOR = discord.Color.red()

# =========================================================
# UTILITIES
# =========================================================

def timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d • %H:%M UTC")


def success_embed(title: str, interaction: discord.Interaction):
    embed = discord.Embed(title=title, color=EMBED_COLOR)
    embed.set_footer(text=f"Requested by {interaction.user} • {timestamp()}")
    return embed


def error_embed(title: str, description: str, interaction: discord.Interaction):
    embed = discord.Embed(
        title=title,
        description=f"> {description}",
        color=ERROR_COLOR
    )
    embed.set_footer(text=f"Requested by {interaction.user} • {timestamp()}")
    return embed


def admin_only():
    async def predicate(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("Administrator permission required.")
        return True
    return app_commands.check(predicate)


def mod_only():
    async def predicate(interaction: discord.Interaction):
        perms = interaction.user.guild_permissions
        if not (perms.manage_roles or perms.manage_nicknames):
            raise app_commands.CheckFailure("Manage Roles or Manage Nicknames permission required.")
        return True
    return app_commands.check(predicate)


# =========================================================
# COG
# =========================================================

class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)

    # =====================================================
    # GLOBAL PERMISSION ERROR HANDLER (PUBLIC)
    # =====================================================

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):

        if isinstance(error, app_commands.CheckFailure):

            embed = error_embed(
                f"{self.e.error} Permission Denied",
                f"{self.e.error} You do not have permission to use this command.\n"
                "> Required: Administrator\n"
                f"> Attempted By: {interaction.user.mention}",
                interaction
            )

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)

            return

        raise error


    # =====================================================
    # ROLE GROUP
    # =====================================================

    role = app_commands.Group(
        name="role",
        description="Commands related to managing and viewing roles."
    )

    @role.command(name="add", description="Assign a role to a member.")
    @app_commands.describe(user="The member to assign the role to", role="The role to assign")
    @admin_only()
    async def role_add(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):

        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role Hierarchy Error",
                    "I cannot assign this role because it is higher than or equal to my highest role.",
                    interaction
                )
            )

        if role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "You cannot assign a role that is higher than or equal to your highest role.",
                    interaction
                )
            )

        if role in user.roles:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role Already Assigned",
                    f"{user.mention} already has the role {role.mention}.",
                    interaction
                )
            )

        await user.add_roles(role, reason=f"Role added by {interaction.user}")

        embed = success_embed("Role Successfully Assigned", interaction)
        embed.description = (
            f"> **Member:** {user.mention}\n"
            f"> **Role Added:** {role.mention}\n"
            f"> **Reason:** Manual role assignment"
        )

        await interaction.response.send_message(embed=embed)

    @role.command(name="remove", description="Remove a role from a member.")
    @app_commands.describe(user="The member to remove the role from", role="The role to remove")
    @admin_only()
    async def role_remove(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role):

        if role not in user.roles:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role Not Found",
                    f"{user.mention} does not currently have the role {role.mention}.",
                    interaction
                )
            )

        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role Hierarchy Error",
                    "I cannot remove this role because it is higher than or equal to my highest role.",
                    interaction
                )
            )

        await user.remove_roles(role, reason=f"Role removed by {interaction.user}")

        embed = success_embed("Role Successfully Removed", interaction)
        embed.description = (
            f"> **Member:** {user.mention}\n"
            f"> **Role Removed:** {role.mention}\n"
            f"> **Reason:** Manual role removal"
        )

        await interaction.response.send_message(embed=embed)

    @role.command(name="info", description="View detailed information about a role.")
    @app_commands.describe(role="The role to view information about")
    async def role_info(self, interaction: discord.Interaction, role: discord.Role):

        embed = success_embed("Role Information", interaction)

        embed.description = (
            f"> **Role Name:** {role.name}\n"
            f"> **Role ID:** {role.id}\n"
            f"> **Member Count:** {len(role.members)}\n"
            f"> **Position:** {role.position}\n"
            f"> **Mentionable:** {'Yes' if role.mentionable else 'No'}\n"
            f"> **Displayed Separately:** {'Yes' if role.hoist else 'No'}\n"
            f"> **Created On:** {role.created_at.strftime('%Y-%m-%d')}"
        )

        if role.icon:
            embed.set_thumbnail(url=role.icon.url)

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # MASS ROLE GROUP
    # =====================================================

    massrole = app_commands.Group(
        name="massrole",
        description="Assign or remove a role from all humans or bots."
    )

    @massrole.command(name="type", description="Add or remove a role from all humans or bots in the server.")
    @app_commands.describe(action="Whether to add or remove the role", target="Apply to humans or bots", role="The role to apply")
    @admin_only()
    async def massrole_type(
        self,
        interaction: discord.Interaction,
        action: Literal["add", "remove"],
        target: Literal["human", "bot"],
        role: discord.Role
    ):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role Hierarchy Error",
                    "I cannot assign or remove this role because it is higher than or equal to my highest role.",
                    interaction
                )
            )

        if role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "You cannot manage a role that is higher than or equal to your highest role.",
                    interaction
                )
            )

        await interaction.response.defer()

        members = [m for m in interaction.guild.members if (m.bot if target == "bot" else not m.bot)]

        success, failed = 0, 0

        for member in members:
            try:
                if action == "add" and role not in member.roles:
                    await member.add_roles(role, reason=f"Mass role by {interaction.user}")
                    success += 1
                elif action == "remove" and role in member.roles:
                    await member.remove_roles(role, reason=f"Mass role by {interaction.user}")
                    success += 1
            except discord.HTTPException:
                failed += 1

        embed = success_embed("Mass Role Complete", interaction)
        embed.description = (
            f"> **Action:** {'Added' if action == 'add' else 'Removed'}\n"
            f"> **Target:** {'Bots' if target == 'bot' else 'Humans'}\n"
            f"> **Role:** {role.mention}\n"
            f"> **Succeeded:** {success}\n"
            f"> **Failed:** {failed}"
        )

        await interaction.followup.send(embed=embed)

    # =====================================================
    # NICKNAME
    # =====================================================

    @app_commands.command(name="nick", description="Change or reset a member's server nickname.")
    @app_commands.describe(user="The member to change the nickname for", nickname="The new nickname (leave empty to reset)")
    async def nick(self, interaction: discord.Interaction, user: discord.Member, nickname: Optional[str] = None):
        if user.id != interaction.user.id:
            perms = interaction.user.guild_permissions
            if not (perms.manage_roles or perms.manage_nicknames):
                raise app_commands.CheckFailure("Manage Roles or Manage Nicknames permission required.")

        if user.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Missing Permissions",
                    "I don't have permission to change this member's nickname.\n> My role is not high enough in the hierarchy.",
                    interaction
                )
            )

        if user.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Missing Permissions",
                    "You don't have permission to change this member's nickname.\n> Your role is not high enough in the hierarchy.",
                    interaction
                )
            )

        previous = user.display_name
        await user.edit(nick=nickname, reason=f"Nickname changed by {interaction.user}")

        embed = success_embed("Nickname Updated", interaction)
        embed.description = (
            f"> **Member:** {user.mention}\n"
            f"> **Previous Nickname:** {previous}\n"
            f"> **New Nickname:** {nickname if nickname else 'Nickname Reset'}"
        )

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # SERVER INFO
    # =====================================================

    @app_commands.command(name="serverinfo", description="View comprehensive information about this server.")
    async def serverinfo(self, interaction: discord.Interaction):

        g = interaction.guild
        embed = success_embed("Server Overview", interaction)

        embed.description = (
            f"> **Server Name:** {g.name}\n"
            f"> **Server ID:** {g.id}\n"
            f"> **Total Members:** {g.member_count}\n"
            f"> **Total Roles:** {len(g.roles)}\n"
            f"> **Total Channels:** {len(g.channels)}\n"
            f"> **Boost Level:** Tier {g.premium_tier} • {g.premium_subscription_count} Boosts\n"
            f"> **Owner:** {g.owner.mention if g.owner else 'Unknown'}\n"
            f"> **Created On:** {g.created_at.strftime('%Y-%m-%d')}"
        )

        if g.icon:
            embed.set_thumbnail(url=g.icon.url)

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # USER INFO
    # =====================================================

    @app_commands.command(name="userinfo", description="View detailed information about a member.")
    @app_commands.describe(user="The member to view information about (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):

        user = user or interaction.user
        roles = [r.mention for r in user.roles[1:]]

        embed = success_embed("Member Information", interaction)
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.description = (
            f"> **Username:** {user}\n"
            f"> **User ID:** {user.id}\n"
            f"> **Account Created:** {user.created_at.strftime('%Y-%m-%d')}\n"
            f"> **Joined Server:** {user.joined_at.strftime('%Y-%m-%d') if user.joined_at else 'Unknown'}\n"
            f"> **Highest Role:** {user.top_role.mention}\n"
            f"> **Assigned Roles ({len(roles)}):** {', '.join(roles[:15]) if roles else 'No additional roles'}"
        )

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # AVATAR
    # =====================================================

    @app_commands.command(name="avatar", description="Display a member's profile picture.")
    @app_commands.describe(user="The member to display the avatar for (defaults to yourself)")
    async def avatar(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):

        user = user or interaction.user
        embed = success_embed("User Avatar", interaction)
        embed.description = f"> Displaying avatar for {user.mention}"
        embed.set_image(url=user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # BANNER
    # =====================================================

    @app_commands.command(name="banner", description="Display a member's profile banner.")
    @app_commands.describe(user="The member to display the banner for (defaults to yourself)")
    async def banner(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):

        user = user or interaction.user
        fetched = await self.bot.fetch_user(user.id)

        if not fetched.banner:
            return await interaction.response.send_message(
                embed=error_embed(
                    "No Banner Found",
                    "This user does not currently have a profile banner set.",
                    interaction
                )
            )

        embed = success_embed("User Banner", interaction)
        embed.description = f"> Displaying banner for {user.mention}"
        embed.set_image(url=fetched.banner.url)

        await interaction.response.send_message(embed=embed)

    # =====================================================
    # PING
    # =====================================================

    @app_commands.command(name="ping", description="Check the bot's connection latency.")
    async def ping(self, interaction: discord.Interaction):
        websocket_latency = round(self.bot.latency * 1000)
        response_latency = max(
            0,
            round((discord.utils.utcnow() - interaction.created_at).total_seconds() * 1000),
        )

        embed = discord.Embed(title=f"{self.e.ping} Pong!", color=discord.Color.blurple())
        embed.description = (
            f"> **WebSocket:** `{websocket_latency} ms`\n"
            f"> **Command response:** `{response_latency} ms`\n"
            "> **Status:** Online"
        )
        embed.set_footer(text=f"Requested by {interaction.user}")

        await interaction.response.send_message(embed=embed)


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
