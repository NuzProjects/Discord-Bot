import os
import sys
import re
import traceback
import datetime

# ── Rich logging setup ────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.rule import Rule
    from rich import box
    from rich.theme import Theme
    from rich.traceback import install as install_rich_traceback
    from rich.padding import Padding
    from rich.align import Align

    RICH_AVAILABLE = True
    install_rich_traceback(show_locals=False, width=120)

    bot_theme = Theme(
        {
            "info": "bold cyan",
            "success": "bold green",
            "warning": "bold yellow",
            "error": "bold red",
            "critical": "bold white on red",
            "muted": "dim white",
            "highlight": "bold magenta",
            "accent": "bold bright_cyan",
            "label": "bold white",
            "value": "bright_white",
            "cog.ok": "bold green",
            "cog.fail": "bold red",
            "separator": "dim blue",
        }
    )
    console = Console(theme=bot_theme, highlight=False)

    # Some Windows consoles use cp1252 and fail on Unicode rendering.
    encoding = (sys.stdout.encoding or "").lower()
    if "utf" not in encoding:
        RICH_AVAILABLE = False
        console = None

except ImportError:
    RICH_AVAILABLE = False
    console = None

# Export Rich symbols for main.py (or set to None).
if not RICH_AVAILABLE:
    Panel = None  # type: ignore
    Table = None  # type: ignore
    Text = None  # type: ignore
    Rule = None  # type: ignore
    Padding = None  # type: ignore
    Align = None  # type: ignore
    box = None  # type: ignore


ICONS = {
    "info": "[I]",
    "success": "[+]",
    "warning": "[!]",
    "error": "[x]",
    "critical": "[!!]",
    "wait": "[.]",
    "event": "[*]",
    "net": "[N]",
    "cog": "[C]",
    "sync": "[S]",
    "shutdown": "[Q]",
}


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def safe_print(text: str):
    """Print text safely on Windows consoles with limited encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        cleaned = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(cleaned)


def log(level: str, message: str):
    """Unified pretty logger. Falls back to plain print when rich is unavailable."""
    if not RICH_AVAILABLE:
        plain = re.sub(r"\[/?[^\]]+\]", "", message)
        safe_print(f"[{_ts()}] [{level.upper()}] {plain}")
        return

    icon = ICONS.get(level, "[?]")
    style = level if level in ("info", "success", "warning", "error", "critical") else "info"

    prefix = Text()
    prefix.append(f" {_ts()} ", style="muted")
    prefix.append(f" {icon} {level.upper()} ", style=style)
    prefix.append(" ")
    console.print(prefix, end="")
    console.print(message, style="value", markup=True, highlight=False)


def log_rule(title: str = "", style: str = "separator"):
    if RICH_AVAILABLE:
        console.print(Rule(title, style=style))


def log_kv(label: str, value: str, *, icon: str = "[I]", label_style="label", value_style="accent"):
    if RICH_AVAILABLE:
        ts = Text(f" {_ts()} ", style="muted")
        prefix = Text(f" {icon}  ", style="muted")
        lbl = Text(f"{label}: ", style=label_style)
        val = Text(str(value), style=value_style)
        console.print(ts + prefix + lbl + val)
    else:
        safe_print(f"  {label}: {value}")


def print_banner():
    if not RICH_AVAILABLE:
        safe_print("=== Discord Bot Starting ===")
        return

    art_lines = [
        "██████╗ ██╗███████╗ ██████╗ ██████╗ ██████╗ ██████╗ ",
        "██╔══██╗██║██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔══██╗",
        "██║  ██║██║███████╗██║     ██║   ██║██████╔╝██║  ██║",
        "██║  ██║██║╚════██║██║     ██║   ██║██╔══██╗██║  ██║",
        "██████╔╝██║███████║╚██████╗╚██████╔╝██║  ██║██████╔╝",
        "╚═════╝ ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝",
    ]

    art = Text(justify="center")
    for line in art_lines:
        art.append(line + "\n", style="bold bright_cyan")
    art.append("\n")
    art.append("  Python 3.12    discord.py     ɴᴜᴢꜰʟᴀᴍᴇᴠ₂ ", style="bold white")

    panel = Panel(
        Align(art, align="center"),
        border_style="bright_cyan",
        padding=(1, 4),
        box=box.DOUBLE_EDGE,
    )
    console.print(panel)
    console.print()


def print_exception_block(title: str, exc: BaseException):
    safe_print("")
    safe_print(f"========== {title} ==========")
    traceback.print_exception(type(exc), exc, exc.__traceback__)
    safe_print("=" * (22 + len(title)))
    safe_print("")

