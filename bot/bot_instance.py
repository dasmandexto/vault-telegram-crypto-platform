from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from config import settings

bot: Bot = None
dp: Dispatcher = Dispatcher()

def get_bot() -> Bot:
    global bot
    if bot is None and settings.BOT_TOKEN:
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
    return bot
