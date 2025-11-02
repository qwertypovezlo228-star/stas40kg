from telegram import Bot
from telegram.ext import Application
from config import TELEGRAM_TOKEN
from telegram.request import HTTPXRequest

bot = Bot(token=TELEGRAM_TOKEN)
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
