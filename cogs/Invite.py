import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
import json
import os
import time
from datetime import datetime
from typing import List

DATA_PATH = "data/invite.json"
EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
V2_COLOR = 0x000000
FAKE_THRESHOLD = 60

MEDAL = {
    1: "<a:gold:1494064565531443351>",
    2: "<a:silver:1494064563086299347>",
    3: "<a:bronze:1494064564604633293>"
}


# =========================
# DATA SYSTEM
# =========================

class InviteData:
    def __init__(self, path: str):
        self.path = path
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump({}, f)

    def load(self):
        with open(self.path, "r") as f:
            return json.load(f)

    def save(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=4)


# =========================
# EMBED BUILDER
# =========================

def base_embed(title: str, description: str = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=EMBED_COLOR,
        timestamp=datetime.utcnow()
    )
    return embed

def set_footer(embed: discord.Embed, requester: discord.Member, page: int = None, total: int = None):
    page_str = f"  ·  Page {page}/{total}" if page is not None else ""
    embed.set_footer(
        text=f"Requested by {requester.display_name}{page_str}",
        icon_url=requester.display_avatar.url
    )


# =========================
# PAGINATION VIEW (V2)
# =========================

class BasePagination(discord.ui.LayoutView):
    def __init__(self, pages: List[str], requester: discord.Member, title: str):
        super().__init__(timeout=60)
        self.pages = pages
        self.index = 0
        self.requester = requester
        self.title = title
        self.refresh_layout()

    def refresh_layout(self):
        self.clear_items()
        
        # Build Text Content using V2 Markdown style
        header = f"## {self.title}\n"
        body = f"{self.pages[self.index]}\n\n"
        footer = f"-# Requested by {self.requester.display_name}  ·  Page {self.index + 1}/{len(self.pages)}"
        
        text_element = discord.ui.TextDisplay(header + body + footer)

        # Build Navigation Row
        nav_row = discord.ui.ActionRow()

        prev_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="left", id=1494484350861971548),
            disabled=self.index == 0,
            custom_id=f"invite_prev_{self.requester.id}_{self.index}"
        )
        prev_btn.callback = self.go_prev

        next_btn = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=discord.PartialEmoji(name="right", id=1494484544693469235),
            disabled=self.index >= len(self.pages) - 1,
            custom_id=f"invite_next_{self.requester.id}_{self.index}"
        )
        next_btn.callback = self.go_next

        nav_row.add_item(prev_btn)
        nav_row.add_item(next_btn)

        # Assemble Container
        container = discord.ui.Container(
            text_element,
            nav_row,
            accent_color=V2_COLOR
        )
        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester.id:
            await interaction.response.send_message(
                f"{self.e.fail} Only the requester can navigate this.",
                ephemeral=True
            )
            return False
        return True

    async def go_prev(self, interaction: discord.Interaction):
        self.index -= 1
        self.refresh_layout()
        await interaction.response.edit_message(view=self)

    async def go_next(self, interaction: discord.Interaction):
        self.index += 1
        self.refresh_layout()
        await interaction.response.edit_message(view=self)


# =========================
# COG
# =========================

class InviteTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        self.data = InviteData(DATA_PATH)
        self.invite_cache = {}

    # -------------------------
    # REAL-TIME CACHE
    # -------------------------

    async def refresh_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {i.code: i.uses for i in invites}
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.refresh_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.refresh_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        await self.refresh_invites(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        await self.refresh_invites(invite.guild)

    # -------------------------
    # MEMBER JOIN
    # -------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild

        try:
            invites = await guild.invites()
        except Exception:
            return

        old_cache = self.invite_cache.get(guild.id, {})
        used_invite = None

        for invite in invites:
            if invite.code in old_cache and invite.uses > old_cache[invite.code]:
                used_invite = invite
                break

        self.invite_cache[guild.id] = {i.code: i.uses for i in invites}

        if not used_invite or not used_invite.inviter:
            return

        data = self.data.load()
        guild_data = data.setdefault(str(guild.id), {"users": {}, "joins": {}})
        inviter_id = str(used_invite.inviter.id)

        inviter_stats = guild_data["users"].setdefault(inviter_id, {
            "invites": 0,
            "left": 0,
            "fake": 0
        })
        inviter_stats["invites"] += 1

        guild_data["joins"][str(member.id)] = {
            "inviter": inviter_id,
            "joined_at": time.time(),
            "code": used_invite.code
        }

        self.data.save(data)

    # -------------------------
    # MEMBER LEAVE
    # -------------------------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        data = self.data.load()
        guild_data = data.get(str(member.guild.id))
        if not guild_data:
            return

        join_info = guild_data["joins"].get(str(member.id))
        if not join_info:
            return

        inviter_id = join_info["inviter"]
        joined_at = join_info["joined_at"]
        inviter_stats = guild_data["users"].get(inviter_id)
        if not inviter_stats:
            return

        time_spent = time.time() - joined_at

        if time_spent <= FAKE_THRESHOLD:
            inviter_stats["fake"] += 1
        else:
            inviter_stats["left"] += 1
            inviter_stats["invites"] = max(inviter_stats["invites"] - 1, 0)

        self.data.save(data)

    # =========================
    # COMMANDS
    # =========================

    @app_commands.command(name="invites", description="View invite statistics for a member")
    @app_commands.describe(member="The member to view invite statistics for (defaults to yourself)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        data = self.data.load()
        guild_data = data.get(str(interaction.guild.id), {"users": {}})
        stats = guild_data["users"].get(str(member.id), {
            "invites": 0,
            "left": 0,
            "fake": 0
        })

        invites = stats["invites"]
        left    = stats["left"]
        fake    = stats["fake"]
        net     = invites - left - fake

        content = (
            f"> **Active:** `{invites}`\n"
            f"> **Left:** `{left}`\n"
            f"> **Fake:** `{fake}`\n"
            f"> **Net Invites:** `{net:+d}`\n\n"
            f"-# Requested by {interaction.user.display_name}"
        )

        view = discord.ui.LayoutView()
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## Invite Stats  ·  {member.display_name}\n{content}"),
            accent_color=V2_COLOR
        )
        view.add_item(container)
        await interaction.response.send_message(view=view)

    @app_commands.command(name="invitelist", description="View who a member has invited")
    @app_commands.describe(
        member="The member to look up (defaults to you)",
        link="Filter by a specific invite code"
    )
    async def invitelist(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
        link: str = None
    ):
        member = member or interaction.user

        data = self.data.load()
        guild_data = data.get(str(interaction.guild.id), {"joins": {}})

        invited_ids = [
            uid for uid, info in guild_data.get("joins", {}).items()
            if info.get("inviter") == str(member.id)
            and (link is None or info.get("code") == link)
        ]

        if not invited_ids:
            desc = (
                f"No invites found for {member.mention} using code `{link}`."
                if link else
                f"{member.mention} hasn't invited anyone recorded in this server."
            )
            view = discord.ui.LayoutView()
            view.add_item(discord.ui.Container(
                discord.ui.TextDisplay(f"## No Invites Found\n{desc}"),
                accent_color=V2_COLOR
            ))
            await interaction.response.send_message(view=view, ephemeral=True)
            return

        lines = []
        for i, uid in enumerate(invited_ids, 1):
            invited_member = interaction.guild.get_member(int(uid))
            join_info = guild_data["joins"].get(uid, {})
            code = join_info.get("code", "unknown")
            name = invited_member.mention if invited_member else f"*Unknown User* `{uid}`"
            lines.append(f"`{i:02}.` {name}  ·  code: `{code}`")

        title = f"Invite List  ·  {member.display_name}"
        if link:
            title += f"  ·  {link}"

        pages = ["\n".join(lines[i:i + 10]) for i in range(0, len(lines), 10)]
        view = BasePagination(pages, interaction.user, title)
        await interaction.response.send_message(view=view)

    @app_commands.command(name="lbinvites", description="View the invite leaderboard")
    async def lbinvites(self, interaction: discord.Interaction):
        data = self.data.load()
        guild_data = data.get(str(interaction.guild.id))

        if not guild_data or not guild_data.get("users"):
            view = discord.ui.LayoutView()
            view.add_item(discord.ui.Container(
                discord.ui.TextDisplay("## No Data Yet\nNo invite data recorded."),
                accent_color=V2_COLOR
            ))
            await interaction.response.send_message(view=view, ephemeral=True)
            return

        sorted_users = sorted(
            guild_data["users"].items(),
            key=lambda x: x[1].get("invites", 0),
            reverse=True
        )

        lines = []
        for rank, (user_id, stats) in enumerate(sorted_users, 1):
            member = interaction.guild.get_member(int(user_id))
            name   = member.display_name if member else f"Unknown `{user_id}`"
            medal  = MEDAL.get(rank, f"`#{rank:02}`")

            invites = stats.get("invites", 0)
            left    = stats.get("left", 0)
            fake    = stats.get("fake", 0)

            lines.append(
                f"{medal}  **{name}**\n"
                f"　　`{invites}` invites  ·  `{left}` left  ·  `{fake}` fake"
            )

        pages = ["\n\n".join(lines[i:i + 5]) for i in range(0, len(lines), 5)]

        view = BasePagination(pages, interaction.user, "Invite Leaderboard")
        await interaction.response.send_message(view=view)

    @app_commands.command(name="invitecodes", description="View all active invite codes for a member")
    @app_commands.describe(member="The member to look up (defaults to you)")
    async def invitecodes(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user

        try:
            guild_invites = await interaction.guild.invites()
        except discord.Forbidden:
            return await interaction.response.send_message("Missing Permissions to view invites.", ephemeral=True)

        user_invites = [i for i in guild_invites if i.inviter and i.inviter.id == member.id]

        if not user_invites:
            return await interaction.response.send_message(f"{member.mention} has no active invite codes.", ephemeral=True)

        lines = []
        for i, invite in enumerate(user_invites, 1):
            uses     = invite.uses or 0
            max_uses = str(invite.max_uses) if invite.max_uses else "∞"
            expires  = f"<t:{int(invite.expires_at.timestamp())}:R>" if invite.expires_at else "Never"
            channel  = f"<#{invite.channel.id}>" if invite.channel else "Unknown"
            lines.append(
                f"`{i:02}.` `{invite.code}`  ·  {channel}\n"
                f"　　`{uses}` / `{max_uses}` uses  ·  Expires: {expires}"
            )

        pages = ["\n\n".join(lines[i:i + 8]) for i in range(0, len(lines), 8)]
        view = BasePagination(pages, interaction.user, f"Invite Codes  ·  {member.display_name}")
        await interaction.response.send_message(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteTracker(bot))