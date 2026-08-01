import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import asyncio
from datetime import datetime, timedelta, timezone

DATA_PATH = "data/giveaways.json"

EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)


class GiveawayData:

    def __init__(self, path):
        self.path = path

        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({}, f)

    def load(self):
        with open(self.path) as f:
            return json.load(f)

    def save(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=4)


class LeaveConfirmView(discord.ui.View):

    def __init__(self, gid, cog, parent):
        super().__init__(timeout=60)
        self.gid = gid
        self.cog = cog
        self.parent = parent

    @discord.ui.button(label="Leave Giveaway", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):

        data = self.cog.data.load()
        giveaway = data.get(self.gid)

        if not giveaway:
            await interaction.response.edit_message(
                embed=discord.Embed(description="Giveaway not found.", color=EMBED_COLOR),
                view=None
            )
            return

        if interaction.user.id in giveaway["entries"]:
            giveaway["entries"].remove(interaction.user.id)

        self.cog.data.save(data)

        self.parent.update_counter()

        # Fetch and update the original giveaway message directly
        try:
            guild = interaction.guild
            channel = guild.get_channel(giveaway["channel"])
            if channel:
                original_msg = await channel.fetch_message(giveaway["message"])
                bonus_role = None
                if giveaway.get("bonus_role"):
                    bonus_role = guild.get_role(giveaway["bonus_role"])
                updated_embed = self.cog.build_embed(
                    title=giveaway.get("title", "Giveaway"),
                    body=giveaway.get("body", ""),
                    gid=self.gid,
                    end_ts=int(giveaway.get("end", 0)),
                    winners=giveaway.get("winners", 1),
                    entries=giveaway.get("entries", []),
                    bonus_role=bonus_role
                )
                await original_msg.edit(embed=updated_embed, view=self.parent)
        except (discord.NotFound, discord.HTTPException):
            pass

        embed = discord.Embed(
            title="Giveaway Left",
            description="You have been removed from the giveaway.",
            color=EMBED_COLOR
        )

        await interaction.response.edit_message(embed=embed, view=None)


class ParticipantsPaginator(discord.ui.View):

    def __init__(self, entries, bonus_role, guild):
        super().__init__(timeout=120)

        self.entries = entries
        self.guild = guild
        self.bonus_role = bonus_role
        self.page = 0
        self.pages = []

        chunk = []

        for uid in entries:

            member = guild.get_member(uid)

            if not member:
                continue

            count = 1

            if bonus_role and bonus_role in [r.id for r in member.roles]:
                count += 1

            chunk.append(f"{member.display_name} — {count} {'entry' if count == 1 else 'entries'}")

            if len(chunk) == 10:
                self.pages.append(chunk)
                chunk = []

        if chunk:
            self.pages.append(chunk)

        if len(self.pages) <= 1:
            for child in self.children:
                child.disabled = True

    def get_embed(self):

        content = "\n".join(self.pages[self.page]) if self.pages else "No participants found."

        embed = discord.Embed(
            title="Participants",
            description=content,
            color=EMBED_COLOR
        )

        if self.pages:
            embed.set_footer(text=f"Page {self.page + 1}/{len(self.pages)}")

        return embed

    @discord.ui.button(emoji="<:left:1494484350861971548>", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.page > 0:
            self.page -= 1

        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(emoji="<:right:1494484544693469235>", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):

        if self.page < len(self.pages) - 1:
            self.page += 1

        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class GiveawayView(discord.ui.View):

    def __init__(self, gid, cog):
        # timeout=None is required for persistence across restarts
        super().__init__(timeout=None)
        self.gid = gid
        self.cog = cog

        data = cog.data.load()
        giveaway = data.get(gid, {})
        count = len(giveaway.get("entries", []))
        ended = giveaway.get("ended", False)

        self.enter_button = discord.ui.Button(
            emoji="<a:giveaway:1494059431745556580>",
            label=f"{count}",
            style=discord.ButtonStyle.primary,
            custom_id=f"giveaway_enter:{gid}",
            disabled=ended
        )
        self.enter_button.callback = self.enter_callback

        self.participants_button = discord.ui.Button(
            label="Participants",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway_participants:{gid}"
        )
        self.participants_button.callback = self.participants_callback

        self.add_item(self.enter_button)
        self.add_item(self.participants_button)

    def update_counter(self):

        data = self.cog.data.load()
        giveaway = data.get(self.gid, {})
        count = len(giveaway.get("entries", []))
        self.enter_button.emoji = "<a:giveaway:1494059431745556580>"
        self.enter_button.label = str(count)

    def disable_buttons(self):
        self.enter_button.disabled = True
        self.participants_button.disabled = True

    async def refresh_message(self, interaction: discord.Interaction):
        if not interaction.message:
            return

        data = self.cog.data.load()
        giveaway = data.get(self.gid, {})

        guild = interaction.guild
        bonus_role = None
        if giveaway.get("bonus_role"):
            bonus_role = guild.get_role(giveaway["bonus_role"])

        embed = self.cog.build_embed(
            title=giveaway.get("title", "<a:giveaway:1494059431745556580> Giveaway"),
            body=giveaway.get("body", ""),
            gid=self.gid,
            end_ts=int(giveaway.get("end", 0)),
            winners=giveaway.get("winners", 1),
            entries=giveaway.get("entries", []),
            bonus_role=bonus_role
        )

        await interaction.message.edit(embed=embed, view=self)

    async def enter_callback(self, interaction: discord.Interaction):

        data = self.cog.data.load()
        giveaway = data.get(self.gid)

        # Guard: giveaway missing entirely (data wiped, etc.)
        if not giveaway:
            await interaction.response.send_message(
                embed=discord.Embed(description="This giveaway no longer exists.", color=EMBED_COLOR),
                ephemeral=True
            )
            return

        # Guard: giveaway ended — disable the button and inform the user
        if giveaway["ended"]:
            self.disable_buttons()
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(
                embed=discord.Embed(description="This giveaway has already ended.", color=EMBED_COLOR),
                ephemeral=True
            )
            return

        if interaction.user.id in giveaway["entries"]:

            embed = discord.Embed(
                title="<a:giveaway:1494059431745556580> Already Entered",
                description="You're already in this giveaway!\nClick below if you'd like to leave.",
                color=EMBED_COLOR
            )

            await interaction.response.send_message(
                embed=embed,
                view=LeaveConfirmView(self.gid, self.cog, self),
                ephemeral=True
            )
            return

        giveaway["entries"].append(interaction.user.id)
        self.cog.data.save(data)

        self.update_counter()

        await interaction.response.edit_message(view=self)

        # Rebuild the embed so the Participants count ticks up
        guild = interaction.guild
        bonus_role = None
        if giveaway.get("bonus_role"):
            bonus_role = guild.get_role(giveaway["bonus_role"])

        new_embed = self.cog.build_embed(
            title=giveaway.get("title", "Giveaway"),
            body=giveaway.get("body", ""),
            gid=self.gid,
            end_ts=int(giveaway.get("end", 0)),
            winners=giveaway.get("winners", 1),
            entries=giveaway.get("entries", []),
            bonus_role=bonus_role
        )

        await interaction.message.edit(embed=new_embed, view=self)

        embed = discord.Embed(
            title="You're In! <a:giveaway:1494059431745556580>",
            description="You've successfully entered the giveaway. Good luck!",
            color=EMBED_COLOR
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def participants_callback(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        data = self.cog.data.load()
        giveaway = data.get(self.gid)

        if not giveaway:
            await interaction.followup.send(
                embed=discord.Embed(description="This giveaway no longer exists.", color=EMBED_COLOR),
                ephemeral=True
            )
            return

        if not giveaway["entries"]:
            embed = discord.Embed(
                description="No participants yet.",
                color=EMBED_COLOR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        view = ParticipantsPaginator(
            giveaway["entries"],
            giveaway["bonus_role"],
            interaction.guild
        )

        await interaction.followup.send(
            embed=view.get_embed(),
            view=view,
            ephemeral=True
        )


class Giveaways(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.e = Emojis(bot)
        self.data = GiveawayData(DATA_PATH)

    async def cog_load(self):

        data = self.data.load()

        for gid, giveaway in data.items():

            if giveaway["ended"]:
                continue

            # Re-register every active view so its custom_ids are live after restart.
            # This is what prevents "Application did not respond" on old buttons.
            self.bot.add_view(GiveawayView(gid, self))

            # Re-schedule the end task — if the end time already passed while the
            # bot was offline, wait_end will call end_giveaway immediately.
            asyncio.create_task(self.wait_end(gid))

    async def admin_guard(self, interaction):

        if not interaction.user.guild_permissions.administrator:

            embed = discord.Embed(
                title=f"{self.e.error} Permission Denied",
                description="You do not have permission to use this command.",
                color=EMBED_COLOR
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        return True

    def parse_time(self, t):

        unit = t[-1].lower()
        amount = int(t[:-1])

        if unit == "s":
            return timedelta(seconds=amount)
        if unit == "m":
            return timedelta(minutes=amount)
        if unit == "h":
            return timedelta(hours=amount)
        if unit == "d":
            return timedelta(days=amount)
        return timedelta(minutes=amount)

    def build_embed(self, title: str, body: str, gid: str, end_ts: int, winners: int, entries: list, bonus_role: discord.Role = None) -> discord.Embed:
        """Build (or rebuild) the live giveaway embed from current data."""

        lines = []

        # Body lines
        for line in body.split("\n"):
            if line.strip():
                lines.append(f"> {line}")

        lines.append("")
        lines.append(f"> Ends: <t:{end_ts}:R>")
        lines.append(f"> Winners: {winners}")
        lines.append("")
        lines.append(f"> Participants: {len(entries)}")

        if bonus_role:
            lines.append(f"**Roles with bonus entries:**")
            lines.append(f"> {bonus_role.mention} • 1 bonus entry")

        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=EMBED_COLOR
        )

        embed.set_footer(text=f"{gid}")

        return embed

    @app_commands.command(name="gstart", description="Start a new giveaway")
    @app_commands.describe(title="The title of the giveaway", body="The description/body of the giveaway", end="Duration until the giveaway ends (e.g., 10m, 2h, 1d)", winners="Number of winners to select", bonus_entries="Optional role that gets bonus entries")
    async def gstart(self, interaction: discord.Interaction, title: str, body: str, end: str, winners: int, bonus_entries: discord.Role = None):

        if not await self.admin_guard(interaction):
            return

        delta = self.parse_time(end)
        end_time = datetime.now(timezone.utc) + delta

        gid = str(int(datetime.now(timezone.utc).timestamp()))

        embed = self.build_embed(
            title=title,
            body=body,
            gid=gid,
            end_ts=int(end_time.timestamp()),
            winners=winners,
            entries=[],
            bonus_role=bonus_entries
        )

        view = GiveawayView(gid, self)

        await interaction.response.defer(ephemeral=True)

        msg = await interaction.channel.send(embed=embed, view=view)

        data = self.data.load()

        data[gid] = {
            "guild": interaction.guild.id,
            "channel": interaction.channel.id,
            "message": msg.id,
            "title": title,
            "body": body,
            "end": end_time.timestamp(),
            "winners": winners,
            "bonus_role": bonus_entries.id if bonus_entries else None,
            "entries": [],
            "ended": False
        }

        self.data.save(data)

        asyncio.create_task(self.wait_end(gid))

        await interaction.followup.send(
            embed=discord.Embed(description=f"{self.e.success} Giveaway started!", color=EMBED_COLOR),
            ephemeral=True
        )

    async def wait_end(self, gid):

        data = self.data.load()
        giveaway = data.get(gid)
        if not giveaway:
            return

        remaining = giveaway["end"] - datetime.now(timezone.utc).timestamp()

        # If giveaway should have already ended, end it immediately
        if remaining <= 0:
            await self.end_giveaway(gid)
            return

        # Sleep with precision handling
        await asyncio.sleep(max(0, remaining))
        
        # Additional check to ensure we're at or past the end time
        while datetime.now(timezone.utc).timestamp() < giveaway["end"]:
            await asyncio.sleep(0.1)
        
        await self.end_giveaway(gid)

    async def end_giveaway(self, gid):

        data = self.data.load()
        giveaway = data.get(gid)

        if not giveaway or giveaway["ended"]:
            return

        giveaway["ended"] = True
        self.data.save(data)

        guild = self.bot.get_guild(giveaway["guild"])
        if not guild:
            return
        channel = guild.get_channel(giveaway["channel"])
        if not channel:
            return

        # ── Disable buttons and update embed on the original giveaway message ──
        try:
            original_msg = await channel.fetch_message(giveaway["message"])
            ended_view = GiveawayView(gid, self)
            ended_view.disable_buttons()

            bonus_role = None
            if giveaway.get("bonus_role"):
                bonus_role = guild.get_role(giveaway["bonus_role"])

            ended_embed = self.build_embed(
                title=giveaway.get("title", "Giveaway") + " — Ended",
                body=giveaway.get("body", ""),
                gid=gid,
                end_ts=int(giveaway.get("end", 0)),
                winners=giveaway.get("winners", 1),
                entries=giveaway.get("entries", []),
                bonus_role=bonus_role
            )

            await original_msg.edit(embed=ended_embed, view=ended_view)
        except (discord.NotFound, discord.HTTPException):
            pass  # Message deleted or inaccessible — not fatal

        entries = giveaway["entries"]
        num_winners = giveaway["winners"]

        if not entries:
            embed = discord.Embed(
                title="<a:giveaway:1494059431745556580> Giveaway Ended",
                description=(
                    "> No one entered this giveaway.\n"
                    "> Better luck next time!"
                ),
                color=EMBED_COLOR
            )
            await channel.send(embed=embed)
            return

        # Apply bonus role weighting: members with the role get 2 tickets
        weighted_pool = []
        bonus_role_id = giveaway.get("bonus_role")

        for uid in entries:
            member = guild.get_member(uid)
            tickets = 1
            if bonus_role_id and member:
                if bonus_role_id in [r.id for r in member.roles]:
                    tickets = 2
            weighted_pool.extend([uid] * tickets)

        # Pick unique winners from the weighted pool
        winners_ids = []
        pool = weighted_pool.copy()

        for _ in range(min(num_winners, len(entries))):
            if not pool:
                break
            pick = random.choice(pool)
            winners_ids.append(pick)
            # Remove all tickets for this winner so they can't win twice
            pool = [uid for uid in pool if uid != pick]

        winner_mentions = " ".join(f"<@{w}>" for w in winners_ids)
        winner_lines = "\n".join(f"> {self.e.trophy} <@{w}>" for w in winners_ids)

        plural = "Winner" if len(winners_ids) == 1 else "Winners"

        embed = discord.Embed(
            title=f"<a:giveaway:1494059431745556580> Giveaway Ended — {plural} Selected!",
            description=(
                f"{winner_lines}\n\n"
                f"> Congratulations! Please open a ticket to claim your reward."
            ),
            color=EMBED_COLOR
        )

        embed.set_footer(text=f"Giveaway ID: {gid} · {len(entries)} total {'entry' if len(entries) == 1 else 'entries'}")

        await channel.send(embed=embed)

    @app_commands.command(name="greroll", description="Reroll a new winner")
    @app_commands.describe(gid="The giveaway ID to reroll")
    async def reroll(self, interaction: discord.Interaction, gid: str):

        if not await self.admin_guard(interaction):
            return

        data = self.data.load()
        giveaway = data.get(gid)

        if not giveaway:

            embed = discord.Embed(
                description="Giveaway not found.",
                color=EMBED_COLOR
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        entries = giveaway["entries"]

        if not entries:

            embed = discord.Embed(
                description="No entries to reroll.",
                color=EMBED_COLOR
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        winner = random.choice(entries)

        embed = discord.Embed(
            title="<a:giveaway:1494059431745556580> Rerolled!",
            description=f"> New Winner: <@{winner}>\n> Please open a ticket to claim your reward.",
            color=EMBED_COLOR
        )

        await interaction.channel.send(content=f"<@{winner}>", embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(
                description="Giveaway rerolled.",
                color=EMBED_COLOR
            ),
            ephemeral=True
        )

        await asyncio.sleep(10)
        await interaction.delete_original_response()

    @app_commands.command(name="gend", description="Manually end a giveaway")
    @app_commands.describe(gid="The giveaway ID to end")
    async def gend(self, interaction: discord.Interaction, gid: str):

        if not await self.admin_guard(interaction):
            return

        data = self.data.load()
        giveaway = data.get(gid)

        if not giveaway:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{self.e.error} Giveaway not found.", color=EMBED_COLOR),
                ephemeral=True
            )
            return

        if giveaway["ended"]:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{self.e.error} This giveaway has already ended.", color=EMBED_COLOR),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self.end_giveaway(gid)

        await interaction.followup.send(
            embed=discord.Embed(description="Giveaway ended.", color=EMBED_COLOR),
            ephemeral=True
        )

        await asyncio.sleep(10)
        await interaction.delete_original_response()


async def setup(bot):
    await bot.add_cog(Giveaways(bot))