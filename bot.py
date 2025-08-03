import datetime

from telegram.ext import Application, CommandHandler
from secrets import API_TOKEN
from db import get_conn
from typing import Tuple, List


class Calendar:
    def __init__(self):
        self.conn = get_conn()

    async def add_event(self, user_id: int, event_name = str, event_date = str) -> bool:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO events (user_id, event_name, event_date)'
                    VALUES (%s, %s, %s)''',
                    (user_id, event_name, event_date)
                )
                self.conn.commit()
            return True
        except Exception as e:
            print(f"Ошибка добавления события: {e}")
            return False

    async def get_events(self, user_id: int) -> List[Tuple[str, str]]:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT event_name, event_date
                    FROM events
                    WHERE user_id = %s
                    ORDER BY event_date''',
                    (user_id,)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Ошибка отображения событий: {e}")
            return []

    async def delete_event(self, user_id: int, event_name: str) -> bool:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''DELETE
                    FROM events
                    WHERE user_id = %s AND event_name = %s''',
                    (user_id, event_name,)
                )
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Ошибка удаления события: {e}")
            return False

async def start(update, context):
    await update.message.reply_text("Привет! Я календарный бот. Напишите /addevent для добавления события.")

async def add_event(update, context):
    calendar = Calendar()
    user_id = update.message.from_user.id

    if len(context.args) < 2:
        await update.message.reply_text("Используйте: '/addevent <название> <дата в формате ДД-ММ-ГГГГ>'")
        return

    event_name = ' '.join(context.args[:-1])
    event_date = context.args[-1]

    try:
        datetime.datetime.strptime(event_date, "%d-%m-%Y")
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Используйте ДД-ММ-ГГГГ")
        return

    if await calendar.add_event(user_id, event_name, event_date):
        await update.message.reply_text(f"Событие '{event_name}' на {event_date} добавлено!")
    else:
        await update.message.reply_text("Ошибка при добавлении события")

async def show_events(update, context):
    calendar = Calendar()
    user_id = update.message.from_user.id
    events = await calendar.get_events(user_id)

    if not events:
        await update.message.reply_text("У вас нет запланированных событий.")
        return

    response = 'Ваши события:\n'
    i = 1
    for event_name, event_date in events:
        response += f"{i}) {event_name} ({event_date})\n"
        i += 1

    await update.message.reply_text(response)

async def delete_events(update, context):
    calendar = Calendar()
    user_id = update.message.from_user.id
    events = await calendar.get_events(user_id)

    if not events:
        await update.message.reply_text("У вас нет событий для удаления")
        return

    print('Какое по счету событие вы хотите удалить?')

def main():
    application = Application.builder().token(API_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('addevent', add_event))
    application.add_handler(CommandHandler('events', show_events))

    application.run_polling()

if __name__ == '__main__':
    main()