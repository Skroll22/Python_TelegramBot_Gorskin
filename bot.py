from telegram.ext import Application, CommandHandler
from secrets import API_TOKEN
from db import get_conn


async def start(update, context):
    await update.message.reply_text("Привет! Я календарный бот. Напишите /addevent для добавления события.")

application = Application.builder().token(API_TOKEN).build()
application.add_handler(CommandHandler('start', start))

application.run_polling()
