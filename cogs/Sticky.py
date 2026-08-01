import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
import json
import os
import uuid

DATA_FILE = "data/sticky.json"

# ---------- COLORS ---------- #
EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
ERROR_COLOR = discord.Color.red()
SUCCESS_COLOR = discord.Color.from_rgb(40, 167, 69)

# ---------- FILE HANDLING ---------- #

def load_data():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
        return {}

    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def make_embed(title, description, color=EMBED_COLOR):
    return discord.Embed(title=title, description=description, color=color)

def permission_error(interaction: discord.Interaction):
    return make_embed(
        f"{self.e.error} Permission Denied",
        (
            f"{self.e.error} You do not have permission to use this command.\n"
            "> Required: Administrator\n"
            f"> Attempted By: {interaction.user.mention}"
        ),
        ERROR_COLOR
    )

# ---------- MODAL ---------- #

class StickyModal(discord.ui.Modal, title="Create / Edit Sticky"):
    title_input = discord.ui.TextInput(label="Embed Title", required=False)
    body_input = discord.ui.TextInput(
        label="Embed Description",
        style=discord.TextStyle.paragraph,
        required=True
    )
    footer_input = discord.ui.TextInput(label="Footer Text", required=False)
    image_input = discord.ui.TextInput(label="Image URL", required=False)

    def __init__(self, sticky_id=None):
        super().__init__()
        self.sticky_id = sticky_id

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=self.title_input.value or None,
            description=self.body_input.value,
            color=EMBED_COLOR
        )

        if self.footer_input.value:
            embed.set_footer(text=self.footer_input.value)

        if self.image_input.value:
            embed.set_image(url=self.image_input.value)

        view = StickyConfirmView(embed, interaction.channel.id, self.sticky_id)

        preview = make_embed(
            f"{self.e.sticky} Sticky Preview",
            "> Review your sticky below before confirming."
        )

        await interaction.response.send_message(
            embed=preview,
            view=view,
            ephemeral=True
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# ---------- CONFIRM VIEW ---------- #

class StickyConfirmView(discord.ui.View):
    def __init__(self, embed, channel_id, sticky_id=None):
        super().__init__(timeout=120)
        self.embed = embed
        self.channel_id = channel_id
        self.sticky_id = sticky_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        guild_id = str(interaction.guild.id)

        if guild_id not in data:
            data[guild_id] = {}

        if not self.sticky_id:
            self.sticky_id = str(uuid.uuid4())[:8]

        # Cleanup existing sticky in this channel before setting a new one
        for sid, info in list(data[guild_id].items()):
            if info["channel_id"] == self.channel_id and info.get("type") == "sticky":
                if info.get("last_message_id"):
                    try:
                        old = await interaction.channel.fetch_message(info["last_message_id"])
                        await old.delete()
                    except Exception:
                        pass
                del data[guild_id][sid]

        sent_message = await interaction.channel.send(embed=self.embed)

        data[guild_id][self.sticky_id] = {
            "type": "sticky",
            "channel_id": self.channel_id,
            "embed": self.embed.to_dict(),
            "last_message_id": sent_message.id
        }

        save_data(data)

        success = make_embed(
            f"{self.e.sticky} Sticky Created",
            f"> Sticky saved with ID `{self.sticky_id}`",
            SUCCESS_COLOR
        )
        await interaction.response.send_message(embed=success, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        cancel = make_embed("Cancelled", "> Sticky creation cancelled.", ERROR_COLOR)
        await interaction.response.send_message(embed=cancel, ephemeral=True)

# ---------- COG ---------- #

class Sticky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.e = Emojis(bot)

    sticky = app_commands.Group(name="sticky", description="Sticky message management")

    def is_admin(self, interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator

    # ---------------- STICKY COMMANDS ---------------- #

    @sticky.command(name="set", description="Create a sticky message")
    async def sticky_set(self, interaction: discord.Interaction):
        if not self.is_admin(interaction):
            return await interaction.response.send_message(embed=permission_error(interaction))
        await interaction.response.send_modal(StickyModal())

    @sticky.command(name="remove", description="Remove a sticky by ID")
    @app_commands.describe(sticky_id="The ID of the sticky to remove")
    async def sticky_remove(self, interaction: discord.Interaction, sticky_id: str):
        if not self.is_admin(interaction):
            return await interaction.response.send_message(embed=permission_error(interaction))

        data = load_data()
        guild_id = str(interaction.guild.id)

        if guild_id not in data or sticky_id not in data[guild_id]:
            return await interaction.response.send_message(
                embed=make_embed("Invalid ID", "> Sticky not found.", ERROR_COLOR),
                ephemeral=True
            )

        info = data[guild_id][sticky_id]
        if info.get("last_message_id"):
            try:
                msg = await interaction.channel.fetch_message(info["last_message_id"])
                await msg.delete()
            except Exception:
                pass

        del data[guild_id][sticky_id]
        save_data(data)

        await interaction.response.send_message(
            embed=make_embed("Sticky Removed", f"> `{sticky_id}` removed.", SUCCESS_COLOR),
            ephemeral=True
        )

    @sticky.command(name="list", description="List all stickies")
    async def sticky_list(self, interaction: discord.Interaction):
        if not self.is_admin(interaction):
            return await interaction.response.send_message(embed=permission_error(interaction))

        data = load_data()
        guild_id = str(interaction.guild.id)

        lines = []
        if guild_id in data:
            for sid, info in data[guild_id].items():
                if info.get("type") == "sticky":
                    channel = interaction.guild.get_channel(info["channel_id"])
                    lines.append(f"> ID `{sid}`: {channel.mention if channel else 'Unknown'}")

        if not lines:
            embed = make_embed(f"{self.e.sticky} Active Stickies", "> There are no active stickies in this server.")
        else:
            embed = make_embed(f"{self.e.sticky} Active Stickies", "\n".join(lines))

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- AUTOPING COMMANDS ---------------- #

    # ---------------- MESSAGE LISTENER ---------------- #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.guild:
            return

        data = load_data()
        guild_id = str(message.guild.id)
        if guild_id not in data:
            return

        data_changed = False

        for sid, info in data[guild_id].items():
            if message.channel.id != info.get("channel_id"):
                continue

            if info.get("last_message_id"):
                try:
                    old_msg = await message.channel.fetch_message(info["last_message_id"])
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

            if info.get("type") == "sticky":
                embed = discord.Embed.from_dict(info["embed"])
                new_msg = await message.channel.send(embed=embed)
                info["last_message_id"] = new_msg.id
                data_changed = True
            elif info.get("type") == "sticky_cv2":
                comp_list = info.get("components", [])
                try:
                    import discord.http as _dhttp
                    route = _dhttp.Route("POST", "/channels/{channel_id}/messages", channel_id=message.channel.id)
                    resp = await self.bot.http.request(route, json={"components": comp_list, "flags": 32768})
                    info["last_message_id"] = int(resp["id"])
                    data_changed = True
                except Exception as e:
                    print(f"[Sticky] CV2 repost error: {e}")

        if data_changed:
            save_data(data)


async def setup(bot):
    await bot.add_cog(Sticky(bot))