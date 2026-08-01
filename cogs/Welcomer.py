import discord
import discord.http as _dhttp
import json
import logging
import os
from discord.ext import commands
from discord import app_commands

_log = logging.getLogger("bot.welcomer")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "data", "welcomer")
WELCOMER_PATH = os.path.join(CONFIG_DIR, "welcomer.json")
WELCOMER_DM_PATH = os.path.join(CONFIG_DIR, "welcomerDM.json")

# Default Components v2 payload (type 17 container) for both channel and DM
DEFAULT_CV2 = [
    {
        "type": 17,
        "accent_color": None,
        "spoiler": False,
        "components": [
            {
                "type": 10,
                "content": "Welcomer Message\nConfigure your welcomer message"
            }
        ]
    }
]

DEFAULT_WELCOMER = {
    "channel_id": 0,
    "cv2": DEFAULT_CV2,
}

DEFAULT_WELCOMER_DM = {
    "enabled": True,
    "cv2": DEFAULT_CV2,
}


def load_json(path: str, default: dict) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return dict(default)
    try:
        with open(path, "r") as f:
            on_disk = json.load(f)
        # Merge so defaults fill any missing keys
        merged = dict(default)
        merged.update(on_disk)
        return merged
    except Exception as e:
        _log.error("[Welcomer] Failed to load %s: %s — using defaults", path, e)
        return dict(default)


def format_text(text: str, member: discord.Member) -> str:
    """Replace placeholders in text content."""
    if not text:
        return ""
    try:
        return text.format(
            mention=member.mention,
            username=member.name,
            display_name=member.display_name,
            avatar=member.display_avatar.url,
            guild=member.guild.name,
            read_channel_id=0,
        )
    except (KeyError, ValueError):
        return text


def _format_cv2_component(comp: dict, member: discord.Member) -> dict:
    """Recursively replace placeholders inside a CV2 component tree.

    Handles:
    - type 10 (text): formats ``content``
    - media components: formats ``media.url`` and ``accessory.media.url``
    - any other nested dict/list so future component types are covered
    """
    comp = dict(comp)

    # Text component — format content
    if comp.get("type") == 10 and isinstance(comp.get("content"), str):
        comp["content"] = format_text(comp["content"], member)

    # Media URL at the top level: { "media": { "url": "..." } }
    if isinstance(comp.get("media"), dict) and isinstance(comp["media"].get("url"), str):
        comp["media"] = dict(comp["media"])
        comp["media"]["url"] = format_text(comp["media"]["url"], member)

    # Accessory with a nested media URL: { "accessory": { "media": { "url": "..." } } }
    if isinstance(comp.get("accessory"), dict):
        acc = dict(comp["accessory"])
        if isinstance(acc.get("media"), dict) and isinstance(acc["media"].get("url"), str):
            acc["media"] = dict(acc["media"])
            acc["media"]["url"] = format_text(acc["media"]["url"], member)
        comp["accessory"] = acc

    # Recurse into child components
    if "components" in comp:
        comp["components"] = [_format_cv2_component(c, member) for c in comp["components"]]

    return comp


async def _send_cv2(http_client, channel_id: int, components: list) -> None:
    """Send a Components v2 message (flag 32768) via raw HTTP."""
    route = _dhttp.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    await http_client.request(route, json={"components": components, "flags": 32768})


async def _send_cv2_dm(bot, user: discord.User | discord.Member, components: list) -> None:
    """Open a DM channel and send a Components v2 message."""
    dm_channel = await user.create_dm()
    # Use the same helper as channel sends — pass bot.http directly
    await _send_cv2(bot.http, dm_channel.id, components)


class Welcomer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Ensure config files exist
        load_json(WELCOMER_PATH, DEFAULT_WELCOMER)
        load_json(WELCOMER_DM_PATH, DEFAULT_WELCOMER_DM)

    @app_commands.command(name="welcome", description="Upload a Components v2 JSON file to set the welcome message.")
    @app_commands.describe(file="JSON file containing a CV2 components array (type 17)")
    async def set_welcomer(self, interaction: discord.Interaction, file: discord.Attachment):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=discord.Embed(title="Permission Denied", description="You need Administrator.", color=discord.Color.red()),
                ephemeral=True
            )
            return
        if not file.filename.lower().endswith(".json"):
            await interaction.response.send_message(
                embed=discord.Embed(title="Invalid File", description="Please upload a `.json` file.", color=discord.Color.red()),
                ephemeral=True
            )
            return
        try:
            raw = await file.read()
            data = json.loads(raw.decode("utf-8"))
            # Accept either a bare array or {cv2: [...]}
            if isinstance(data, dict) and "cv2" in data:
                cv2 = data["cv2"]
            elif isinstance(data, list):
                cv2 = data
            else:
                raise ValueError("Expected a JSON array of components or an object with a 'cv2' key.")
            if not cv2 or not all(isinstance(c, dict) for c in cv2):
                raise ValueError("Components must be a non-empty array of objects.")
            cfg = load_json(WELCOMER_PATH, DEFAULT_WELCOMER)
            cfg["cv2"] = cv2
            with open(WELCOMER_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            await interaction.response.send_message(
                embed=discord.Embed(title="Welcomer Updated", description="Channel welcome message updated.", color=discord.Color.green()),
                ephemeral=True
            )
        except json.JSONDecodeError as e:
            _log.error("[Welcomer] /welcome JSON parse error: %s", e)
            await interaction.response.send_message(
                embed=discord.Embed(title="JSON Error", description=f"Invalid JSON: {e}", color=discord.Color.red()),
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(
                embed=discord.Embed(title="Invalid Config", description=str(e), color=discord.Color.red()),
                ephemeral=True
            )
        except Exception as e:
            _log.exception("[Welcomer] /welcome unexpected error: %s", e)
            await interaction.response.send_message(
                embed=discord.Embed(title="Error", description=f"Unexpected error: {e}", color=discord.Color.red()),
                ephemeral=True
            )

    @app_commands.command(name="welcomedm", description="Upload a Components v2 JSON file to set the DM welcome message.")
    @app_commands.describe(file="JSON file containing a CV2 components array (type 17)")
    async def set_welcomer_dm(self, interaction: discord.Interaction, file: discord.Attachment):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=discord.Embed(title="Permission Denied", description="You need Administrator.", color=discord.Color.red()),
                ephemeral=True
            )
            return
        if not file.filename.lower().endswith(".json"):
            await interaction.response.send_message(
                embed=discord.Embed(title="Invalid File", description="Please upload a `.json` file.", color=discord.Color.red()),
                ephemeral=True
            )
            return
        try:
            raw = await file.read()
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict) and "cv2" in data:
                cv2 = data["cv2"]
            elif isinstance(data, list):
                cv2 = data
            else:
                raise ValueError("Expected a JSON array of components or an object with a 'cv2' key.")
            if not cv2 or not all(isinstance(c, dict) for c in cv2):
                raise ValueError("Components must be a non-empty array of objects.")
            cfg = load_json(WELCOMER_DM_PATH, DEFAULT_WELCOMER_DM)
            cfg["cv2"] = cv2
            with open(WELCOMER_DM_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            await interaction.response.send_message(
                embed=discord.Embed(title="DM Welcomer Updated", description="DM welcome message updated.", color=discord.Color.green()),
                ephemeral=True
            )
        except json.JSONDecodeError as e:
            _log.error("[Welcomer] /welcomedm JSON parse error: %s", e)
            await interaction.response.send_message(
                embed=discord.Embed(title="JSON Error", description=f"Invalid JSON: {e}", color=discord.Color.red()),
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(
                embed=discord.Embed(title="Invalid Config", description=str(e), color=discord.Color.red()),
                ephemeral=True
            )
        except Exception as e:
            _log.exception("[Welcomer] /welcomedm unexpected error: %s", e)
            await interaction.response.send_message(
                embed=discord.Embed(title="Error", description=f"Unexpected error: {e}", color=discord.Color.red()),
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)

        # Try per-guild config first, then fall back to the global configuration.
        guild_welcomer_path    = os.path.join(CONFIG_DIR, guild_id, "welcomer.json")
        guild_welcomer_dm_path = os.path.join(CONFIG_DIR, guild_id, "welcomerDM.json")

        if os.path.exists(guild_welcomer_path):
            cfg = load_json(guild_welcomer_path, DEFAULT_WELCOMER)
        else:
            cfg = load_json(WELCOMER_PATH, DEFAULT_WELCOMER)

        if os.path.exists(guild_welcomer_dm_path):
            dm_cfg = load_json(guild_welcomer_dm_path, DEFAULT_WELCOMER_DM)
        else:
            dm_cfg = load_json(WELCOMER_DM_PATH, DEFAULT_WELCOMER_DM)

        # ── Channel welcome (Components v2) ───────────────────────────────────
        cv2 = cfg.get("cv2")
        raw_channel_id = cfg.get("channel_id") or 0
        try:
            channel_id = int(str(raw_channel_id).split(".")[0])
        except (TypeError, ValueError):
            channel_id = 0

        if cv2 and isinstance(cv2, list) and channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await member.guild.fetch_channel(channel_id)
                except discord.NotFound:
                    _log.error("[Welcomer] Welcome channel %s not found (404) — update channel_id in config.", channel_id)
                    channel = None
                except discord.Forbidden:
                    _log.error("[Welcomer] No permission to access welcome channel %s.", channel_id)
                    channel = None
                except Exception as e:
                    _log.error("[Welcomer] Could not fetch welcome channel %s: %s", channel_id, e)
                    channel = None
            if channel:
                try:
                    formatted = [_format_cv2_component(c, member) for c in cv2]
                    await _send_cv2(self.bot.http, channel.id, formatted)
                except Exception as e:
                    _log.error("[Welcomer] Failed to send channel welcome CV2 for %s: %s", member, e)

        # ── DM welcome (Components v2) ─────────────────────────────────────────
        if dm_cfg.get("enabled", True):
            dm_cv2 = dm_cfg.get("cv2")
            if dm_cv2 and isinstance(dm_cv2, list):
                try:
                    formatted_dm = [_format_cv2_component(c, member) for c in dm_cv2]
                    # Re-fetch the member to ensure a fully populated User object,
                    # which avoids create_dm() issues on freshly joined members.
                    try:
                        fresh = await member.guild.fetch_member(member.id)
                    except Exception:
                        fresh = member
                    dm_channel = await fresh.create_dm()
                    await _send_cv2(self.bot.http, dm_channel.id, formatted_dm)
                    _log.info("[Welcomer] DM welcome sent to %s (channel %s)", member, dm_channel.id)
                except discord.Forbidden:
                    _log.debug("[Welcomer] DM blocked by %s — user has DMs disabled.", member)
                except Exception as e:
                    _log.error("[Welcomer] Failed to send DM welcome CV2 for %s: %s", member, e, exc_info=True)


async def setup(bot):
    await bot.add_cog(Welcomer(bot))
