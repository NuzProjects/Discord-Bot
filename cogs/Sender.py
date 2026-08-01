import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path
from typing import Any

# Config
SEND_DIR = Path("data/send")
COLOR_ERROR = discord.Color.red()
COLOR_SUCCESS = discord.Color.green()


class SendMessages(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ensure_directories()

    def _ensure_directories(self):
        SEND_DIR.mkdir(parents=True, exist_ok=True)

    async def send_error_embed(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=COLOR_ERROR)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def message_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        if SEND_DIR.exists():
            for file in SEND_DIR.glob("*.json"):
                if current.lower() in file.stem.lower():
                    choices.append(app_commands.Choice(name=file.stem, value=file.stem))
        return choices[:25]

    def _parse_color(self, color_val: Any) -> discord.Color:
        try:
            if isinstance(color_val, str) and color_val.startswith("#"):
                return discord.Color.from_str(color_val)
            return discord.Color(int(color_val))
        except Exception:
            return discord.Color.default()

    def _is_raw_components(self, data: Any) -> bool:
        """Returns True if data is a raw Discord Components V2 payload (list of type-17 objects)."""
        return (
            isinstance(data, list)
            and len(data) > 0
            and isinstance(data[0], dict)
            and data[0].get("type") == 17
        )

    async def _send_components_v2(self, channel_id: int, components: list) -> None:
        """Send a raw Components V2 payload via aiohttp directly."""
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self.bot.http.token}",
            "Content-Type": "application/json",
        }
        body = {
            "components": components,
            "flags": 1 << 15,  # IS_COMPONENTS_V2
        }
        # Access the underlying aiohttp session from discord.py's HTTPClient
        session = self.bot.http._HTTPClient__session
        async with session.post(url, headers=headers, json=body) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise discord.HTTPException(resp, text)

    def _build_layout_view(self, data: dict[str, Any]) -> discord.ui.LayoutView | None:
        """Build a LayoutView from our custom JSON format (container/containers keys)."""
        containers_cfg = data.get("containers")
        if containers_cfg is None and data.get("container"):
            containers_cfg = [data["container"]]
        if not containers_cfg:
            return None

        view = discord.ui.LayoutView()
        for cfg in containers_cfg:
            children: list[discord.ui.Item[Any]] = []

            if cfg.get("components"):
                children = self._parse_components(cfg["components"])
            else:
                # Legacy text/thumbnail/media_gallery format
                text_cfg = cfg.get("text", {})
                markdown = self._legacy_markdown(text_cfg)
                thumb_url = cfg.get("thumbnail")
                if thumb_url:
                    children.append(discord.ui.Section(markdown, accessory=discord.ui.Thumbnail(thumb_url)))
                else:
                    children.append(discord.ui.TextDisplay(markdown))
                for media_url in cfg.get("media_gallery", []):
                    gallery = discord.ui.MediaGallery()
                    gallery.add_item(media=media_url)
                    children.append(gallery)

            accent_raw = cfg.get("accent_color")
            accent = self._parse_color(accent_raw) if accent_raw else discord.utils.MISSING
            view.add_item(discord.ui.Container(*children, accent_colour=accent))

        return view

    def _parse_components(self, components: list) -> list[discord.ui.Item[Any]]:
        children: list[discord.ui.Item[Any]] = []
        for component in components:
            ctype = component.get("type")

            if ctype == 10:
                children.append(discord.ui.TextDisplay(component.get("content", "")))

            elif ctype == 14:
                spacing = component.get("spacing", 1)
                divider = component.get("divider", True)
                children.append(discord.ui.Separator(
                    divider=divider,
                    spacing=discord.SeparatorSpacing.small if spacing == 1 else discord.SeparatorSpacing.large
                ))

            elif ctype == 1:
                buttons = []
                for btn in component.get("components", []):
                    if btn.get("type") == 2 and btn.get("style") == 5:
                        emoji_raw = btn.get("emoji")
                        emoji = discord.PartialEmoji.from_str(emoji_raw) if isinstance(emoji_raw, str) else None
                        buttons.append(discord.ui.Button(
                            label=btn.get("label", ""),
                            url=btn.get("url"),
                            disabled=btn.get("disabled", False),
                            emoji=emoji
                        ))
                if buttons:
                    children.append(discord.ui.ActionRow(*buttons))

            elif ctype == 11:
                gallery = discord.ui.MediaGallery()
                for item in component.get("items", []):
                    gallery.add_item(media=item.get("url", ""))
                if component.get("url"):
                    gallery.add_item(media=component["url"])
                children.append(gallery)

            elif ctype == 9:
                content = component.get("content", "")
                thumb_url = component.get("thumbnail")
                if thumb_url:
                    children.append(discord.ui.Section(content, accessory=discord.ui.Thumbnail(thumb_url)))
                else:
                    children.append(discord.ui.TextDisplay(content))

        return children

    def _legacy_markdown(self, text_cfg: dict[str, Any]) -> str:
        parts: list[str] = []
        title = (text_cfg.get("title") or "").strip()
        description = (text_cfg.get("description") or "").strip()
        footer = (text_cfg.get("footer") or "").strip()
        if title:
            parts.append(f"## {title}")
        if description:
            parts.append(description)
        inline_buffer: list[tuple[str, str]] = []
        for field in text_cfg.get("fields", []):
            name = (field.get("name") or "").strip()
            value = (field.get("value") or "").strip()
            if field.get("inline", False):
                inline_buffer.append((name or "\u200b", value or "\u200b"))
                if len(inline_buffer) == 3:
                    parts.append(" · ".join(f"**{n}**" for n, _ in inline_buffer))
                    parts.append(" · ".join(v for _, v in inline_buffer))
                    inline_buffer.clear()
                continue
            if inline_buffer:
                parts.append(" · ".join(f"**{n}**" for n, _ in inline_buffer))
                parts.append(" · ".join(v for _, v in inline_buffer))
                inline_buffer.clear()
            if name:
                parts.append(f"**{name}**")
            if value:
                parts.append(value)
        if inline_buffer:
            parts.append(" · ".join(f"**{n}**" for n, _ in inline_buffer))
            parts.append(" · ".join(v for _, v in inline_buffer))
        if footer:
            parts.append(f"-# {footer}")
        return "\n\n".join(p for p in parts if p).strip() or "\u200b"

    @app_commands.command(name="send", description="Send a pre-configured message from a JSON file.")
    @app_commands.autocomplete(message=message_autocomplete)
    async def send_message(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await self.send_error_embed(interaction, "Permission Denied",
                f"You do not have permission to use this command.\n**Required:** Administrator\n**Attempted By:** {interaction.user.mention}")

        target_file = SEND_DIR / f"{message}.json"
        if not target_file.exists():
            return await self.send_error_embed(interaction, "File Not Found",
                f"The template `{message}.json` does not exist in the data folder.")

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return await self.send_error_embed(interaction, "JSON Syntax Error",
                f"Formatting error in `{message}.json`\n**Detail:** {e.msg}\n**Location:** Line {e.lineno}, Column {e.colno}")
        except Exception as e:
            return await self.send_error_embed(interaction, "System Error", str(e))

        # Resolve channel
        channel = interaction.channel or self.bot.get_channel(interaction.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(interaction.channel_id)
            except Exception as e:
                return await self.send_error_embed(interaction, "Channel Error", f"Could not resolve channel: {e}")

        try:
            # --- Raw Components V2 (list of type-17 objects) ---
            if self._is_raw_components(data):
                await self._send_components_v2(channel.id, data)

            # --- Custom container/containers JSON ---
            elif isinstance(data, dict) and (data.get("container") or data.get("containers")):
                layout_view = self._build_layout_view(data)
                content = data.get("content") or None
                await channel.send(content=content, view=layout_view)

            # --- Legacy embed ---
            elif isinstance(data, dict) and data.get("embed"):
                embed_data = data["embed"]
                color = self._parse_color(embed_data.get("color", "#7289da"))
                embed = discord.Embed(
                    title=embed_data.get("title"),
                    description=embed_data.get("description"),
                    color=color
                )
                if (author := embed_data.get("author")) and author.get("name"):
                    embed.set_author(name=author["name"], icon_url=author.get("icon_url") or None)
                if thumb := embed_data.get("thumbnail"):
                    embed.set_thumbnail(url=thumb)
                if img := embed_data.get("image"):
                    embed.set_image(url=img)
                if footer := embed_data.get("footer"):
                    embed.set_footer(text=footer.get("text"), icon_url=footer.get("icon_url") or None)
                for field in embed_data.get("fields", []):
                    embed.add_field(
                        name=field.get("name", "\u200b"),
                        value=field.get("value", "\u200b"),
                        inline=field.get("inline", False)
                    )
                await channel.send(content=data.get("content") or None, embed=embed)

            # --- Plain content ---
            elif isinstance(data, dict) and data.get("content"):
                await channel.send(content=data["content"])

            else:
                return await self.send_error_embed(interaction, "Invalid Configuration",
                    "The JSON file must contain a raw components array, `container`/`containers`, `embed`, or `content`.")

            await interaction.followup.send(embed=discord.Embed(
                title="Message Sent",
                description=f"Successfully sent the template: `{message}`",
                color=COLOR_SUCCESS
            ), ephemeral=True)

        except discord.Forbidden:
            await self.send_error_embed(interaction, "Access Forbidden",
                "The bot does not have permission to send messages in this channel.")
        except discord.HTTPException as e:
            await self.send_error_embed(interaction, "Discord API Error", f"`{e.status}` {e.text}")
        except Exception as e:
            await self.send_error_embed(interaction, "Unexpected Error", str(e))


async def setup(bot: commands.Bot):
    await bot.add_cog(SendMessages(bot))