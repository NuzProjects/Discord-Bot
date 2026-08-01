import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import json
import datetime

# ================== STORAGE ==================

DATA_DIR = Path("data/backup")
COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR = discord.Color.red()
COLOR_NEUTRAL = discord.Color.from_rgb(0, 0, 0)
COLOR_WARNING = discord.Color.orange()

def get_backup_path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"

def list_backups() -> list[str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return [f.stem for f in DATA_DIR.glob("*.json")]

def save_backup(name: str, data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    get_backup_path(name).write_text(json.dumps(data, indent=4))

def load_backup(name: str) -> dict | None:
    path = get_backup_path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text())

def delete_backup(name: str) -> bool:
    path = get_backup_path(name)
    if not path.exists():
        return False
    path.unlink()
    return True


# ================== COG ==================

class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)

    # ================== ADMIN GUARD ==================

    async def admin_guard(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="Permission Denied",
                description="\n".join([
                    f"{self.e.error} You do not have permission to use this command.",
                    "> Required: Administrator",
                    f"> Attempted By: {interaction.user.mention}"
                ]),
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    # ================== /backup ==================

    @app_commands.command(name="backup", description="Create a full server backup (Administrator only)")
    @app_commands.describe(name="Name for this backup (no spaces)")
    async def backup(self, interaction: discord.Interaction, name: str):
        if not await self.admin_guard(interaction):
            return

        # Sanitize name
        name = name.strip().replace(" ", "_")

        if get_backup_path(name).exists():
            embed = discord.Embed(
                title=f"{self.e.error} Backup Already Exists",
                description=f"A backup named **`{name}`** already exists. Delete it first or choose a different name.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild
        data = {
            "meta": {
                "name": name,
                "guild_id": guild.id,
                "guild_name": guild.name,
                "created_at": datetime.datetime.utcnow().isoformat(),
                "created_by": str(interaction.user),
            },
            "guild_settings": {
                "name": guild.name,
                "description": guild.description,
                "afk_timeout": guild.afk_timeout,
                "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "explicit_content_filter": guild.explicit_content_filter.value,
                "system_channel_id": guild.system_channel.id if guild.system_channel else None,
                "preferred_locale": str(guild.preferred_locale),
            },
            "roles": [],
            "categories": [],
            "text_channels": [],
            "voice_channels": [],
            "stage_channels": [],
            "forum_channels": [],
        }

        # ---- Roles ----
        for role in guild.roles:
            if role.is_default():
                continue
            role_data = {
                "id": role.id,
                "name": role.name,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
                "permissions": role.permissions.value,
                "managed": role.managed,
            }
            data["roles"].append(role_data)

        # ---- Categories ----
        for category in guild.categories:
            overwrites = []
            for target, overwrite in category.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            data["categories"].append({
                "id": category.id,
                "name": category.name,
                "position": category.position,
                "nsfw": category.nsfw,
                "overwrites": overwrites,
            })

        # ---- Text Channels ----
        for channel in guild.text_channels:
            overwrites = []
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            data["text_channels"].append({
                "id": channel.id,
                "name": channel.name,
                "topic": channel.topic,
                "position": channel.position,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "category_id": channel.category_id,
                "overwrites": overwrites,
            })

        # ---- Voice Channels ----
        for channel in guild.voice_channels:
            overwrites = []
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            data["voice_channels"].append({
                "id": channel.id,
                "name": channel.name,
                "position": channel.position,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
                "category_id": channel.category_id,
                "overwrites": overwrites,
            })

        # ---- Stage Channels ----
        for channel in guild.stage_channels:
            overwrites = []
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            data["stage_channels"].append({
                "id": channel.id,
                "name": channel.name,
                "position": channel.position,
                "topic": getattr(channel, "topic", None),
                "category_id": channel.category_id,
                "overwrites": overwrites,
            })

        # ---- Forum Channels ----
        for channel in guild.forums:
            overwrites = []
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append({
                    "id": target.id,
                    "type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value,
                })
            data["forum_channels"].append({
                "id": channel.id,
                "name": channel.name,
                "position": channel.position,
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "category_id": channel.category_id,
                "overwrites": overwrites,
            })

        save_backup(name, data)

        role_count = len(data["roles"])
        channel_count = (
            len(data["text_channels"])
            + len(data["voice_channels"])
            + len(data["stage_channels"])
            + len(data["forum_channels"])
        )
        category_count = len(data["categories"])

        embed = discord.Embed(
            title=f"{self.e.success} Backup Created",
            description=f"Server backup **`{name}`** has been saved successfully.",
            color=COLOR_SUCCESS,
            timestamp=datetime.datetime.utcnow()
        )
        embed.description = (
            f"{embed.description}\n"
            f"> Roles: {role_count}\n"
            f"> Categories: {category_count}\n"
            f"> Channels: {channel_count}"
        )
        embed.set_footer(text=f"Created by {interaction.user}")

        await interaction.followup.send(embed=embed)


    # ================== /import-backup ==================

    @app_commands.command(name="import-backup", description="Restore a server backup (Administrator only)")
    @app_commands.describe(backup="Select a backup to restore")
    async def import_backup(self, interaction: discord.Interaction, backup: str):
        if not await self.admin_guard(interaction):
            return

        data = load_backup(backup)
        if not data:
            embed = discord.Embed(
                title=f"{self.e.error} Backup Not Found",
                description=f"No backup named **`{backup}`** exists.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild
        log = []

        # ---- Restore Guild Settings ----
        try:
            gs = data.get("guild_settings", {})
            await guild.edit(
                name=gs.get("name", guild.name),
                afk_timeout=gs.get("afk_timeout", guild.afk_timeout),
                verification_level=discord.VerificationLevel(gs.get("verification_level", guild.verification_level.value)),
                default_notifications=discord.NotificationLevel(gs.get("default_notifications", guild.default_notifications.value)),
                explicit_content_filter=discord.ContentFilter(gs.get("explicit_content_filter", guild.explicit_content_filter.value)),
            )
            log.append(f"{self.e.success} Guild settings restored")
        except Exception as e:
            log.append(f"{self.e.error} Guild settings failed: {e}")

        # ---- Build old ID -> new object maps ----
        role_map: dict[int, discord.Role] = {}

        # ---- Restore Roles ----
        existing_roles = {r.name: r for r in guild.roles}
        for role_data in sorted(data.get("roles", []), key=lambda r: r["position"]):
            if role_data["managed"]:
                continue
            try:
                if role_data["name"] in existing_roles:
                    role = existing_roles[role_data["name"]]
                    await role.edit(
                        color=discord.Color(role_data["color"]),
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        permissions=discord.Permissions(role_data["permissions"]),
                    )
                else:
                    role = await guild.create_role(
                        name=role_data["name"],
                        color=discord.Color(role_data["color"]),
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"],
                        permissions=discord.Permissions(role_data["permissions"]),
                    )
                role_map[role_data["id"]] = role
            except Exception as e:
                log.append(f"{self.e.error} Role `{role_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Roles restored ({len(role_map)})")

        # ---- Helper: build overwrites dict ----
        def build_overwrites(raw_overwrites: list) -> dict:
            overwrites = {}
            for ow in raw_overwrites:
                if ow["type"] == "role":
                    target = role_map.get(ow["id"]) or guild.get_role(ow["id"])
                else:
                    target = guild.get_member(ow["id"])
                if target is None:
                    continue
                overwrite = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(ow["allow"]),
                    discord.Permissions(ow["deny"]),
                )
                overwrites[target] = overwrite
            return overwrites

        # ---- Restore Categories ----
        category_map: dict[int, discord.CategoryChannel] = {}
        existing_categories = {c.name: c for c in guild.categories}
        for cat_data in sorted(data.get("categories", []), key=lambda c: c["position"]):
            try:
                overwrites = build_overwrites(cat_data.get("overwrites", []))
                if cat_data["name"] in existing_categories:
                    cat = existing_categories[cat_data["name"]]
                    await cat.edit(overwrites=overwrites)
                else:
                    cat = await guild.create_category(
                        name=cat_data["name"],
                        overwrites=overwrites,
                    )
                category_map[cat_data["id"]] = cat
            except Exception as e:
                log.append(f"{self.e.fail} Category `{cat_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Categories restored ({len(category_map)})")

        # ---- Restore Text Channels ----
        text_restored = 0
        existing_text = {c.name: c for c in guild.text_channels}
        for ch_data in sorted(data.get("text_channels", []), key=lambda c: c["position"]):
            try:
                overwrites = build_overwrites(ch_data.get("overwrites", []))
                category = category_map.get(ch_data.get("category_id"))
                if ch_data["name"] in existing_text:
                    ch = existing_text[ch_data["name"]]
                    await ch.edit(
                        topic=ch_data.get("topic"),
                        nsfw=ch_data.get("nsfw", False),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                else:
                    await guild.create_text_channel(
                        name=ch_data["name"],
                        topic=ch_data.get("topic"),
                        nsfw=ch_data.get("nsfw", False),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                text_restored += 1
            except Exception as e:
                log.append(f"{self.e.fail} Text channel `{ch_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Text channels restored ({text_restored})")

        # ---- Restore Voice Channels ----
        voice_restored = 0
        existing_voice = {c.name: c for c in guild.voice_channels}
        for ch_data in sorted(data.get("voice_channels", []), key=lambda c: c["position"]):
            try:
                overwrites = build_overwrites(ch_data.get("overwrites", []))
                category = category_map.get(ch_data.get("category_id"))
                if ch_data["name"] in existing_voice:
                    ch = existing_voice[ch_data["name"]]
                    await ch.edit(
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                else:
                    await guild.create_voice_channel(
                        name=ch_data["name"],
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                voice_restored += 1
            except Exception as e:
                log.append(f"{self.e.fail} Voice channel `{ch_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Voice channels restored ({voice_restored})")

        # ---- Restore Stage Channels ----
        stage_restored = 0
        existing_stage = {c.name: c for c in guild.stage_channels}
        for ch_data in sorted(data.get("stage_channels", []), key=lambda c: c["position"]):
            try:
                overwrites = build_overwrites(ch_data.get("overwrites", []))
                category = category_map.get(ch_data.get("category_id"))
                if ch_data["name"] in existing_stage:
                    ch = existing_stage[ch_data["name"]]
                    await ch.edit(overwrites=overwrites, category=category)
                else:
                    await guild.create_stage_channel(
                        name=ch_data["name"],
                        overwrites=overwrites,
                        category=category,
                    )
                stage_restored += 1
            except Exception as e:
                log.append(f"{self.e.fail} Stage channel `{ch_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Stage channels restored ({stage_restored})")

        # ---- Restore Forum Channels ----
        forum_restored = 0
        existing_forums = {c.name: c for c in guild.forums}
        for ch_data in sorted(data.get("forum_channels", []), key=lambda c: c["position"]):
            try:
                overwrites = build_overwrites(ch_data.get("overwrites", []))
                category = category_map.get(ch_data.get("category_id"))
                if ch_data["name"] in existing_forums:
                    ch = existing_forums[ch_data["name"]]
                    await ch.edit(
                        topic=ch_data.get("topic"),
                        nsfw=ch_data.get("nsfw", False),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                else:
                    await guild.create_forum(
                        name=ch_data["name"],
                        topic=ch_data.get("topic"),
                        nsfw=ch_data.get("nsfw", False),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        overwrites=overwrites,
                        category=category,
                    )
                forum_restored += 1
            except Exception as e:
                log.append(f"{self.e.fail} Forum `{ch_data['name']}` Failed: {e}")

        log.append(f"{self.e.success} Forums restored ({forum_restored})")

        # ---- Summary embed ----
        description = "\n".join(log)
        embed = discord.Embed(
            title=f"{self.e.download} Backup Restored",
            description=f"Restored backup **`{backup}`**\n\n{description}",
            color=COLOR_SUCCESS,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"Restored by {interaction.user}")
        await interaction.followup.send(embed=embed)


    # ================== /del-backup ==================

    @app_commands.command(name="del-backup", description="Delete a saved backup (Administrator only)")
    @app_commands.describe(backup="Select a backup to delete")
    async def del_backup(self, interaction: discord.Interaction, backup: str):
        if not await self.admin_guard(interaction):
            return

        if not delete_backup(backup):
            embed = discord.Embed(
                title=f"{self.e.error} Backup Not Found",
                description=f"No backup named **`{backup}`** was found.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{self.e.trash} Backup Deleted",
            description=f"Backup **`{backup}`** has been permanently deleted.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)


    # ================== AUTOCOMPLETE ==================

    @import_backup.autocomplete("backup")
    @del_backup.autocomplete("backup")
    async def backup_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        backups = list_backups()
        return [
            app_commands.Choice(name=b, value=b)
            for b in backups
            if current.lower() in b.lower()
        ][:25]


# ================== SETUP ==================

async def setup(bot: commands.Bot):
    await bot.add_cog(Backup(bot))