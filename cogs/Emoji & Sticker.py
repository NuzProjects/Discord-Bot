import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import json
import aiohttp
import re
import io

# ================== STORAGE ==================

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "emoji.json"

COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_NEUTRAL = discord.Color.from_rgb(0, 0, 0)
COLOR_WARNING = discord.Color.orange()

def load_data():
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"guilds": {}}, indent=4))
    return json.loads(DATA_FILE.read_text())

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=4))


# ================== HELPERS ==================

def parse_emojis(raw: str) -> list[dict]:
    """Extract up to 4 emoji dicts from a space-separated string."""
    tokens = raw.strip().split()
    results = []
    for token in tokens:
        match = re.match(r"<(a?):([a-zA-Z0-9_]+):(\d+)>", token)
        if match:
            animated = match.group(1) == "a"
            ext = "gif" if animated else "png"
            results.append({
                "name": match.group(2),
                "id": match.group(3),
                "animated": animated,
                "url": f"https://cdn.discordapp.com/emojis/{match.group(3)}.{ext}",
                "raw": token,
            })
        if len(results) == 4:
            break
    return results

def parse_sticker_url(url: str) -> dict | None:
    """
    Parses a Discord sticker CDN URL.
    Accepts:
      https://media.discordapp.net/stickers/<id>.png/gif/json
      https://cdn.discordapp.com/stickers/<id>.png/gif/json
    Returns dict with id, ext, url — or None if not valid.
    """
    match = re.match(
        r"https://(?:media\.discordapp\.net|cdn\.discordapp\.com)/stickers/(\d+)\.(png|gif|json)",
        url.strip()
    )
    if not match:
        return None
    return {
        "id": match.group(1),
        "ext": match.group(2),
        "url": url.strip(),
    }


# ================== COG ==================

class EmojiTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ================== PERMISSION CHECK ==================

    async def check_perms(self, interaction: discord.Interaction, *permissions: str) -> bool:
        """Passes if the user has administrator OR any ONE of the listed permissions."""
        user_perms = interaction.user.guild_permissions

        if user_perms.administrator:
            return True

        for permission in permissions:
            if getattr(user_perms, permission, False):
                return True

        readable = " or ".join(f"`{p.replace('_', ' ').title()}`" for p in permissions)
        embed = discord.Embed(
            title="<:error:1493771193134616586> Permission Denied",
            description="\n".join([
                "You do not have permission to use this command.",
                f"> Required: {readable}",
                f"> Attempted By: {interaction.user.mention}"
            ]),
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    def bot_missing_perm(self, perm_label: str) -> discord.Embed:
        return discord.Embed(
            title="<:error:1493771193134616586> Missing Bot Permission",
            description=f"I need **{perm_label}** to do that.",
            color=COLOR_ERROR
        )

    # ================== EMOJI INFO ==================

    @app_commands.command(name="emojiinfo", description="Get information about up to 3 custom emojis")
    @app_commands.describe(emojis="Up to 3 emojis separated by spaces (<:name:id> or <a:name:id>)")
    async def emojiinfo(self, interaction: discord.Interaction, emojis: str):

        parsed = parse_emojis(emojis)

        if not parsed:
            await interaction.response.send_message(embed=discord.Embed(
                title="<:error:1493771193134616586> Invalid Emoji",
                description="No valid emojis found. Use format like `<:name:id>` or `<a:name:id>`.",
                color=COLOR_ERROR
            ), ephemeral=True)
            return

        too_many = len(parsed) == 4
        to_show = parsed[:3]

        embeds = []
        for entry in to_show:
            embed = discord.Embed(
                title="<:emoji:1493765595840250027> Emoji Information",
                description=(
                    f"> Name: `{entry['name']}`\n"
                    f"> ID: `{entry['id']}`\n"
                    f"> Animated: {'Yes' if entry['animated'] else 'No'}\n"
                    f"> URL: [Open Image]({entry['url']})"
                ),
                color=COLOR_NEUTRAL
            )
            embed.set_thumbnail(url=entry["url"])
            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds)

        if too_many:
            await interaction.followup.send(embed=discord.Embed(
                title="<:error:1493771193134616586> Too Many Emojis",
                description="You provided **4 emojis** — only the first **3** were shown. Limit is 3 at a time.",
                color=COLOR_ERROR
            ))

    # ================== COPY EMOJI ==================

    @app_commands.command(name="copyemoji", description="Copy up to 3 emojis into this server")
    @app_commands.describe(
        emojis="Up to 3 emojis separated by spaces (<:name:id> or <a:name:id>)",
        name="Optional name override (only applies when copying a single emoji)"
    )
    async def copyemoji(self, interaction: discord.Interaction, emojis: str, name: str | None = None):
        if not await self.check_perms(interaction, "manage_emojis_and_stickers"):
            return

        if not interaction.guild.me.guild_permissions.manage_emojis_and_stickers:
            await interaction.response.send_message(
                embed=self.bot_missing_perm("Manage Emojis and Stickers"),
                ephemeral=True
            )
            return

        parsed = parse_emojis(emojis)

        if not parsed:
            await interaction.response.send_message(embed=discord.Embed(
                title="<:error:1493771193134616586> Invalid Format",
                description="No valid emojis found. Use `<:name:id>` or `<a:name:id>` format.",
                color=COLOR_ERROR
            ), ephemeral=True)
            return

        too_many = len(parsed) == 4
        to_copy = parsed[:3]
        await interaction.response.defer()

        for entry in to_copy:
            final_name = (name if name and len(to_copy) == 1 else entry["name"])

            async with aiohttp.ClientSession() as session:
                async with session.get(entry["url"]) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(
                            title="<:error:1493771193134616586> Download Failed",
                            description=f"Could not download **`{entry['name']}`**.",
                            color=COLOR_ERROR
                        ))
                        continue
                    image = await resp.read()

            try:
                new_emoji = await interaction.guild.create_custom_emoji(
                    name=final_name,
                    image=image,
                    reason=f"Copied by {interaction.user}"
                )
            except discord.HTTPException as e:
                await interaction.followup.send(embed=discord.Embed(
                    title="<:error:1493771193134616586> Creation Failed",
                    description=f"Could not add **`{entry['name']}`**: {e}",
                    color=COLOR_ERROR
                ))
                continue

            await interaction.followup.send(embed=discord.Embed(
                title="<:success:1493767597605519380> Emoji Added",
                description=f"{new_emoji} **`{new_emoji.name}`** has been added to this server.",
                color=COLOR_SUCCESS
            ))

        if too_many:
            await interaction.followup.send(embed=discord.Embed(
                title="<:error:1493771193134616586> Too Many Emojis",
                description="You provided **4 emojis** — only the first **3** were copied. Limit is 3 at a time.",
                color=COLOR_ERROR
            ))

    # ================== STICKER INFO ==================

    @app_commands.command(name="stickerinfo", description="Get info about a sticker — by name (this server) or CDN URL (any server)")
    @app_commands.describe(query="Sticker name from this server, or a Discord CDN sticker URL from any server")
    async def stickerinfo(self, interaction: discord.Interaction, query: str):

        embed = discord.Embed(title="<:star:1494798374283776090> Sticker Information", color=COLOR_NEUTRAL)

        fmt_map = {
            discord.StickerFormatType.png: "PNG",
            discord.StickerFormatType.apng: "APNG (Animated)",
            discord.StickerFormatType.lottie: "Lottie (Animated)",
            discord.StickerFormatType.gif: "GIF",
        }

        # ---- Path A: CDN URL (cross-server) ----
        parsed_url = parse_sticker_url(query)
        if parsed_url:
            try:
                # Attempt full metadata resolution via API (works for standard/Nitro stickers)
                sticker = await self.bot.fetch_sticker(int(parsed_url["id"]))
                lines = [
                    f"> Name: `{sticker.name}`",
                    f"> ID: `{sticker.id}`",
                    f"> Format: {fmt_map.get(sticker.format, 'Unknown')}",
                ]
                if hasattr(sticker, "description"):
                    lines.append(f"> Description: {sticker.description or 'None'}")
                lines.append(f"> URL: [Open Image]({sticker.url})")
                embed.description = "\n".join(lines)
                if sticker.format != discord.StickerFormatType.lottie:
                    embed.set_thumbnail(url=sticker.url)
            except Exception:
                # Guild sticker from another server — show what we can from the URL alone
                ext_label = {"png": "PNG", "gif": "GIF", "json": "Lottie (Animated)"}.get(parsed_url["ext"], "Unknown")
                embed.description = (
                    f"> ID: `{parsed_url['id']}`\n"
                    f"> Format: {ext_label}\n"
                    f"> URL: [Open Image]({parsed_url['url']})"
                )
                embed.set_footer(text="Full metadata unavailable — sticker belongs to another server.")
                if parsed_url["ext"] != "json":
                    embed.set_thumbnail(url=parsed_url["url"])

            await interaction.response.send_message(embed=embed)
            return

        # ---- Path B: Name lookup in this server ----
        try:
            stickers = await interaction.guild.fetch_stickers()
        except Exception:
            await interaction.response.send_message(embed=discord.Embed(
                title="<:error:1493771193134616586> Error",
                description="Could not fetch stickers for this server.",
                color=COLOR_ERROR
            ), ephemeral=True)
            return

        match = discord.utils.find(lambda s: s.name.lower() == query.lower(), stickers)

        if not match:
            await interaction.response.send_message(embed=discord.Embed(
                title="<:error:1493771193134616586> Sticker Not Found",
                description="\n".join([
                    f"No sticker named **`{query}`** was found in this server.",
                    "> Tip: Paste a Discord CDN sticker URL to look up stickers from other servers."
                ]),
                color=COLOR_ERROR
            ), ephemeral=True)
            return

        embed.description = (
            f"> Name: `{match.name}`\n"
            f"> ID: `{match.id}`\n"
            f"> Format: {fmt_map.get(match.format, 'Unknown')}\n"
            f"> Description: {match.description or 'None'}\n"
            f"> URL: [Open Image]({match.url})"
        )
        if match.format != discord.StickerFormatType.lottie:
            embed.set_thumbnail(url=match.url)

        await interaction.response.send_message(embed=embed)

    # ================== STICKER INFO AUTOCOMPLETE ==================

    @stickerinfo.autocomplete("query")
    async def stickerinfo_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        # Don't autocomplete if user is typing a URL
        if current.startswith("http"):
            return []
        try:
            stickers = await interaction.guild.fetch_stickers()
        except Exception:
            return []
        return [
            app_commands.Choice(name=s.name, value=s.name)
            for s in stickers
            if current.lower() in s.name.lower()
        ][:25]

    # ================== STICKER STEAL ==================

    @app_commands.command(name="stealsticker", description="Copy a sticker into this server — by message ID or direct CDN URL")
    @app_commands.describe(
        source="A message ID (any visible channel) or a Discord CDN sticker URL from any server",
        name="Optional new name for the sticker"
    )
    async def stealsticker(self, interaction: discord.Interaction, source: str, name: str | None = None):
        if not await self.check_perms(interaction, "manage_emojis_and_stickers"):
            return

        if not interaction.guild.me.guild_permissions.manage_emojis_and_stickers:
            await interaction.response.send_message(
                embed=self.bot_missing_perm("Manage Emojis and Stickers"),
                ephemeral=True
            )
            return

        await interaction.response.defer()

        sticker_url: str | None = None
        sticker_name: str = name or "sticker"
        sticker_format: discord.StickerFormatType | None = None

        # ---- Path A: Direct CDN URL (cross-server) ----
        parsed_url = parse_sticker_url(source)
        if parsed_url:
            if parsed_url["ext"] == "json":
                await interaction.followup.send(embed=discord.Embed(
                    title="<:error:1493771193134616586> Unsupported Format",
                    description="Lottie stickers (Nitro animated) cannot be copied by bots.",
                    color=COLOR_ERROR
                ))
                return

            sticker_url = parsed_url["url"]

            # Try to resolve the real name from the API
            if not name:
                try:
                    fetched = await self.bot.fetch_sticker(int(parsed_url["id"]))
                    sticker_name = fetched.name
                except Exception:
                    sticker_name = f"sticker_{parsed_url['id']}"

        # ---- Path B: Message ID — search current channel, then guild, then all bot guilds ----
        else:
            message = None

            try:
                message = await interaction.channel.fetch_message(int(source))
            except Exception:
                pass

            if not message:
                for channel in interaction.guild.text_channels:
                    try:
                        message = await channel.fetch_message(int(source))
                        break
                    except Exception:
                        continue

            if not message:
                for guild in self.bot.guilds:
                    if guild.id == interaction.guild.id:
                        continue
                    for channel in guild.text_channels:
                        try:
                            message = await channel.fetch_message(int(source))
                            break
                        except Exception:
                            continue
                    if message:
                        break

            if not message:
                await interaction.followup.send(embed=discord.Embed(
                    title="<:error:1493771193134616586> Message Not Found",
                    description="\n".join([
                        "Could not find a message with that ID in any accessible channel.",
                        "> Tip: Paste a Discord CDN sticker URL to steal stickers from servers the bot isn't in."
                    ]),
                    color=COLOR_ERROR
                ))
                return

            if not message.stickers:
                await interaction.followup.send(embed=discord.Embed(
                    title="<:error:1493771193134616586> No Sticker Found",
                    description="That message does not contain any stickers.",
                    color=COLOR_ERROR
                ))
                return

            sticker_item = message.stickers[0]

            if sticker_item.format == discord.StickerFormatType.lottie:
                await interaction.followup.send(embed=discord.Embed(
                    title="<:error:1493771193134616586> Unsupported Format",
                    description="Lottie stickers (Nitro animated) cannot be copied by bots.",
                    color=COLOR_ERROR
                ))
                return

            sticker_url = sticker_item.url
            sticker_name = name or sticker_item.name
            sticker_format = sticker_item.format

        # ---- Download ----
        async with aiohttp.ClientSession() as session:
            async with session.get(sticker_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(embed=discord.Embed(
                        title="<:error:1493771193134616586> Download Failed",
                        description="Could not download the sticker image.",
                        color=COLOR_ERROR
                    ))
                    return
                image_bytes = await resp.read()

        ext = "gif" if (
            sticker_format == discord.StickerFormatType.gif
            or (parsed_url and parsed_url["ext"] == "gif")
        ) else "png"

        # ---- Upload ----
        try:
            file = discord.File(
                fp=io.BytesIO(image_bytes),
                filename=f"{sticker_name}.{ext}"
            )
            new_sticker = await interaction.guild.create_sticker(
                name=sticker_name,
                description=f"Stolen by {interaction.user}",
                emoji="⭐",
                file=file,
                reason=f"Stolen by {interaction.user}"
            )
        except discord.HTTPException as e:
            await interaction.followup.send(embed=discord.Embed(
                title="<:error:1493771193134616586> Creation Failed",
                description=f"Discord error: {e}",
                color=COLOR_ERROR
            ))
            return

        result_embed = discord.Embed(
            title="<:success:1493767597605519380> Sticker Added",
            description=f"**`{new_sticker.name}`** has been added to this server.",
            color=COLOR_SUCCESS
        )
        if new_sticker.format != discord.StickerFormatType.lottie:
            result_embed.set_thumbnail(url=new_sticker.url)

        await interaction.followup.send(embed=result_embed)


# ================== SETUP ==================

async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiTools(bot))