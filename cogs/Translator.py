import discord
from utils.emojis import Emojis
from discord.ext import commands
import aiohttp
import difflib

COLOR_SUCCESS = discord.Color.from_rgb(0, 0, 0)
COLOR_ERROR = discord.Color.red()

LANGUAGES = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh-cn",
    "arabic": "ar",
    "hindi": "hi",
    "turkish": "tr",
    "dutch": "nl",
    "polish": "pl",
    "swedish": "sv",
    "greek": "el"
}


class Translator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.e = Emojis(bot)
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        await self.session.close()

    # Fuzzy language matching
    def get_language_code(self, input_lang: str):
        input_lang = input_lang.lower()

        if input_lang in LANGUAGES:
            return LANGUAGES[input_lang]

        # Try fuzzy match
        matches = difflib.get_close_matches(
            input_lang,
            LANGUAGES.keys(),
            n=1,
            cutoff=0.6
        )

        if matches:
            return LANGUAGES[matches[0]]

        return None

    async def translate_text(self, text: str, target_lang: str):
        base_url = "https://translate.googleapis.com/translate_a/single"

        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": text
        }

        async with self.session.get(base_url, params=params) as resp:
            data = await resp.json()

        translated = "".join([item[0] for item in data[0]])
        return translated

    async def send_temp_error(self, channel, title, description):
        embed = discord.Embed(
            title=title,
            description=description,
            color=COLOR_ERROR
        )
        embed.set_footer(text="This message will delete in 15 seconds.")

        msg = await channel.send(embed=embed)
        await msg.delete(delay=15)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not message.content.lower().startswith("!t"):
            return

        if not message.reference:
            await self.send_temp_error(
                message.channel,
                f"{self.e.error} Reply Required",
                "Reply to a message and type `!t <language>`"
            )
            return

        parts = message.content.split()
        language_input = "english"

        if len(parts) > 1:
            language_input = parts[1]

        target_code = self.get_language_code(language_input)

        if not target_code:
            await self.send_temp_error(
                message.channel,
                f"{self.e.error} Unsupported Language",
                "That language is not supported."
            )
            return

        try:
            replied = await message.channel.fetch_message(
                message.reference.message_id
            )
        except Exception:
            await self.send_temp_error(
                message.channel,
                f"{self.e.error} Error",
                "Could not fetch the replied message."
            )
            return

        if not replied.content:
            await self.send_temp_error(
                message.channel,
                f"{self.e.error} No Text Found",
                "That message has no text to translate."
            )
            return

        try:
            translated = await self.translate_text(
                replied.content,
                target_code
            )
        except Exception as e:
            await self.send_temp_error(
                message.channel,
                f"{self.e.error} Translation Failed",
                f"Error: {str(e)}"
            )
            return

        embed = discord.Embed(
            title=f"{self.e.language} Translation Result",
            description=f"```{translated[:4000]}```",
            color=COLOR_SUCCESS
        )

        embed.set_footer(text=f"Requested by {message.author}")

        await message.channel.send(embed=embed)

        # Delete the command message after successful translation
        try:
            await message.delete()
        except:
            pass


async def setup(bot):
    await bot.add_cog(Translator(bot))