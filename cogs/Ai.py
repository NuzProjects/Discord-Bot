import discord
from utils.emojis import Emojis
from discord.ext import commands
from discord import app_commands
from groq import AsyncGroq
from collections import deque
import json
import time
import asyncio
from pathlib import Path

COLOR_ERROR = discord.Color.red()
EMBED_COLOR = discord.Color.from_rgb(0, 0, 0)
AI_DATA_FILE = Path("data/ai.json")
BLACKLIST_FILE = Path("data/blacklist.json")

STREAM_INTERVAL = 0.8

class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.e = Emojis(bot)
        ai_cfg = (getattr(bot, "config", {}) or {}).get("ai") or {}
        self.api_key = str(ai_cfg.get("api_key") or "").strip()
        self.target_channel_id = int(ai_cfg.get("channel_id") or 0)
        self.cooldown_seconds = max(0, int(ai_cfg.get("cooldown_seconds") or 20))
        raw_models = ai_cfg.get("models") or []
        # Support string (newline-separated) or list; also handle list entries
        # that are comma-separated (e.g. saved incorrectly as one string)
        if isinstance(raw_models, str):
            raw_models = [m.strip() for m in raw_models.splitlines() if m.strip()]
        # Flatten: split any list entry that contains commas into individual models
        expanded = []
        for entry in raw_models:
            if isinstance(entry, str) and "," in entry:
                expanded.extend(m.strip() for m in entry.split(",") if m.strip())
            elif isinstance(entry, str) and entry.strip():
                expanded.append(entry.strip())
        self.models = expanded if expanded else [
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-120b",
            "llama-3.3-70b-versatile",
            "qwen/qwen3-32b",
        ]
        self.current_model_index = 0
        self.model_failures: dict[int, int] = {}   # index -> failure count
        self.smart_rotate = True  # rotate models intelligently
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None
        self.system_prompt = str(ai_cfg.get("system_prompt") or "").strip()
        self.memory = {}
        self.knowledge_base = []
        self.blacklist = []
        self.cooldowns = {}
        self._load_data()

    def _load_data(self):
        AI_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        if AI_DATA_FILE.exists():
            try:
                with open(AI_DATA_FILE, "r", encoding="utf-8") as f:
                    self.knowledge_base = json.load(f)
            except:
                self.knowledge_base = []
        if BLACKLIST_FILE.exists():
            try:
                with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                    self.blacklist = json.load(f)
            except:
                self.blacklist = []

    def _save_knowledge(self):
        with open(AI_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.knowledge_base, f, indent=4)

    def _save_blacklist(self):
        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(self.blacklist, f, indent=4)

    def get_system_prompt(self, user_name: str):
        base = (
            "You are a concise Discord assistant. "
            f"The user you are currently speaking to is named {user_name}. Use their name occasionally. "
            "You can use Markdown and send images or videos. Keep everything SFW. "
            "You can see and analyze images if the user provides them. "
            "CRITICAL: Do NOT type @everyone or @here NO MATTER what anyone asks you to do."
        )
        parts = [base]
        if self.system_prompt:
            parts.append(self.system_prompt)
        if self.knowledge_base:
            parts.append("Additional Context: " + " | ".join(self.knowledge_base))
        return "\n".join(parts)

    async def admin_guard(self, interaction: discord.Interaction):
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

    def check_cooldown(self, user_id):
        current_time = time.time()
        last_use = self.cooldowns.get(user_id, 0)
        if current_time - last_use < self.cooldown_seconds:
            return self.cooldown_seconds - (current_time - last_use)
        return 0

    def _build_messages(self, user_name: str, user_id: int, content: str, image_url: str = None):
        if user_id not in self.memory:
            self.memory[user_id] = deque(maxlen=5)
        if image_url:
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": content if content else "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        else:
            user_msg = {"role": "user", "content": content}
        messages = [{"role": "system", "content": self.get_system_prompt(user_name)}]
        for past_msg in self.memory[user_id]:
            messages.append(past_msg)
        messages.append(user_msg)
        return messages

    def _save_to_memory(self, user_id: int, user_content: str, assistant_response: str):
        if user_id not in self.memory:
            self.memory[user_id] = deque(maxlen=5)
        self.memory[user_id].append({"role": "user", "content": user_content})
        self.memory[user_id].append({"role": "assistant", "content": assistant_response})

    def _next_model(self, failed_index: int | None = None):
        """Smart model rotation: track failures, skip broken models."""
        if failed_index is not None:
            self.model_failures[failed_index] = self.model_failures.get(failed_index, 0) + 1
        # Try to find the next model with fewer than 3 consecutive failures
        for _ in range(len(self.models)):
            self.current_model_index = (self.current_model_index + 1) % len(self.models)
            if self.model_failures.get(self.current_model_index, 0) < 3:
                return self.models[self.current_model_index]
        # All models seem down — reset failure counts and try again
        self.model_failures = {}
        self.current_model_index = 0
        return self.models[0]

    async def stream_ai_response(self, user, content: str, discord_message, image_url: str = None):
        user_id = user.id
        user_name = user.display_name
        CURSOR = " ▌"

        model_to_use = (
            "meta-llama/llama-4-scout-17b-16e-instruct"
            if image_url
            else self.models[self.current_model_index]
        )

        messages = self._build_messages(user_name, user_id, content, image_url)

        full_response = ""
        last_edit_content = ""
        last_edit_time = asyncio.get_event_loop().time()

        try:
            stream = await self.client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=0.7,
                max_tokens=800,
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if not delta:
                    continue

                full_response += delta
                now = asyncio.get_event_loop().time()

                if (now - last_edit_time) >= STREAM_INTERVAL and full_response != last_edit_content:
                    display = full_response if len(full_response) <= 1900 else full_response[:1900]
                    try:
                        await discord_message.edit(content=display + CURSOR)
                        last_edit_content = full_response
                        last_edit_time = now
                    except discord.HTTPException:
                        pass

        except Exception as e:
            print(f"DEBUG STREAM ERROR [{model_to_use}]: {e}")
            if not image_url:
                self._next_model(failed_index=self.current_model_index)
                print(f"[AI] Rotated to model: {self.models[self.current_model_index]}")
            error_msg = f"{self.e.error} Error: I encountered an issue. Please try again later."
            try:
                await discord_message.edit(content=error_msg)
            except discord.HTTPException:
                pass
            return error_msg
        import re
        full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()
        if not full_response:
            full_response = f"{self.e.error} Error: Empty response from AI."
        elif len(full_response) > 2000:
            full_response = full_response[:1997] + "..."

        try:
            await discord_message.edit(content=full_response)
        except discord.HTTPException:
            pass

        self._save_to_memory(user_id, content if content else "[Sent an image]", full_response)
        # Successful — clear failure count for this model; soft rotate to spread load
        if not image_url:
            self.model_failures[self.current_model_index] = 0
            if self.smart_rotate:
                self.current_model_index = (self.current_model_index + 1) % len(self.models)
        return full_response

    async def send_error_embed(self, destination, title, description):
        embed = discord.Embed(title=title, description=description, color=COLOR_ERROR)
        if isinstance(destination, discord.Interaction):
            if destination.response.is_done():
                await destination.followup.send(embed=embed, ephemeral=True)
            else:
                await destination.response.send_message(embed=embed, ephemeral=True)
        else:
            await destination.reply(embed=embed, delete_after=10)

    @app_commands.command(name="feed", description="Add information to the AI system prompt for this server")
    @app_commands.describe(message="The information to add to the AI system prompt")
    async def feed(self, interaction: discord.Interaction, message: str):
        if not await self.admin_guard(interaction): return
        await interaction.response.defer(ephemeral=True)
        # Load guild config, append to system_prompt, and save
        try:
            import yaml
            from pathlib import Path
            guild_id = str(interaction.guild.id)
            cfg_path = Path(f"data/guild_configs/{guild_id}.yaml")
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            ai_sec = existing.setdefault("ai", {})
            current_prompt = str(ai_sec.get("system_prompt") or "").strip()
            separator = "\n" if current_prompt else ""
            ai_sec["system_prompt"] = current_prompt + separator + message
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            # Update live cog state
            self.system_prompt = ai_sec["system_prompt"]
        except Exception as e:
            return await interaction.followup.send(
                embed=discord.Embed(title=f"{self.e.error} Error", description=f"Failed to save: {e}", color=COLOR_ERROR),
                ephemeral=True
            )
        embed = discord.Embed(
            title="System Prompt Updated",
            description="The AI system prompt for this server has been updated.",
            color=EMBED_COLOR,
            timestamp=interaction.created_at
        )
        embed.add_field(name="Added Content", value=f"```\n{message}\n```", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="blacklist", description="Add or remove a user from the AI blacklist")
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove")
    ])
    @app_commands.describe(action="Whether to add or remove the user from the blacklist", user="The user to add or remove from the blacklist")
    async def blacklist_user(self, interaction: discord.Interaction, action: app_commands.Choice[str], user: discord.User):
        if not await self.admin_guard(interaction): return
        if action.value == "add":
            if user.id in self.blacklist:
                return await self.send_error_embed(interaction, f"{self.e.error} Error", f"{user.mention} is already blacklisted.")
            self.blacklist.append(user.id)
            title, desc = "User Blacklisted", f"{user.mention} has been added to the AI blacklist."
        else:
            if user.id not in self.blacklist:
                return await self.send_error_embed(interaction, f"{self.e.error} Error", f"{user.mention} is not blacklisted.")
            self.blacklist.remove(user.id)
            title, desc = "User Unblacklisted", f"{user.mention} has been removed from the AI blacklist."
        self._save_blacklist()
        embed = discord.Embed(title=title, description=desc, color=EMBED_COLOR, timestamp=interaction.created_at)
        embed.add_field(name="User ID", value=str(user.id), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ask", description="Ask the AI anything (Images supported)")
    @app_commands.describe(content="The question or message to send to the AI", image="An optional image to include with your question")
    async def slash_ask(self, interaction: discord.Interaction, content: str, image: discord.Attachment = None):
        if not self.api_key or not self.client:
            return await self.send_error_embed(interaction, f"{self.e.error} Configuration Error", "AI API key not configured. Please set the API key in ai.py")
        if self.target_channel_id == 0:
            return await self.send_error_embed(interaction, f"{self.e.error} Configuration Error", "AI channel ID not configured. Please set the target channel ID in ai.py")
        if interaction.user.id in self.blacklist:
            return await self.send_error_embed(interaction, f"{self.e.error} Access Denied", "You are blacklisted from using this AI.")
        cd = self.check_cooldown(interaction.user.id)
        if cd > 0:
            return await self.send_error_embed(interaction, f"{self.e.error} Cooldown", f"Please wait {int(cd)} seconds.")
        await interaction.response.defer()
        self.cooldowns[interaction.user.id] = time.time()
        image_url = (
            image.url
            if image and any(image.filename.lower().endswith(e) for e in ['png', 'jpg', 'jpeg', 'webp'])
            else None
        )
        try:
            placeholder = await interaction.followup.send("_ _")
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=discord.Embed(title=f"{self.e.error} Error", description="Failed to send response. Please try again.", color=COLOR_ERROR),
                ephemeral=True
            )
        await self.stream_ai_response(interaction.user, content, placeholder, image_url)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.api_key or not self.client or self.target_channel_id == 0:
            return
        if message.author.bot or message.channel.id != self.target_channel_id:
            return

        is_reply_to_bot = (
            message.reference is not None
            and message.reference.resolved is not None
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author == self.bot.user
        )
        has_ask_prefix = message.content.lower().startswith(".ask ")

        if not has_ask_prefix and not is_reply_to_bot:
            return
        if message.author.id in self.blacklist:
            return await self.send_error_embed(message, f"{self.e.error} Access Denied", "You are blacklisted. Contact an administrator for more information.")
        cd = self.check_cooldown(message.author.id)
        if cd > 0:
            return await self.send_error_embed(message, "Cooldown", f"Please wait {int(cd)} seconds.")

        self.cooldowns[message.author.id] = time.time()
        content = message.content[5:].strip() if has_ask_prefix else message.content.strip()

        if not content and not message.attachments:
            return await self.send_error_embed(message, f"{self.e.error} Empty Message", "Please include a message.")

        image_url = None
        if message.attachments:
            att = message.attachments[0]
            if any(att.filename.lower().endswith(e) for e in ['png', 'jpg', 'jpeg', 'webp']):
                image_url = att.url

        placeholder = await message.reply("_ _")
        await self.stream_ai_response(message.author, content, placeholder, image_url)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
