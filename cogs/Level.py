import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import json
import random
import io
import asyncio
import time
import yaml
from PIL import Image, ImageDraw, ImageFont

# ================== CONFIG ==================


XP_PER_MESSAGE_MIN   = 15
XP_PER_MESSAGE_MAX   = 40
XP_COOLDOWN_SECONDS  = 45

XP_PER_REACTION      = 10
REACTION_COOLDOWN_SEC = 60

XP_VOICE_MIN         = 50
XP_VOICE_MAX         = 75
VOICE_INTERVAL_SEC   = 60
VOICE_INACTIVITY_SEC = 300

# XP scaling: at higher levels, XP earned is divided by this factor.
# At level N, XP gain = base_xp / (1 + N * XP_LEVEL_SCALE_FACTOR)
# e.g. level 10 → 1/(1+1.0) = 50% of base; level 20 → 1/(1+2.0) = 33%
XP_LEVEL_SCALE_FACTOR = 0.1

# ================== STORAGE ==================

DATA_DIR  = Path("data")
DATA_FILE = DATA_DIR / "levels.json"
GUILD_CONFIG_DIR = DATA_DIR / "guild_configs"

COLOR_SUCCESS = discord.Color.green()
COLOR_ERROR   = discord.Color.red()
COLOR_TEAL    = discord.Color.from_rgb(0, 0, 0)

def xp_for_level(level: int) -> int:
    return int(100 * (level ** 1.5))

def scale_xp(base_xp: int, current_level: int) -> int:
    """Return XP amount scaled down for higher levels so levelling gets harder."""
    return max(1, int(base_xp / (1 + current_level * XP_LEVEL_SCALE_FACTOR)))

def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level

def load_data() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"guilds": {}}, indent=4))
    return json.loads(DATA_FILE.read_text())

def save_data(data: dict):
    DATA_FILE.write_text(json.dumps(data, indent=4))

def get_user(data: dict, guild_id: int, user_id: int) -> dict:
    g = data["guilds"].setdefault(str(guild_id), {"users": {}})
    return g["users"].setdefault(str(user_id), {"xp": 0, "messages": 0})

def get_rank(data: dict, guild_id: int, user_id: int) -> int:
    users = data["guilds"].get(str(guild_id), {}).get("users", {})
    sorted_users = sorted(users.items(), key=lambda u: u[1].get("xp", 0), reverse=True)
    for i, (uid, _) in enumerate(sorted_users, 1):
        if uid == str(user_id):
            return i
    return len(sorted_users) + 1

def fmt_xp(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

# ================== FONTS ==================

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def _circle_mask_paste(base: Image.Image, layer: Image.Image, pos: tuple):
    """Smooth anti-aliased circular paste — mask built at 4x then downsampled."""
    ms       = layer.width * 4
    big_mask = Image.new("L", (ms, ms), 0)
    ImageDraw.Draw(big_mask).ellipse([0, 0, ms, ms], fill=255)
    mask = big_mask.resize(layer.size, Image.LANCZOS)
    base.paste(layer, pos, mask)


# ================== RANK CARD ==================
# Output: 800×160  |  Rendered at 2x (1600×320) then downsampled → crisp edges

SCALE    = 2
OUT_W    = 800
OUT_H    = 160
W        = OUT_W * SCALE   # 1600
H        = OUT_H * SCALE   # 320

AV_SIZE  = 100 * SCALE     # 200px at render size
AV_PAD_X = 18  * SCALE
AV_PAD_Y = (H - AV_SIZE) // 2

BAR_H    = 14 * SCALE

C_BG       = (57,  58,  65)
C_TEAL     = (0,  188, 188)
C_TEAL_DIM = (0,   90,  90)
C_WHITE    = (255, 255, 255)
C_SUBTEXT  = (170, 178, 195)


def _make_card(username: str, level: int, xp: int, rank: int, avatar_bytes: bytes | None) -> io.BytesIO:
    current_xp = xp - xp_for_level(level)
    needed_xp  = xp_for_level(level + 1) - xp_for_level(level)
    progress   = max(0.0, min(1.0, current_xp / needed_xp if needed_xp else 1.0))

    img  = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    # Teal chevron top-right
    chevron = [
        (W - 130 * SCALE, 0),
        (W,                0),
        (W,                H - BAR_H),
        (W -  60 * SCALE,  H - BAR_H),
    ]
    draw.polygon(chevron, fill=C_TEAL)

    # Circle avatar
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((AV_SIZE, AV_SIZE), Image.LANCZOS)
            _circle_mask_paste(img, av, (AV_PAD_X, AV_PAD_Y))
        except Exception:
            draw.ellipse([AV_PAD_X, AV_PAD_Y, AV_PAD_X + AV_SIZE, AV_PAD_Y + AV_SIZE], fill=(60, 64, 78))
    else:
        draw.ellipse([AV_PAD_X, AV_PAD_Y, AV_PAD_X + AV_SIZE, AV_PAD_Y + AV_SIZE], fill=(60, 64, 78))

    draw = ImageDraw.Draw(img)

    # Text starts just after avatar
    tx = AV_PAD_X + AV_SIZE + 22 * SCALE

    f_name  = _font(FONT_BOLD, 30 * SCALE)
    f_stats = _font(FONT_REG,  22 * SCALE)

    name_text  = f"@{username}"
    stats_text = f"Level: {level}   XP: {fmt_xp(current_xp)} / {fmt_xp(needed_xp)}   Rank: {rank}"

    # Vertical layout — username ~18% down, underline, then stats
    name_y  = int(H * 0.18)
    line_y  = name_y + 30 * SCALE + 6 * SCALE
    stats_y = line_y + 8 * SCALE

    # Left-aligned @username
    draw.text((tx, name_y), name_text, font=f_name, fill=C_WHITE)

    # Teal underline aligned to username width
    name_w = int(draw.textlength(name_text, font=f_name))
    draw.rectangle([tx, line_y, tx + name_w, line_y + 2 * SCALE], fill=C_TEAL)

    # Left-aligned stats
    draw.text((tx, stats_y), stats_text, font=f_stats, fill=C_SUBTEXT)

    # Progress bar flush at bottom, full width
    bar_top = H - BAR_H
    draw.rectangle([0, bar_top, W, H], fill=C_TEAL_DIM)
    fill_w = int(W * progress)
    if fill_w > 0:
        draw.rectangle([0, bar_top, fill_w, H], fill=C_TEAL)

    # Downsample to output size
    out = img.resize((OUT_W, OUT_H), Image.LANCZOS)

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ================== LEADERBOARD IMAGE ==================
# Also rendered at 2x then downsampled for crispness

LB_SCALE    = 2
LB_OUT_W    = 680
LB_OUT_H_R  = 64    # output row height
LB_OUT_GAP  = 1

LB_W        = LB_OUT_W   * LB_SCALE
LB_ROW_H    = LB_OUT_H_R * LB_SCALE
LB_GAP      = LB_OUT_GAP * LB_SCALE
LB_AV       = LB_ROW_H               # square avatar = full row height
LB_BAR_H    = 4 * LB_SCALE

C_ROW_ODD     = (32,  34,  43)
C_ROW_EVEN    = (36,  38,  48)
C_GOLD_LB     = (255, 196,   0)
C_SILVER      = (192, 192, 192)
C_BRONZE      = (205, 127,  50)
C_TEXT_LB     = (220, 222, 230)
C_BULLET      = (110, 120, 140)
C_TEAL_LB     = (0,  188, 188)
C_TEAL_DIM_LB = (0,   70,  70)

RANK_COLORS_LB = {1: C_GOLD_LB, 2: C_SILVER, 3: C_BRONZE}


def _make_leaderboard(entries: list) -> io.BytesIO:
    n          = len(entries)
    render_h   = n * (LB_ROW_H + LB_GAP)
    out_h      = n * (LB_OUT_H_R + LB_OUT_GAP)

    img  = Image.new("RGB", (LB_W, render_h), C_BG)
    draw = ImageDraw.Draw(img)

    f_rank = _font(FONT_BOLD, 21 * LB_SCALE)
    f_main = _font(FONT_BOLD, 19 * LB_SCALE)

    for i, entry in enumerate(entries):
        row_top = i * (LB_ROW_H + LB_GAP)
        row_bg  = C_ROW_ODD if i % 2 == 0 else C_ROW_EVEN
        draw.rectangle([0, row_top, LB_W, row_top + LB_ROW_H], fill=row_bg)

        # Square avatar flush left, full row height
        if entry.get("avatar_bytes"):
            try:
                av = Image.open(io.BytesIO(entry["avatar_bytes"])).convert("RGB")
                av = av.resize((LB_AV, LB_AV), Image.LANCZOS)
                img.paste(av, (0, row_top))
            except Exception:
                draw.rectangle([0, row_top, LB_AV, row_top + LB_AV], fill=(50, 52, 65))
        else:
            draw.rectangle([0, row_top, LB_AV, row_top + LB_AV], fill=(50, 52, 65))

        draw = ImageDraw.Draw(img)

        rank       = entry["rank"]
        rank_color = RANK_COLORS_LB.get(rank, C_TEXT_LB)

        rank_str = f"#{rank}"
        bullet   = "  •  "
        name_str = f"@{entry['name']}"
        lvl_str  = f"  •  LVL: {entry['level']}"

        text_x      = LB_AV + 16 * LB_SCALE
        text_area_h = LB_ROW_H - LB_BAR_H
        _, _, _, th = f_main.getbbox("Ag")
        text_y      = row_top + (text_area_h - th) // 2

        draw.text((text_x, text_y), rank_str, font=f_rank, fill=rank_color)
        cx = text_x + int(draw.textlength(rank_str, font=f_rank))

        draw.text((cx, text_y), bullet, font=f_main, fill=C_BULLET)
        cx += int(draw.textlength(bullet, font=f_main))

        draw.text((cx, text_y), name_str, font=f_main, fill=C_TEXT_LB)
        cx += int(draw.textlength(name_str, font=f_main))

        draw.text((cx, text_y), lvl_str, font=f_main, fill=C_TEXT_LB)

        # Progress bar at very bottom of row
        current_xp = entry["xp"] - xp_for_level(entry["level"])
        needed_xp  = xp_for_level(entry["level"] + 1) - xp_for_level(entry["level"])
        progress   = max(0.0, min(1.0, current_xp / needed_xp if needed_xp else 1.0))

        bar_top = row_top + LB_ROW_H - LB_BAR_H
        draw.rectangle([LB_AV, bar_top, LB_W, row_top + LB_ROW_H], fill=C_TEAL_DIM_LB)
        fill_end = LB_AV + int((LB_W - LB_AV) * progress)
        if fill_end > LB_AV:
            draw.rectangle([LB_AV, bar_top, fill_end, row_top + LB_ROW_H], fill=C_TEAL_LB)

    # Downsample to output size
    out = img.resize((LB_OUT_W, out_h), Image.LANCZOS)

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ================== COG ==================

class Levels(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        self._msg_cooldowns:      dict[str, float] = {}
        self._reaction_cooldowns: dict[str, float] = {}
        self._voice_join_times:   dict[str, float] = {}
        self._voice_last_active:  dict[str, float] = {}
        self._voice_task: asyncio.Task | None = None
        self._load_level_config()

    def _guild_level_config(self, guild_id: int | None = None) -> dict:
        """Load level settings, preferring the per-guild local configuration."""
        cfg = dict((getattr(self.bot, "config", {}) or {}).get("levels") or {})
        if not guild_id:
            return cfg

        path = GUILD_CONFIG_DIR / f"{guild_id}.yaml"
        if not path.exists():
            return cfg

        try:
            guild_cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return cfg

        guild_levels = guild_cfg.get("levels") or {}
        if isinstance(guild_levels, dict):
            cfg.update(guild_levels)
        return cfg

    def _load_level_config(self):
        """Load global level defaults from bot config."""
        cfg = self._guild_level_config()
        raw_ch = str(cfg.get("level_up_channel") or "0").strip()
        self._level_up_channel_id = int(raw_ch) if raw_ch.isdigit() else 0
        # level_roles: list of {level: int, role_id: str}
        self._level_roles: list[dict] = cfg.get("level_roles") or []
        # no_xp_channels: list of channel IDs where users cannot earn XP
        raw_no_xp = cfg.get("no_xp_channels") or []
        self._no_xp_channel_ids: set[int] = set()
        for ch_id in raw_no_xp:
            try:
                self._no_xp_channel_ids.add(int(str(ch_id).strip()))
            except (ValueError, TypeError):
                pass

    async def _assign_level_roles(self, member: discord.Member, new_level: int):
        """Assign any configured roles for the reached level."""
        if not member:
            return
        _, level_roles, _ = self._level_settings_for_guild(member.guild.id)
        if not level_roles:
            return
        for entry in level_roles:
            try:
                req = int(entry.get("level", 0))
                role_id = int(str(entry.get("role_id", 0)).strip())
            except (ValueError, TypeError):
                continue
            if new_level >= req and role_id:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Level {req} reward")
                    except discord.HTTPException:
                        pass

    def cog_load(self):
        self._voice_task = asyncio.get_event_loop().create_task(self._voice_xp_loop())

    def cog_unload(self):
        if self._voice_task:
            self._voice_task.cancel()

    # ================== VOICE XP LOOP ==================

    def _level_settings_for_guild(self, guild_id: int | None = None) -> tuple[int, list[dict], set[int]]:
        cfg = self._guild_level_config(guild_id)
        raw_ch = str(cfg.get("level_up_channel") or "0").strip()
        channel_id = int(raw_ch) if raw_ch.isdigit() else 0
        level_roles = cfg.get("level_roles") or []

        no_xp_channel_ids: set[int] = set()
        for ch_id in cfg.get("no_xp_channels") or []:
            try:
                no_xp_channel_ids.add(int(str(ch_id).strip()))
            except (ValueError, TypeError):
                pass
        return channel_id, level_roles, no_xp_channel_ids

    def _get_levelup_channel(self, guild_id: int | None = None, fallback_channel=None):
        """Return the configured level-up channel.
        Falls back to fallback_channel ONLY when no level_up_channel is configured.
        If a level_up_channel IS configured but cannot be found, returns None (no message).
        """
        channel_id, _, _ = self._level_settings_for_guild(guild_id)
        if channel_id:
            return self.bot.get_channel(channel_id)
        # No channel configured: send in the channel where the event occurred
        return fallback_channel

    async def _voice_xp_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(VOICE_INTERVAL_SEC)
            now  = time.time()
            data = load_data()
            changed = False

            for key, join_ts in list(self._voice_join_times.items()):
                last_active = self._voice_last_active.get(key, join_ts)
                if now - last_active > VOICE_INACTIVITY_SEC:
                    continue
                guild_id_str, user_id_str = key.split(":", 1)
                guild_id = int(guild_id_str)
                user_id  = int(user_id_str)
                u        = get_user(data, guild_id, user_id)
                old_lvl  = level_from_xp(u["xp"])
                base_xp  = random.randint(XP_VOICE_MIN, XP_VOICE_MAX)
                u["xp"] += scale_xp(base_xp, old_lvl)
                new_lvl  = level_from_xp(u["xp"])
                changed  = True

                if new_lvl > old_lvl:
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        member  = guild.get_member(user_id)
                        channel = self._get_levelup_channel(guild_id)
                        if member:
                            await self._assign_level_roles(member, new_lvl)
                        if channel and member:
                            embed = discord.Embed(
                                title=f"{self.e.trophy} Level Up!",
                                description="\n".join([
                                    f"{member.mention} just levelled up!",
                                    f"> **New Level:** `{new_lvl}`",
                                    f"> **Total XP:** `{u['xp']:,}`",
                                ]),
                                color=COLOR_TEAL,
                            )
                            embed.set_thumbnail(url=member.display_avatar.url)
                            await channel.send(embed=embed)

            if changed:
                save_data(data)

    # ================== PERMISSION CHECK ==================

    async def check_perms(self, interaction: discord.Interaction, *permissions: str) -> bool:
        user_perms = interaction.user.guild_permissions
        if user_perms.administrator:
            return True
        for permission in permissions:
            if getattr(user_perms, permission, False):
                return True
        readable = " or ".join(f"`{p.replace('_', ' ').title()}`" for p in permissions)
        embed = discord.Embed(
            title=f"{self.e.error} Permission Denied",
            description="\n".join([
                "You do not have permission to use this command.",
                f"> Required: {readable}",
                f"> Attempted By: {interaction.user.mention}",
            ]),
            color=COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    # ================== MESSAGE LISTENER ==================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Skip channels where XP cannot be earned
        _, _, no_xp_channel_ids = self._level_settings_for_guild(message.guild.id)
        if message.channel.id in no_xp_channel_ids:
            return

        key = f"{message.guild.id}:{message.author.id}"
        now = time.time()
        if now - self._msg_cooldowns.get(key, 0) < XP_COOLDOWN_SECONDS:
            return
        self._msg_cooldowns[key] = now

        voice_key = f"{message.guild.id}:{message.author.id}"
        if voice_key in self._voice_join_times:
            self._voice_last_active[voice_key] = now

        data    = load_data()
        g       = data["guilds"].setdefault(str(message.guild.id), {"users": {}})
        user    = g["users"].setdefault(str(message.author.id), {"xp": 0, "messages": 0})
        old_lvl = level_from_xp(user["xp"])
        base_xp = random.randint(XP_PER_MESSAGE_MIN, XP_PER_MESSAGE_MAX)
        user["xp"]       += scale_xp(base_xp, old_lvl)
        user["messages"] += 1
        new_lvl           = level_from_xp(user["xp"])
        save_data(data)

        if new_lvl > old_lvl:
            member = message.guild.get_member(message.author.id)
            if member:
                await self._assign_level_roles(member, new_lvl)
            channel = self._get_levelup_channel(message.guild.id, message.channel)
            if channel:
                embed = discord.Embed(
                    title=f"{self.e.trophy} Level Up!",
                    description="\n".join([
                        f"{message.author.mention} just levelled up!",
                        f"> **New Level:** `{new_lvl}`",
                        f"> **Total XP:** `{user['xp']:,}`",
                    ]),
                    color=COLOR_TEAL,
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await channel.send(embed=embed)

    # ================== REACTION LISTENER ==================

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        guild = reaction.message.guild
        if not guild:
            return

        # Skip channels where XP cannot be earned
        _, _, no_xp_channel_ids = self._level_settings_for_guild(guild.id)
        if reaction.message.channel.id in no_xp_channel_ids:
            return

        key = f"{guild.id}:{user.id}:{reaction.message.id}"
        now = time.time()
        if now - self._reaction_cooldowns.get(key, 0) < REACTION_COOLDOWN_SEC:
            return
        self._reaction_cooldowns[key] = now

        voice_key = f"{guild.id}:{user.id}"
        if voice_key in self._voice_join_times:
            self._voice_last_active[voice_key] = now

        data    = load_data()
        u       = get_user(data, guild.id, user.id)
        old_lvl = level_from_xp(u["xp"])
        u["xp"] += scale_xp(XP_PER_REACTION, old_lvl)
        new_lvl  = level_from_xp(u["xp"])
        save_data(data)

        if new_lvl > old_lvl:
            member = guild.get_member(user.id)
            if member:
                await self._assign_level_roles(member, new_lvl)
            channel = self._get_levelup_channel(guild.id, reaction.message.channel)
            if channel:
                embed  = discord.Embed(
                    title=f"{self.e.trophy} Level Up!",
                    description="\n".join([
                        f"{member.mention if member else user.mention} just levelled up!",
                        f"> **New Level:** `{new_lvl}`",
                        f"> **Total XP:** `{u['xp']:,}`",
                    ]),
                    color=COLOR_TEAL,
                )
                if member:
                    embed.set_thumbnail(url=member.display_avatar.url)
                await channel.send(embed=embed)

    # ================== VOICE STATE LISTENER ==================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        key = f"{member.guild.id}:{member.id}"
        now = time.time()
        if before.channel is None and after.channel is not None:
            self._voice_join_times[key]  = now
            self._voice_last_active[key] = now
        elif before.channel is not None and after.channel is None:
            self._voice_join_times.pop(key, None)
            self._voice_last_active.pop(key, None)
        else:
            self._voice_last_active[key] = now

    # ================== /level ==================

    @app_commands.command(name="level", description="View your level card (or another user's)")
    @app_commands.describe(user="The user to look up (defaults to yourself)")
    async def level(self, interaction: discord.Interaction, user: discord.Member = None):
        user = user or interaction.user
        await interaction.response.defer()

        data = load_data()
        u    = get_user(data, interaction.guild.id, user.id)
        xp   = u["xp"]
        lvl  = level_from_xp(xp)
        rank = get_rank(data, interaction.guild.id, user.id)

        avatar_bytes = None
        try:
            avatar_bytes = await user.display_avatar.read()
        except Exception:
            pass

        loop = asyncio.get_event_loop()
        buf  = await loop.run_in_executor(
            None,
            lambda: _make_card(
                username=user.display_name,
                level=lvl, xp=xp, rank=rank,
                avatar_bytes=avatar_bytes,
            ),
        )

        await interaction.followup.send(file=discord.File(fp=buf, filename="level.png"))

    # ================== /lblevel ==================

    @app_commands.command(name="lblevel", description="View the server XP leaderboard")
    async def lblevel(self, interaction: discord.Interaction):
        await interaction.response.defer()

        data      = load_data()
        users_raw = data["guilds"].get(str(interaction.guild.id), {}).get("users", {})

        if not users_raw:
            await interaction.followup.send(embed=discord.Embed(
                title=f"{self.e.error} No Data",
                description="No one has earned XP in this server yet.",
                color=COLOR_ERROR,
            ))
            return

        sorted_users = sorted(
            users_raw.items(),
            key=lambda u: u[1].get("xp", 0),
            reverse=True,
        )[:10]

        entries = []
        for i, (uid, udata) in enumerate(sorted_users, 1):
            xp_val = udata.get("xp", 0)
            lvl    = level_from_xp(xp_val)
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else "Unknown"

            avatar_bytes = None
            if member:
                try:
                    avatar_bytes = await member.display_avatar.read()
                except Exception:
                    pass

            entries.append({
                "rank":         i,
                "name":         name,
                "level":        lvl,
                "xp":           xp_val,
                "avatar_bytes": avatar_bytes,
            })

        loop = asyncio.get_event_loop()
        buf  = await loop.run_in_executor(None, lambda: _make_leaderboard(entries))

        file  = discord.File(fp=buf, filename="leaderboard.png")
        embed = discord.Embed(title=interaction.guild.name, color=COLOR_TEAL)
        embed.set_image(url="attachment://leaderboard.png")
        await interaction.followup.send(embed=embed, file=file)

    # ================== /resetxp ==================

    @app_commands.command(name="resetxp", description="Reset a user's XP and message count (Administrator only)")
    @app_commands.describe(user="The user to reset")
    async def resetxp(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.check_perms(interaction, "administrator"):
            return

        data = load_data()
        g    = data["guilds"].get(str(interaction.guild.id), {})
        if str(user.id) in g.get("users", {}):
            g["users"][str(user.id)] = {"xp": 0, "messages": 0}
            save_data(data)

        await interaction.response.send_message(embed=discord.Embed(
            title=f"{self.e.success} XP Reset",
            description=f"> Reset XP and message count for {user.mention}.",
            color=COLOR_SUCCESS,
        ))

    # ================== /setxp ==================

    @app_commands.command(name="setxp", description="Manually set a user's XP (Administrator only)")
    @app_commands.describe(user="The user to update", xp="The exact XP amount to set")
    async def setxp(self, interaction: discord.Interaction, user: discord.Member, xp: int):
        if not await self.check_perms(interaction, "administrator"):
            return

        if xp < 0:
            await interaction.response.send_message(embed=discord.Embed(
                title=f"{self.e.error} Invalid XP",
                description="> XP cannot be negative.",
                color=COLOR_ERROR,
            ), ephemeral=True)
            return

        data    = load_data()
        u       = get_user(data, interaction.guild.id, user.id)
        u["xp"] = xp
        save_data(data)

        lvl = level_from_xp(xp)
        await interaction.response.send_message(embed=discord.Embed(
            title=f"{self.e.success} XP Updated",
            description="\n".join([
                f"> User: {user.mention}",
                f"> New XP: `{xp:,}`",
                f"> New Level: `{lvl}`",
            ]),
            color=COLOR_SUCCESS,
        ))


# ================== SETUP ==================

async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
