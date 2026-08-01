"""
utils/emojis.py
─────────────────────────────────────────────────────────────────
Central emoji registry.  All cogs import from here instead of
hard-coding emoji strings.  Values come from config.yaml under the
`emojis:` block; the defaults below are the fallback values so the
bot still works if the key is missing from config.
"""
from __future__ import annotations
from typing import Any

# ── Default emoji strings (fallback if not in config) ────────────────────────
_DEFAULTS: dict[str, str] = {
    "success":  "<:success:1493767597605519380>",
    "fail":     "<:fail:1493767597030772916>",
    "error":    "<:error:1493771193134616586>",
    "info":     "<:info:1494058285890801786>",
    "ticket":   "<:ticket:1494057766958927872>",
    "lock":     "<:lock:1494057987503952024>",
    "unlock":   "<:unlock:1494057986040266813>",
    "ban":      "<:ban:1495227479592271922>",
    "kick":     "<:kick:1495554172911620247>",
    "timeout":  "<:timeout:1495227742915137618>",
    "trash":    "<:trash:1494796123003424879>",
    "report":   "<:report:1495228065549254826>",
    "slowmode": "<:slowmode:1495227875589361807>",
    "trophy":   "<:trophy:1494060175848374313>",
    "afk":      "<:afk:1493772448082952254>",
    "online":   "<:online:1493772831446536353>",
    "down":     "<:down:1493775399501566077>",
    "uptime":   "<:uptime:1493770600366215218>",
    "logs":     "<:logs:1494102361029869608>",
    "star":     "<:star:1494798374283776090>",
    "sticky":   "<:sticky:1495555622286917702>",
    "language": "<:language:1493777595802718258>",
    "link":     "<:link:1495084949496139867>",
    "shield":   "<:shield:1495228701078720603>",
    "ping":     "<:ping:1495229918173466864>",
    "announce": "<:announce:1495077753781878784>",
    "booster":  "<:booster:1493764643879911615>",
    "left":     "<:left:1494484350861971548>",
    "right":    "<:right:1494484544693469235>",
    "download": "<:download:1494795438467973310>",
    "add":      "<:add:1496975643051688017>",
    "remove":   "<:remove:1496975641348931776>",
}


class Emojis:
    """
    Lightweight emoji accessor.  Call ``Emojis(bot)`` to get an instance
    backed by the bot's live config, or ``Emojis()`` for pure defaults.

    Usage::

        from utils.emojis import Emojis
        e = Emojis(bot)
        title = f"{e.success} Operation complete"
    """

    __slots__ = ("_data",)

    def __init__(self, bot: Any = None) -> None:
        cfg: dict = {}
        if bot is not None:
            cfg = ((getattr(bot, "config", None) or {}).get("emojis") or {})
        self._data: dict[str, str] = {**_DEFAULTS, **{k: str(v) for k, v in cfg.items() if v}}

    def get(self, name: str) -> str:
        return self._data.get(name, _DEFAULTS.get(name, ""))

    # ── convenience properties ────────────────────────────────────────────
    @property
    def success(self)  -> str: return self.get("success")
    @property
    def fail(self)     -> str: return self.get("fail")
    @property
    def error(self)    -> str: return self.get("error")
    @property
    def info(self)     -> str: return self.get("info")
    @property
    def ticket(self)   -> str: return self.get("ticket")
    @property
    def lock(self)     -> str: return self.get("lock")
    @property
    def unlock(self)   -> str: return self.get("unlock")
    @property
    def ban(self)      -> str: return self.get("ban")
    @property
    def kick(self)     -> str: return self.get("kick")
    @property
    def timeout(self)  -> str: return self.get("timeout")
    @property
    def trash(self)    -> str: return self.get("trash")
    @property
    def report(self)   -> str: return self.get("report")
    @property
    def slowmode(self) -> str: return self.get("slowmode")
    @property
    def trophy(self)   -> str: return self.get("trophy")
    @property
    def afk(self)      -> str: return self.get("afk")
    @property
    def online(self)   -> str: return self.get("online")
    @property
    def down(self)     -> str: return self.get("down")
    @property
    def uptime(self)   -> str: return self.get("uptime")
    @property
    def logs(self)     -> str: return self.get("logs")
    @property
    def star(self)     -> str: return self.get("star")
    @property
    def sticky(self)   -> str: return self.get("sticky")
    @property
    def language(self) -> str: return self.get("language")
    @property
    def link(self)     -> str: return self.get("link")
    @property
    def shield(self)   -> str: return self.get("shield")
    @property
    def ping(self)     -> str: return self.get("ping")
    @property
    def announce(self) -> str: return self.get("announce")
    @property
    def booster(self)  -> str: return self.get("booster")
    @property
    def left(self)     -> str: return self.get("left")
    @property
    def right(self)    -> str: return self.get("right")
    @property
    def download(self) -> str: return self.get("download")
    @property
    def add(self)      -> str: return self.get("add")
    @property
    def remove(self)   -> str: return self.get("remove")
