import discord
from utils.emojis import Emojis, _DEFAULTS as _EMOJI_DEFAULTS
from discord.ext import commands
from discord import app_commands
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import asyncio
import io
import yaml as _yaml
import logging

_log = logging.getLogger("bot.tickets")

TICKET_DATA_PATH = "data/tickets.json"
GUILD_CONFIGS_DIR = Path("data") / "guild_configs"


# ── Guild config helpers ───────────────────────────────────────────────────────

def _load_guild_cfg(guild_id) -> dict:
    path = GUILD_CONFIGS_DIR / f"{guild_id}.yaml"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def _tcfg(bot, guild_id=None) -> dict:
    if guild_id:
        gcfg = _load_guild_cfg(guild_id)
        if gcfg.get("tickets"):
            return gcfg["tickets"]
    return (getattr(bot, "config", {}) or {}).get("tickets") or {}


def _chcfg(bot, guild_id=None) -> dict:
    if guild_id:
        gcfg = _load_guild_cfg(guild_id)
        if gcfg.get("channels"):
            return gcfg["channels"]
    return (getattr(bot, "config", {}) or {}).get("channels") or {}


def _s(val, fallback="") -> str:
    return str(val).strip() if val else fallback


def _i(val, fallback=0) -> int:
    try:
        return int(str(val).split(".")[0])
    except Exception:
        return fallback


def _ticket_log_ch(bot, guild_id=None) -> int:
    return _i(_chcfg(bot, guild_id).get("ticket_log"))


def _panel_channel_id(cfg: dict) -> int:
    return _i(cfg.get("panel_channel"))


def _category_name(cfg: dict) -> str:
    return _s(cfg.get("category_name"), "Tickets")


def _channel_prefix(cfg: dict) -> str:
    return _s(cfg.get("channel_prefix"), "🎫︱ticket-")


def _autoclose_prefix(cfg: dict) -> str:
    return _s(cfg.get("autoclose_prefix"), "⌛︱")


def _autoclose_emoji(cfg: dict) -> str:
    return _s(cfg.get("autoclose_emoji"), "<:hourglass:1504581446277267507>")


def _autoclose_hours(cfg: dict) -> int:
    return _i(cfg.get("autoclose_hours"), 24)


def _transcript_limit(cfg: dict) -> int:
    return _i(cfg.get("transcript_history_limit"), 500)


def _panel_title(cfg: dict) -> str:
    return _s(cfg.get("panel_title"), "Create a Ticket")


def _panel_desc(cfg: dict) -> str:
    raw = cfg.get("panel_description") or (
        "If you are in need of any assistance, create a ticket by clicking the button below "
        "and filling out the form. Do **NOT** make joke or spam tickets, as we can blacklist you."
    )
    # Replace literal \n escape sequences from the local config, then preserve real newlines
    text = str(raw).replace("\\n", "\n")
    # Collapse spaces within each line but keep line breaks intact
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(lines).strip()


def _welcome_text(cfg: dict) -> str:
    raw = cfg.get("welcome_text") or (
        "While you wait, describe your issue in detail and include screenshots "
        "and/or video recordings as well as any error messages if they are present. "
        "The more details you include, the faster we can help you."
    )
    # Replace literal \n escape sequences from the local config, then preserve real newlines
    text = str(raw).replace("\\n", "\n")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(lines).strip()


def _button_count(cfg: dict) -> int:
    buttons = cfg.get("buttons")
    if isinstance(buttons, list) and buttons:
        return max(1, min(3, len(buttons)))
    n = _i(cfg.get("button_count"), 1)
    return max(1, min(3, n))


def _ticket_buttons(cfg: dict) -> list[dict]:
    configured = cfg.get("buttons")
    if isinstance(configured, list) and configured:
        buttons = [b for b in configured[:3] if isinstance(b, dict)]
        if buttons:
            return buttons

    labels = _button_labels(cfg)
    buttons = []
    for i in range(_button_count(cfg)):
        buttons.append({
            "label": labels[i],
            "emoji": cfg.get(f"button_{i + 1}_emoji") or _EMOJI_DEFAULTS["ticket"],
            "questions": [
                {
                    "label": cfg.get(f"question_{j}_label"),
                    "placeholder": cfg.get(f"question_{j}_placeholder"),
                    "required": True,
                }
                for j in range(1, 4)
                if cfg.get(f"question_{j}_label")
            ],
        })
    return buttons


def _button_labels(cfg: dict) -> list[str]:
    buttons = cfg.get("buttons")
    if isinstance(buttons, list) and buttons:
        defaults = ["Create Ticket", "Report User", "Other"]
        return [
            _s(button.get("label"), defaults[i] if i < len(defaults) else "Create Ticket")
            for i, button in enumerate(buttons[:3])
            if isinstance(button, dict)
        ]

    defaults = ["Create Ticket", "Report User", "Other"]
    labels = []
    for i in range(1, 4):
        raw = cfg.get(f"button_{i}_label") or defaults[i - 1]
        labels.append(_s(raw, defaults[i - 1]))
    return labels


def _questions(cfg: dict) -> list[tuple[str, str]]:
    """Return list of (label, placeholder) for up to 3 legacy questions."""
    q = []
    defaults = [
        ("Reason for ticket", "Describe your issue..."),
        ("Additional details", "Any other information..."),
        ("Evidence / links", "Screenshots, links, etc."),
    ]
    for i in range(1, 4):
        label = _s(cfg.get(f"question_{i}_label"), defaults[i - 1][0])
        ph    = _s(cfg.get(f"question_{i}_placeholder"), defaults[i - 1][1])
        q.append((label, ph))
    return q


def _button_questions(cfg: dict, button_index: int) -> list[dict]:
    buttons = _ticket_buttons(cfg)
    if button_index < len(buttons):
        questions = buttons[button_index].get("questions")
        if isinstance(questions, list) and questions:
            clean = []
            for question in questions[:3]:
                if isinstance(question, str):
                    label = _s(question)
                    if label:
                        clean.append({"label": label, "placeholder": "", "required": True})
                    continue
                if not isinstance(question, dict):
                    continue
                label = _s(question.get("label") or question.get("question"))
                if not label:
                    continue
                clean.append({
                    "label": label,
                    "placeholder": _s(question.get("placeholder") or question.get("hint")),
                    "required": bool(question.get("required", True)),
                })
            if clean:
                return clean

    return [
        {"label": label, "placeholder": placeholder, "required": True}
        for label, placeholder in _questions(cfg)
    ]


def _button_emoji(cfg: dict, button_index: int) -> discord.PartialEmoji | str | None:
    buttons = _ticket_buttons(cfg)
    raw = ""
    if button_index < len(buttons):
        raw = _s(buttons[button_index].get("emoji"))
    raw = raw or _s(cfg.get(f"button_{button_index + 1}_emoji")) or _EMOJI_DEFAULTS["ticket"]
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return raw


def _ping_role_ids(cfg: dict) -> list[int]:
    raw = cfg.get("ping_roles") or cfg.get("support_roles") or cfg.get("manager_roles") or []
    if isinstance(raw, (str, int)):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    ids = []
    for role_id in raw:
        parsed = _i(role_id)
        if parsed and parsed not in ids:
            ids.append(parsed)
    return ids


def _code_block(value: str) -> str:
    escaped = str(value or "No answer provided.").replace("```", "'''")
    return f"```\n{escaped}\n```"


# ── CV2 helpers ────────────────────────────────────────────────────────────────

def _cv2_text(content: str) -> discord.ui.TextDisplay:
    for args, kw in (
        ((), {"content": content}),
        ((content,), {}),
        ((), {"text": content}),
    ):
        try:
            return discord.ui.TextDisplay(*args, **kw)
        except TypeError:
            continue
    raise RuntimeError("TextDisplay: no working signature found")


def _cv2_container(*items, accent: int | None = None) -> discord.ui.Container:
    valid = [i for i in items if i is not None]
    colour = discord.Colour(accent) if accent is not None else None
    colour_kwargs = (
        [{"accent_colour": colour}, {"accent_color": colour}, {}]
        if colour is not None else [{}]
    )
    for child_args, child_kw in [(valid, {}), ((), {"children": valid})]:
        for ckw in colour_kwargs:
            try:
                return discord.ui.Container(*child_args, **child_kw, **ckw)
            except TypeError:
                continue
    raise RuntimeError("Container: no working signature found")


def _cv2_section(*lines: str, thumbnail_url: str | None = None):
    text = _cv2_text("\n".join(lines))
    if thumbnail_url:
        thumb = None
        for args, kw in (
            ((thumbnail_url,), {}),
            ((), {"media": thumbnail_url}),
            ((), {"url": thumbnail_url}),
        ):
            try:
                thumb = discord.ui.Thumbnail(*args, **kw)
                break
            except TypeError:
                continue
        if thumb is not None:
            for args, kw in (
                ((text,), {"accessory": thumb}),
                ((), {"components": [text], "accessory": thumb}),
            ):
                try:
                    return discord.ui.Section(*args, **kw)
                except TypeError:
                    continue
    for args, kw in (((text,), {}), ((), {"components": [text]})):
        try:
            return discord.ui.Section(*args, **kw)
        except TypeError:
            continue
    return text


# ── Transcript helpers ─────────────────────────────────────────────────────────

def _extract_component_text(component: dict) -> list:
    results = []
    if component.get("type") == 10:
        text = component.get("content", "").strip()
        if text:
            results.append(text)
    for child in component.get("components", []):
        results.extend(_extract_component_text(child))
    return results


import re as _re

_THINK_RE = _re.compile(r"<think>.*?</think>", _re.DOTALL | _re.IGNORECASE)

def _strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks left by AI models."""
    return _THINK_RE.sub("", text).strip()

def generate_txt_transcript(channel, messages, limit=500):
    lines = [
        f"Transcript - {channel.name}",
        f"Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 60, "",
    ]
    for msg in reversed(messages):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        header = f"[{ts}] {msg.author.display_name}:"
        content = _strip_think(msg.content) if msg.content else ""
        lines.append(f"{header} {content}" if content else header)
        for embed in msg.embeds:
            if embed.title:        lines.append(f"  [Embed Title] {_strip_think(embed.title)}")
            if embed.description:  lines.append(f"  [Embed Desc] {_strip_think(embed.description)}")
            for field in embed.fields:
                lines.append(f"  [Embed Field: {field.name}] {_strip_think(field.value)}")
            if embed.footer and embed.footer.text:
                lines.append(f"  [Embed Footer] {_strip_think(embed.footer.text)}")
        raw = getattr(msg, "_raw_data", None) or getattr(msg, "_data", None)
        raw_comps = raw.get("components", []) if isinstance(raw, dict) else [
            row.to_dict() for row in getattr(msg, "components", []) if hasattr(row, "to_dict")
        ]
        for comp in raw_comps:
            for t in _extract_component_text(comp):
                lines.append(f"  [Container] {_strip_think(t)}")
        for a in msg.attachments:
            lines.append(f"  [Attachment] {a.filename}: {a.url}")
        for s in msg.stickers:
            lines.append(f"  [Sticker] {s.name}")
    return "\n".join(lines)


# ── Data layer ─────────────────────────────────────────────────────────────────

class TicketData:
    def __init__(self, path):
        self.path = path
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump({"blacklist": [], "tickets": {}, "panel_message_ids": {}}, f, indent=4)

    def load(self):
        with open(self.path, "r") as f:
            data = json.load(f)
        data.setdefault("tickets", {})
        data.setdefault("blacklist", [])
        data.setdefault("panel_message_ids", {})
        return data

    def save(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=4)


# ── Close logic ────────────────────────────────────────────────────────────────

async def close_ticket(bot, ticket_data: TicketData, channel: discord.TextChannel, closed_by, reason="Ticket closed"):
    data = ticket_data.load()
    ticket_info = data["tickets"].get(str(channel.id))
    if not ticket_info:
        return

    guild_id = channel.guild.id
    cfg = _tcfg(bot, guild_id)
    limit = _transcript_limit(cfg)
    messages = [msg async for msg in channel.history(limit=limit, oldest_first=False)]
    txt_content = generate_txt_transcript(channel, messages, limit)
    filename = f"transcript-{channel.name}.txt"
    transcript_bytes = txt_content.encode()
    closer_mention = closed_by.mention if closed_by else "the system"

    try:
        user = bot.get_user(ticket_info["user_id"]) or await bot.fetch_user(ticket_info["user_id"])
        if user:
            dm_layout = discord.ui.LayoutView()
            dm_layout.add_item(_cv2_container(
                _cv2_text(
                    "## 🔒 Ticket Closed\n\n"
                    f"Your ticket <#{channel.id}> was closed by {closer_mention}.\n"
                    f"**Reason:** {reason}\n\n"
                    "A transcript of the ticket is attached below."
                ),
                accent=0xED4245,
            ))
            await user.send(view=dm_layout)
            await user.send(file=discord.File(io.BytesIO(transcript_bytes), filename=filename))
    except Exception:
        pass

    log_ch_id = _ticket_log_ch(bot, guild_id)
    if log_ch_id:
        log_ch = bot.get_channel(log_ch_id)
        if log_ch:
            log_layout = discord.ui.LayoutView()
            log_layout.add_item(_cv2_container(
                _cv2_text(
                    "## 🔒 Ticket Closed\n\n"
                    f"**Ticket:** <#{channel.id}>\n"
                    f"**Closed by:** {closer_mention}\n"
                    f"**Reason:** {reason}"
                ),
                accent=0xED4245,
            ))
            try:
                await log_ch.send(view=log_layout)
                await log_ch.send(file=discord.File(io.BytesIO(transcript_bytes), filename=filename))
            except Exception:
                pass

    del data["tickets"][str(channel.id)]
    ticket_data.save(data)
    try:
        await channel.delete(reason=reason)
    except discord.NotFound:
        pass


# ── Dynamic Modal ──────────────────────────────────────────────────────────────

def make_ticket_modal(cfg: dict, button_index: int):
    """Build a TicketCreateModal dynamically with up to 3 configured questions."""
    questions = _button_questions(cfg, button_index)
    buttons = _ticket_buttons(cfg)
    title = (
        _s(buttons[button_index].get("label"), "Create a Ticket")
        if button_index < len(buttons) else
        "Create a Ticket"
    )

    # Discord modals max 5 components; ticket config exposes up to 3 prompts.
    q_count = min(3, max(1, len(questions)))

    inputs = []
    for i in range(q_count):
        question = questions[i]
        label = _s(question.get("label"), f"Question {i + 1}")
        ph = _s(question.get("placeholder"))
        inputs.append(discord.ui.TextInput(
            label=label[:45],
            placeholder=ph[:100] if ph else None,
            style=discord.TextStyle.paragraph,
            required=bool(question.get("required", True)),
            max_length=1000,
        ))

    class _Modal(discord.ui.Modal):
        def __init__(self_m, ticket_data: TicketData):
            super().__init__(title=title[:45])
            self_m.ticket_data = ticket_data
            self_m.btn_index   = button_index
            self_m._cfg        = cfg
            for inp in inputs:
                self_m.add_item(inp)

        async def on_submit(self_m, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            data = self_m.ticket_data.load()
            bot  = interaction.client
            e    = Emojis(bot)

            if interaction.user.id in data["blacklist"]:
                layout = discord.ui.LayoutView()
                layout.add_item(_cv2_container(
                    _cv2_text(f"## {e.fail} Blacklisted\n\nYou are blacklisted from creating tickets."),
                    accent=0xED4245,
                ))
                await interaction.followup.send(view=layout, ephemeral=True)
                return

            for ticket_id, ticket_info in list(data["tickets"].items()):
                if ticket_info["user_id"] == interaction.user.id:
                    ch = bot.get_channel(int(ticket_id))
                    if ch:
                        layout = discord.ui.LayoutView()
                        layout.add_item(_cv2_container(
                            _cv2_text(f"## {e.fail} Ticket Already Exists\n\nYou already have an open ticket: {ch.mention}"),
                            accent=0xED4245,
                        ))
                        await interaction.followup.send(view=layout, ephemeral=True)
                        return
                    del data["tickets"][ticket_id]
                    self_m.ticket_data.save(data)
                    break

            guild      = interaction.guild
            ticket_cfg = _tcfg(bot, guild.id)
            prefix     = _channel_prefix(ticket_cfg)
            cat_name   = _category_name(ticket_cfg)
            category   = discord.utils.get(guild.categories, name=cat_name)
            if not category:
                category = await guild.create_category(cat_name)

            overwrites = {
                guild.default_role:   discord.PermissionOverwrite(read_messages=False),
                interaction.user:     discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me:             discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            ping_roles = []
            for role_id in _ping_role_ids(ticket_cfg):
                role = guild.get_role(role_id)
                if role:
                    ping_roles.append(role)
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            for role in guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            channel_name = f"{prefix}{interaction.user.name}"
            channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

            # Collect answers
            answers = [item.value for item in self_m.children if isinstance(item, discord.ui.TextInput)]
            reason  = answers[0] if answers else "No reason provided"

            data["tickets"][str(channel.id)] = {
                "user_id":      interaction.user.id,
                "channel_name": channel_name,
                "reason":       reason,
                "answers":      answers,
                "button_index": self_m.btn_index,
                "created_at":   datetime.utcnow().isoformat(),
                "auto_close":   None,
            }
            self_m.ticket_data.save(data)

            # Build welcome message with all answers
            welcome_text = _welcome_text(ticket_cfg)
            answer_lines = "\n".join(
                f"**{questions[i].get('label', f'Question {i + 1}')}**\n{_code_block(ans)}"
                for i, ans in enumerate(answers)
            )
            if ping_roles:
                await channel.send(
                    " ".join(role.mention for role in ping_roles),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
                )

            welcome_layout = discord.ui.LayoutView()
            welcome_layout.add_item(_cv2_container(
                _cv2_text(
                    f"## <:ticket:1494057766958927872> Welcome, <@{interaction.user.id}>!\n\n"
                    f"{welcome_text}"
                ),
            ))
            await channel.send(view=welcome_layout, allowed_mentions=discord.AllowedMentions(users=True))

            answers_layout = discord.ui.LayoutView()
            answers_layout.add_item(_cv2_container(
                _cv2_text(
                    "## Ticket Questions\n\n"
                    f"{answer_lines or 'No answers were submitted.'}"
                ),
            ))
            await channel.send(view=answers_layout)

            confirm_layout = discord.ui.LayoutView()
            confirm_layout.add_item(_cv2_container(
                _cv2_text(f"## <:ticket:1494057766958927872> Ticket Created\n\nYour ticket has been created: {channel.mention}"),
                accent=0x28A745,
            ))
            await interaction.followup.send(view=confirm_layout, ephemeral=True)

            try:
                dm_layout = discord.ui.LayoutView()
                dm_layout.add_item(_cv2_container(
                    _cv2_text(
                        "## <:ticket:1494057766958927872> Ticket Opened\n\n"
                        f"Your ticket <#{channel.id}> has been created in **{guild.name}**.\n"
                        f"**Reason:** {reason}"
                    ),
                    accent=0x28A745,
                ))
                await interaction.user.send(view=dm_layout)
            except Exception:
                pass

    return _Modal


# ── Panel View (dynamic buttons) ───────────────────────────────────────────────

def make_panel_view(cfg: dict, ticket_data: TicketData) -> discord.ui.View:
    """Build a panel View with 1–3 buttons from config."""
    btn_count  = _button_count(cfg)
    btn_labels = _button_labels(cfg)
    ModalCls   = [make_ticket_modal(cfg, i) for i in range(btn_count)]

    class _PanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

    for i in range(btn_count):
        label    = btn_labels[i]
        modal_cls = ModalCls[i]
        custom_id = f"ticket:create:{i}"

        async def _callback(interaction: discord.Interaction, *, _i=i, _cls=modal_cls):
            cog: Tickets = interaction.client.cogs.get("Tickets")
            td = cog.ticket_data if cog else ticket_data
            await interaction.response.send_modal(_cls(td))

        btn = discord.ui.Button(
            label=label,
            emoji=_button_emoji(cfg, i),
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id,
            row=0,
        )
        btn.callback = _callback

    # Rebuild the view class cleanly
    class PanelViewFinal(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            for j in range(btn_count):
                _lbl = btn_labels[j]
                _cls = ModalCls[j]
                _cid = f"ticket:create:{j}"

                b = discord.ui.Button(
                    label=_lbl,
                    emoji=_button_emoji(cfg, j),
                    style=discord.ButtonStyle.secondary,
                    custom_id=_cid,
                    row=0,
                )

                async def _cb(interaction: discord.Interaction, *, __cls=_cls):
                    cog: Tickets = interaction.client.cogs.get("Tickets")
                    td = cog.ticket_data if cog else ticket_data
                    await interaction.response.send_modal(__cls(td))

                b.callback = _cb
                self.add_item(b)

    return PanelViewFinal()


# ── Persistent fallback view (always registered) ───────────────────────────────

class TicketPanelView(discord.ui.View):
    """Minimal persistent view that handles any ticket:create:* custom_id."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _open_modal(self, interaction: discord.Interaction, btn_idx: int) -> None:
        cog: Tickets = interaction.client.cogs.get("Tickets")
        if not cog:
            await interaction.response.defer()
            return
        cfg = _tcfg(interaction.client, interaction.guild.id if interaction.guild else None)
        ModalCls = make_ticket_modal(cfg, btn_idx)
        await interaction.response.send_modal(ModalCls(cog.ticket_data))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cid = interaction.data.get("custom_id", "")
        if not cid.startswith("ticket:create"):
            return True
        return True

    @discord.ui.button(label="Ticket 1", style=discord.ButtonStyle.secondary, custom_id="ticket:create:0")
    async def create_ticket_0(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, 0)

    @discord.ui.button(label="Ticket 2", style=discord.ButtonStyle.secondary, custom_id="ticket:create:1")
    async def create_ticket_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, 1)

    @discord.ui.button(label="Ticket 3", style=discord.ButtonStyle.secondary, custom_id="ticket:create:2")
    async def create_ticket_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, 2)


class AutoCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _has_access(self, interaction, ticket_info):
        if interaction.user.guild_permissions.administrator:
            return True
        return ticket_info and ticket_info.get("user_id") == interaction.user.id

    @discord.ui.button(label="Deny Auto Close", style=discord.ButtonStyle.secondary, custom_id="autoclose:deny")
    async def deny_auto_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = Emojis(interaction.client)
        cog: Tickets = interaction.client.cogs.get("Tickets")
        if not cog:
            await interaction.response.defer()
            return
        data = cog.ticket_data.load()
        ticket_info = data["tickets"].get(str(interaction.channel.id))
        if not self._has_access(interaction, ticket_info):
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(
                _cv2_text(f"## {e.fail} Permission Denied\n\nOnly the ticket owner or administrators can deny auto-close."),
                accent=0xED4245,
            ))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if ticket_info:
            ticket_info["auto_close"] = None
            cog.ticket_data.save(data)
        cfg = _tcfg(interaction.client, interaction.guild.id)
        new_name = interaction.channel.name.replace(_autoclose_prefix(cfg), _channel_prefix(cfg))
        try:
            await interaction.channel.edit(name=new_name)
        except Exception:
            pass
        denied_layout = discord.ui.LayoutView()
        denied_layout.add_item(_cv2_container(
            _cv2_text(f"## {e.success} Auto-Close Denied\n\nAuto-close was denied by {interaction.user.mention}. The ticket will remain open."),
            accent=0x28A745,
        ))
        await interaction.response.edit_message(view=denied_layout)

    @discord.ui.button(label="Instant Close", style=discord.ButtonStyle.danger, custom_id="autoclose:instant")
    async def instant_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = Emojis(interaction.client)
        cog: Tickets = interaction.client.cogs.get("Tickets")
        if not cog:
            await interaction.response.defer()
            return
        data = cog.ticket_data.load()
        ticket_info = data["tickets"].get(str(interaction.channel.id))
        if not ticket_info:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text("## Error\n\nThis ticket is not in the database."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if not self._has_access(interaction, ticket_info):
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(
                _cv2_text(f"## {e.fail} Permission Denied\n\nOnly the ticket owner or administrators can close this ticket."),
                accent=0xED4245,
            ))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        await interaction.response.defer()
        await close_ticket(interaction.client, cog.ticket_data, interaction.channel, interaction.user, "Instant close via button")
        try:
            await interaction.followup.send("Ticket closed successfully.", ephemeral=True)
        except Exception:
            pass


# ── Cog ────────────────────────────────────────────────────────────────────────

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.e   = Emojis(bot)
        self.ticket_data = TicketData(TICKET_DATA_PATH)

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(AutoCloseView())
        self.bot.loop.create_task(self._restore_auto_closes())

    async def _restore_auto_closes(self):
        await self.bot.wait_until_ready()
        # Extra small delay so guild channel caches are populated after ready
        await asyncio.sleep(2)
        data = self.ticket_data.load()
        now  = datetime.utcnow()
        for channel_id, ticket_info in list(data.get("tickets", {}).items()):
            ac = ticket_info.get("auto_close")
            if not ac:
                continue
            try:
                scheduled_at = datetime.fromisoformat(ac["scheduled_at"])
            except (KeyError, ValueError):
                continue
            cfg      = _tcfg(self.bot)
            hours    = _autoclose_hours(cfg)
            close_at = scheduled_at + timedelta(hours=hours)
            delay    = (close_at - now).total_seconds()
            channel  = self.bot.get_channel(int(channel_id))
            if channel is None:
                continue
            reason = ac.get("reason", "Auto-close")
            if delay <= 0:
                self.bot.loop.create_task(
                    close_ticket(self.bot, self.ticket_data, channel, None, f"Auto-close (overdue): {reason}")
                )
            else:
                self.bot.loop.create_task(self._scheduled_close(channel, delay, reason))

    async def _scheduled_close(self, channel: discord.TextChannel, delay: float, reason: str):
        """Wait `delay` seconds then close the ticket if auto_close is still set."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            fresh = self.ticket_data.load()
            info  = fresh.get("tickets", {}).get(str(channel.id))
            if info and info.get("auto_close"):
                await close_ticket(self.bot, self.ticket_data, channel, None, f"Auto-close: {reason}")
        except Exception as exc:
            import traceback
            print(f"[Ticket] _scheduled_close error for channel {channel.id}: {exc}")
            traceback.print_exc()

    async def _post_panel(self):
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()

        configs_to_process = []
        if GUILD_CONFIGS_DIR.exists():
            for cfg_file in GUILD_CONFIGS_DIR.glob("*.yaml"):
                try:
                    gid_str = cfg_file.stem
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        gcfg = _yaml.safe_load(f) or {}
                    raw_panel = (gcfg.get("tickets") or {}).get("panel_channel") or 0
                    panel_ch_id = _i(raw_panel)
                    if panel_ch_id:
                        configs_to_process.append((gcfg, panel_ch_id, gid_str))
                except Exception as exc:
                    _log.warning("[Tickets] Failed to read guild config %s: %s", cfg_file, exc)

        # Fallback to global config
        if not configs_to_process:
            global_cfg = getattr(self.bot, "config", {}) or {}
            p_id = _i((global_cfg.get("tickets") or {}).get("panel_channel"))
            if p_id:
                for g in self.bot.guilds:
                    configs_to_process.append((global_cfg, p_id, str(g.id)))
                    break

        for gcfg, panel_ch_id, guild_id_str in configs_to_process:
            guild = self.bot.get_guild(int(guild_id_str))
            if not guild:
                _log.warning("[Tickets] Guild %s not found, skipping.", guild_id_str)
                continue

            panel_ch = guild.get_channel(panel_ch_id)
            if panel_ch is None:
                try:
                    panel_ch = await guild.fetch_channel(panel_ch_id)
                except discord.NotFound:
                    _log.error("[Tickets] Panel channel %s not found in guild %s.", panel_ch_id, guild_id_str)
                    continue
                except discord.Forbidden:
                    _log.error("[Tickets] No permission to access panel channel %s.", panel_ch_id)
                    continue
                except Exception as exc:
                    _log.error("[Tickets] Error fetching panel channel %s: %s", panel_ch_id, exc)
                    continue

            tickets_cfg = gcfg.get("tickets") or {}
            title = _panel_title(tickets_cfg)
            desc  = _panel_desc(tickets_cfg)

            data     = self.ticket_data.load()
            panel_ids = data.setdefault("panel_message_ids", {})
            old_id   = panel_ids.get(str(panel_ch_id))
            if old_id:
                try:
                    old_msg = await panel_ch.fetch_message(int(old_id))
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

            panel_embed = discord.Embed(
                description=f"## <:ticket:1494057766958927872> {title}\n\n{desc}"
            )
            panel_view = make_panel_view(tickets_cfg, self.ticket_data)
            try:
                new_msg = await panel_ch.send(embed=panel_embed, view=panel_view)
            except Exception as exc:
                _log.error("[Tickets] Failed to post panel in channel %s: %s", panel_ch_id, exc)
                continue

            panel_ids[str(panel_ch_id)] = new_msg.id
            data["panel_message_id"] = new_msg.id
            self.ticket_data.save(data)
            _log.info("[Tickets] Panel posted in %s (guild %s).", panel_ch_id, guild_id_str)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        data = self.ticket_data.load()
        for ticket_id, ticket_info in list(data["tickets"].items()):
            if ticket_info["user_id"] == member.id:
                channel = self.bot.get_channel(int(ticket_id))
                if channel:
                    try:
                        layout = discord.ui.LayoutView()
                        layout.add_item(_cv2_container(
                            _cv2_text(f"## Member Left\n\n{member.mention} has left the server. This ticket is now closing."),
                        ))
                        await channel.send(view=layout)
                    except Exception:
                        pass
                    await close_ticket(self.bot, self.ticket_data, channel, None, f"{member} left the server")
                break

    @app_commands.command(name="close", description="Close a ticket immediately")
    async def close(self, interaction: discord.Interaction):
        data = self.ticket_data.load()
        if str(interaction.channel.id) not in data["tickets"]:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Error\n\nThis command can only be used in a ticket channel."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Permission Denied\n\nOnly administrators can close tickets."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        await interaction.response.defer()
        await close_ticket(self.bot, self.ticket_data, interaction.channel, interaction.user, f"Closed by {interaction.user}")
        try:
            await interaction.followup.send("Ticket closed successfully.", ephemeral=True)
        except Exception:
            pass

    @app_commands.command(name="autoclose", description="Schedule a ticket to auto-close")
    @app_commands.describe(reason="The reason for auto-closing the ticket")
    async def autoclose(self, interaction: discord.Interaction, reason: str):
        if not interaction.user.guild_permissions.administrator:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Permission Denied\n\nOnly administrators can schedule auto-close."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        data = self.ticket_data.load()
        ticket_info = data["tickets"].get(str(interaction.channel.id))
        if not ticket_info:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Error\n\nThis command can only be used in a ticket channel."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        cfg = _tcfg(self.bot, interaction.guild.id)
        ac_prefix = _autoclose_prefix(cfg)
        new_name  = interaction.channel.name.replace(_channel_prefix(cfg), ac_prefix)
        try:
            await interaction.channel.edit(name=new_name)
        except Exception:
            pass
        hours = _autoclose_hours(cfg)
        ac_emoji = _autoclose_emoji(cfg)
        scheduled_at    = datetime.utcnow()
        close_timestamp = int((scheduled_at + timedelta(hours=hours)).timestamp())
        ticket_info["auto_close"] = {
            "reason":       reason,
            "scheduled_at": scheduled_at.isoformat(),
            "scheduled_by": interaction.user.id,
        }
        self.ticket_data.save(data)
        autoclose_embed = discord.Embed(
            description=(
                f"## {ac_emoji} Auto-Close Scheduled\n\n"
                f"<@{ticket_info['user_id']}>\n\n"
                f"This ticket will automatically close <t:{close_timestamp}:R>.\n"
                f"**Reason:** {reason}"
            )
        )
        await interaction.channel.send(embed=autoclose_embed, view=AutoCloseView(), allowed_mentions=discord.AllowedMentions(users=True))
        confirm_layout = discord.ui.LayoutView()
        confirm_layout.add_item(_cv2_container(_cv2_text(f"## {ac_emoji} Auto-Close Scheduled\n\nThe ticket will auto-close <t:{close_timestamp}:R>."), accent=0x28A745))
        await interaction.followup.send(view=confirm_layout, ephemeral=True)
        self.bot.loop.create_task(self._scheduled_close(interaction.channel, hours * 3600, reason))

    @app_commands.command(name="ticket-blacklist", description="Manage the ticket blacklist")
    @app_commands.describe(action="Whether to add or remove", user="The user to add or remove")
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove")])
    async def blacklist(self, interaction: discord.Interaction, action: str, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Permission Denied\n\nOnly administrators can manage the blacklist."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        data = self.ticket_data.load()
        if action == "add":
            if user.id in data["blacklist"]:
                layout = discord.ui.LayoutView()
                layout.add_item(_cv2_container(_cv2_text(f"## Already Blacklisted\n\n{user.mention} is already blacklisted."), accent=0xED4245))
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            data["blacklist"].append(user.id)
            self.ticket_data.save(data)
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.success} User Blacklisted\n\n{user.mention} has been blacklisted from creating tickets."), accent=0x28A745))
            await interaction.response.send_message(view=layout)
        else:
            if user.id not in data["blacklist"]:
                layout = discord.ui.LayoutView()
                layout.add_item(_cv2_container(_cv2_text(f"## Not Blacklisted\n\n{user.mention} is not blacklisted."), accent=0xED4245))
                await interaction.response.send_message(view=layout, ephemeral=True)
                return
            data["blacklist"].remove(user.id)
            self.ticket_data.save(data)
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.success} User Unblacklisted\n\n{user.mention} has been removed from the ticket blacklist."), accent=0x28A745))
            await interaction.response.send_message(view=layout)

    @app_commands.command(name="add", description="Add a user to the current ticket")
    @app_commands.describe(user="The user to add to this ticket")
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        data = self.ticket_data.load()
        if str(interaction.channel.id) not in data["tickets"]:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Error\n\nThis command can only be used in a ticket channel."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Permission Denied\n\nOnly administrators can add users to tickets."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        overwrite = interaction.channel.overwrites_for(user)
        if overwrite.read_messages:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.add} Already Added\n\n{user.mention} already has access to this ticket."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
        except discord.Forbidden:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Missing Permissions\n\nBot is missing permissions to edit this channel."), accent=0xED4245))
            await interaction.followup.send(view=layout, ephemeral=True)
            return
        notice = discord.ui.LayoutView()
        notice.add_item(_cv2_container(_cv2_text(f"## {self.e.add} User Added\n\n{user.mention} has been added to this ticket by {interaction.user.mention}."), accent=0x28A745))
        await interaction.channel.send(view=notice, allowed_mentions=discord.AllowedMentions(users=True))
        confirm = discord.ui.LayoutView()
        confirm.add_item(_cv2_container(_cv2_text(f"## {self.e.add} Done\n\n{user.mention} has been added to this ticket."), accent=0x28A745))
        await interaction.followup.send(view=confirm, ephemeral=True)

    @app_commands.command(name="remove", description="Remove a user from the current ticket")
    @app_commands.describe(user="The user to remove from this ticket")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        data = self.ticket_data.load()
        ticket_info = data["tickets"].get(str(interaction.channel.id))
        if not ticket_info:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Error\n\nThis command can only be used in a ticket channel."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Permission Denied\n\nOnly administrators can remove users from tickets."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        if user.id == ticket_info.get("user_id"):
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.remove} Cannot Remove Owner\n\nThe ticket owner cannot be removed from their own ticket."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        overwrite = interaction.channel.overwrites_for(user)
        if not overwrite.read_messages:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.remove} Not in Ticket\n\n{user.mention} does not have explicit access to this ticket."), accent=0xED4245))
            await interaction.response.send_message(view=layout, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.set_permissions(user, overwrite=None)
        except discord.Forbidden:
            layout = discord.ui.LayoutView()
            layout.add_item(_cv2_container(_cv2_text(f"## {self.e.fail} Missing Permissions\n\nBot is missing permissions to edit this channel."), accent=0xED4245))
            await interaction.followup.send(view=layout, ephemeral=True)
            return
        notice = discord.ui.LayoutView()
        notice.add_item(_cv2_container(_cv2_text(f"## {self.e.remove} User Removed\n\n{user.mention} has been removed from this ticket by {interaction.user.mention}."), accent=0xED4245))
        await interaction.channel.send(view=notice, allowed_mentions=discord.AllowedMentions(users=True))
        confirm = discord.ui.LayoutView()
        confirm.add_item(_cv2_container(_cv2_text(f"## {self.e.remove} Done\n\n{user.mention} has been removed from this ticket."), accent=0x28A745))
        await interaction.followup.send(view=confirm, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
