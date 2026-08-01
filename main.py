import os
import sys
import asyncio
import yaml
import datetime
from pathlib import Path
from dotenv import load_dotenv

import discord
from discord.ext import commands

from utils.console_ui import (
    RICH_AVAILABLE,
    console,
    Panel,
    Table,
    Text,
    Rule,
    Padding,
    Align,
    box,
    safe_print,
    log,
    log_rule,
    log_kv,
    print_banner,
    print_exception_block,
)

# ── Custom imports ─────────────────────────────────────────────────────────────
try:
    from utils.logger import BotLogger
    from utils.embeds import EmbedColor
except ImportError as e:
    if RICH_AVAILABLE:
        console.print(f"[error]✗ Import Error:[/error] {e}\n[muted]Ensure your directory structure is correct.[/muted]")
    else:
        print(f"Import Error: {e}. Ensure your directory structure is correct.")
    sys.exit(1)

_PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
load_dotenv()

# Use Discord's blurple for embeds that do not explicitly choose a semantic
# success, warning, or error colour. This keeps every cog visually consistent
# without requiring each one to repeat ``color=discord.Color.blurple()``.
_embed_init = discord.Embed.__init__
_embed_default_color = discord.Color.blurple()


def _blurple_embed_init(self, *args, **kwargs):
    if kwargs.get("color") is None and kwargs.get("colour") is None:
        kwargs["color"] = _embed_default_color
    _embed_init(self, *args, **kwargs)


discord.Embed.__init__ = _blurple_embed_init


def configure_embed_default(config: dict) -> None:
    """Set the global embed default from ``appearance.embed_color``."""
    global _embed_default_color
    value = str((config.get("appearance") or {}).get("embed_color", "blurple")).strip().lower()
    if value == "blurple":
        _embed_default_color = discord.Color.blurple()
        return
    try:
        _embed_default_color = discord.Color.from_str(value)
    except ValueError:
        log("warning", f"Invalid appearance.embed_color {value!r}; using blurple.")
        _embed_default_color = discord.Color.blurple()

# (logging / console UI lives in utils/console_ui.py)


# ═══════════════════════════════════════════════════════════════════════════════
#  Bot class
# ═══════════════════════════════════════════════════════════════════════════════

class Bot(commands.Bot):
    """Custom Discord bot with rich terminal logging."""

    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True

        super().__init__(
            command_prefix=config['bot'].get('prefix', '!'),
            intents=intents,
            help_command=None,
        )

        self.config = config
        self.start_time = discord.utils.utcnow()
        self.logger = BotLogger(config.get('logging', {}))

    # ── Startup ────────────────────────────────────────────────────────────────

    async def setup_hook(self):
        print_banner()
        log_rule("STARTUP SEQUENCE", style="bright_cyan")
        log("info", "Initialising Bot")
        await self.load_cogs()

    # ── Cog loader ─────────────────────────────────────────────────────────────

    async def load_cogs(self):
        cogs_dir = Path(__file__).parent / 'cogs'

        if not cogs_dir.exists():
            log("warning", "Cogs Directory not found, skipping.")
            return

        cog_files = [f.stem for f in cogs_dir.glob('*.py') if f.stem != '__init__']

        log_rule("COG REGISTRY", style="blue")

        ok = fail = 0

        for cog in cog_files:
            try:
                await self.load_extension(f'cogs.{cog}')
                log("success", f"Cog Loaded: [ [bold cyan]{cog}[/bold cyan] ]")
                ok += 1
            except Exception as e:
                log("error", f"Cog Failed:  [ [bold]{cog}[/bold] ]  [dim]{type(e).__name__}: {e}[/dim]")
                fail += 1
                self.logger.error(f"Cog Load Failed [{cog}]: {e}", exc_info=True)

        if RICH_AVAILABLE:
            console.print()
        summary_style = "success" if fail == 0 else ("warning" if ok > 0 else "error")
        log(summary_style, f"[bold]{ok}/{len(cog_files)}[/bold] Cogs Loaded" + (f"  [dim]([bold red]{fail}[/bold red] Failed)[/dim]" if fail else "  [dim]— All Clear[/dim]"))

    # ── Ready ──────────────────────────────────────────────────────────────────

    async def on_ready(self):
        log_rule("BOT ONLINE", style="bold bright_cyan")

        if RICH_AVAILABLE:
            info_table = Table(
                show_header=False,
                border_style="dim blue",
                box=box.SIMPLE,
                padding=(0, 2),
            )
            info_table.add_column("Key",   style="label",  justify="right")
            info_table.add_column("Value", style="accent",  justify="left")

            info_table.add_row("Identity",  f"{self.user}  (ID: {self.user.id})")
            info_table.add_row("Guilds",    str(len(self.guilds)))
            info_table.add_row("Users",     str(sum(g.member_count for g in self.guilds if g.member_count)))
            info_table.add_row("Prefix",    self.config['bot'].get('prefix', '!'))
            info_table.add_row("Uptime",    self.start_time.strftime("%Y-%m-%d %H:%M UTC"))

            console.print(Padding(info_table, (0, 2)))
        else:
            log("info", f"Identity: {self.user} (ID: {self.user.id})")
            log("info", f"Guilds: {len(self.guilds)}")

        # Set presence
        activity_type_str = self.config['bot'].get('activity_type', 'watching').lower()
        activity_text     = self.config['bot'].get('activity', 'your community')

        activity_types = {
            'playing':   discord.ActivityType.playing,
            'watching':  discord.ActivityType.watching,
            'listening': discord.ActivityType.listening,
            'streaming': discord.ActivityType.streaming,
            'custom':    getattr(discord.ActivityType, 'custom', discord.ActivityType.playing),
        }

        if activity_type_str == 'custom' and hasattr(discord, 'CustomActivity'):
            activity = discord.CustomActivity(name=activity_text)
        else:
            activity = discord.Activity(
                type=activity_types.get(activity_type_str, discord.ActivityType.watching),
                name=activity_text,
            )

        await self.change_presence(
            activity=activity,
            status=discord.Status.online,
        )
        log("info", f"Presence set → [{activity_type_str}] {activity_text}")

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            log("success", f"Commands Synced — {len(synced)} command(s) registered")
        except Exception as e:
            log("error", f"Failed to Sync Commands: {e}")

        log_rule(style="bright_cyan")
        log("success", "Bot is online. Listening for events…")
        console.print() if RICH_AVAILABLE else None

    # ── Error formatting ───────────────────────────────────────────────────────

    def _build_error_panel(self, error: Exception, context: str) -> None:
        """Print a beautiful error panel to the terminal."""
        if not RICH_AVAILABLE:
            safe_print(f"\n[ERROR] {context}\n{traceback.format_exc()}\n")
            return

        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text  = "".join(tb_lines).strip()

        header = Table.grid(padding=(0, 1))
        header.add_column(style="bold red")
        header.add_column(style="white")
        header.add_row("Error Type:",    type(error).__name__)
        header.add_row("Message:",       str(error))
        header.add_row("Context:",       context)
        header.add_row("Timestamp:",     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        tb_renderable = Text(tb_text, style="dim white")

        full = Table.grid()
        full.add_column()
        full.add_row(header)
        full.add_row(Rule(style="dim red"))
        full.add_row(tb_renderable)

        console.print(
            Panel(
                full,
                title=f"[bold red]⚠  EXCEPTION CAUGHT[/bold red]",
                border_style="red",
                padding=(1, 2),
                box=box.HEAVY,
            )
        )

    def format_error_details(self, error: Exception, context: str = "Unknown") -> str:
        """Return plain-text error string for BotLogger file output."""
        tb_str = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        return (
            f"\n{'='*80}\n"
            f"ERROR  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'='*80}\n"
            f"Context:       {context}\n"
            f"Error Type:    {type(error).__name__}\n"
            f"Error Message: {error}\n"
            f"{'─'*80}\n"
            f"{tb_str}"
            f"{'='*80}\n"
        )

    # ── Error handlers ─────────────────────────────────────────────────────────

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return

        context_str = (
            f"Prefix Command  /{ctx.command}  "
            f"| {ctx.author} in {ctx.guild.name if ctx.guild else 'DM'}"
        )
        self._build_error_panel(error, context_str)
        self.logger.error(self.format_error_details(error, context_str))

        try:
            await ctx.send(f"❌ `{type(error).__name__}` — check logs for details.")
        except Exception:
            pass

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        command_name = interaction.command.name if interaction.command else "unknown"
        context_str = (
            f"Slash Command  /{command_name}  "
            f"| {interaction.user} in {interaction.guild.name if interaction.guild else 'DM'}"
        )
        self._build_error_panel(error, context_str)
        self.logger.error(self.format_error_details(error, context_str))

        try:
            msg = f"❌ `{type(error).__name__}` — check logs for details."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def on_error(self, event_method, *args, **kwargs):
        exc_type, exc_value, _ = sys.exc_info()
        context_str = f"Event: {event_method}"

        if args:
            obj = args[0]
            if isinstance(obj, discord.Message):
                context_str += f" | msg from {obj.author} in {obj.guild}"
            elif isinstance(obj, discord.Member):
                context_str += f" | member {obj} in {obj.guild}"
            elif isinstance(obj, discord.Guild):
                context_str += f" | guild {obj}"

        self._build_error_panel(exc_value, context_str)
        self.logger.error(self.format_error_details(exc_value, context_str))

    # ── Shutdown ───────────────────────────────────────────────────────────────

    async def close(self):
        log_rule("SHUTDOWN", style="yellow")
        log("warning", "Shutdown signal received — cleaning up…")
        await super().close()
        log("success", "Bot stopped cleanly. Goodbye.")
        console.print() if RICH_AVAILABLE else None


# ═══════════════════════════════════════════════════════════════════════════════
#  Config loader
# ═══════════════════════════════════════════════════════════════════════════════

def load_config(config_path: str = 'config.yaml') -> dict:
    """Load YAML config and resolve ${ENV_VAR} placeholders."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        def replace_env_vars(obj):
            if isinstance(obj, dict):
                return {k: replace_env_vars(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_env_vars(i) for i in obj]
            elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
                return os.getenv(obj[2:-1], obj)
            return obj

        return replace_env_vars(config)

    except FileNotFoundError:
        if RICH_AVAILABLE:
            console.print(f"[error]✘ Config not found:[/error] {config_path}")
        else:
            safe_print(f"Error: {config_path} not found.")
        sys.exit(1)
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[error]✘ Config load error:[/error] {e}")
        else:
            safe_print(f"Error loading config: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  Entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    # Clear the console
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

    config = load_config()
    configure_embed_default(config)

    token = os.getenv('DISCORD_BOT_TOKEN') or config['bot'].get('token')
    if not token or token.startswith('${'):
        if RICH_AVAILABLE:
            console.print(
                Panel(
                    "[bold red]DISCORD_BOT_TOKEN not found.[/bold red]\n"
                    "[muted]Set it in your [white].env[/white] file or [white]config.yaml[/white].[/muted]",
                    title="[bold red]⚠  Fatal Error[/bold red]",
                    border_style="red",
                    box=box.HEAVY,
                )
            )
        else:
            safe_print("Fatal Error: DISCORD_BOT_TOKEN not found.")
        sys.exit(1)

    bot = Bot(config)

    async with bot:
        await bot.start(token)


if __name__ == '__main__':
    import signal as _signal

    def _sigterm_handler(*_):
        import io
        sys.stderr = io.StringIO()
        sys.stdout = io.StringIO()
        os._exit(1)

    try:
        _signal.signal(_signal.SIGTERM, _sigterm_handler)
    except (OSError, ValueError):
        pass

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[critical] FATAL STARTUP ERROR [/critical] {e}")
        else:
            safe_print(f"Fatal Startup Error: {e}")
        sys.exit(1)
    finally:
        import io
        sys.stderr = io.StringIO()
        sys.stdout = io.StringIO()
