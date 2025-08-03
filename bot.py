import datetime

from pyexpat.errors import messages
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
from secrets import API_TOKEN
from db import get_conn
from typing import Tuple, List

REGISTER_PASSWORD = 1

class Calendar:
    def __init__(self):
        self.conn = get_conn()

    async def register_user(self, user_id: int, username: str, first_name: str, last_name: str, password: str) -> bool:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO users (user_id, username, first_name, last_name, password)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        password = EXCLUDED.password
                    RETURNING user_id
                    ''', (user_id, username, first_name, last_name, password)
                )
                self.conn.commit()
                return cursor.fetchall() is not None
        except Exception as e:
            print(f'Ошибка регистрации пользователя: {e}')
            return False

    async def is_user_registered(self, user_id: int) -> bool:
        with self.conn.cursor() as cursor:
            cursor.execute('''
                SELECT 1 FROM users
                WHERE user_id = %s AND password IS not NULL
            ''', (user_id,))
            return cursor.fetchone() is not None

    async def _ensure_user_exists(self, user_id: int, username: str, first_name: str, last_name: str):
        with self.conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name
            ''', (user_id, username, first_name, last_name))
            self.conn.commit()

    async def add_event(self, user_id: int, username: str, first_name: str, last_name: str,
                        event_name = str, event_date = str) -> bool:
        try:
            if not await self.is_user_registered(user_id):
                return False

            await self._ensure_user_exists(user_id, username, first_name, last_name)

            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''INSERT INTO events (user_id, event_name, event_date)
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

    async def delete_event(self, user_id: int, event_name: int) -> bool:
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
    calendar = Calendar()
    user = update.message.from_user
    await update.message.reply_text("Привет! Я календарный бот.\n"
                                    "Напишите /register для регистрации\n"
                                    "или /addevent для добавления события.")

    await calendar._ensure_user_exists(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )

async def register(update, context):
    calendar = Calendar()
    user = update.message.from_user

    if await calendar.is_user_registered(user.id):
        await update.message.reply_text('Вы уже зарегистрированы')
        return ConversationHandler.END

    await update.message.reply_text("Придумайте пароль:")
    return REGISTER_PASSWORD


async def register_password(update, context):
    calendar = Calendar()
    user = update.message.from_user
    password = update.message.text  # Получаем текст пароля от пользователя

    if await calendar.register_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            password=password
    ):
        await update.message.reply_text("Вы успешно зарегистрированы!")
    else:
        await update.message.reply_text("Ошибка при регистрации")

    return ConversationHandler.END

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

    if await calendar.add_event(
        user_id=user_id,
        username=update.message.from_user.username,
        first_name=update.message.from_user.first_name,
        last_name=update.message.from_user.last_name,
        event_name=event_name,
        event_date=event_date
    ):
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
    for i, (event_name, event_date) in enumerate(events, 1):
        response += f"{i}) {event_name} ({event_date})\n"

    await update.message.reply_text(response)

async def delete_event(update, context):
    calendar = Calendar()
    user_id = update.message.from_user.id
    events = await calendar.get_events(user_id)

    if not events:
        await update.message.reply_text("У вас нет событий для удаления")
        return

    try:
        event_num = int(context.args[0])
        events = await calendar.get_events(user_id)

        if not 1 <= event_num <= len(events):
            await update.message.reply_text("Неверный номер события")
            return

        event_id = events[event_num-1][0]
        if await calendar.delete_event(user_id, event_id):
            await update.message.reply_text('Событие успешно удалено')
        else:
            await update.message.reply_text('Ошибка при удалении события')
    except ValueError:
        await update.message.reply_text('Номер события должен быть числом')

def main():
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('register', register)],
        states={
            REGISTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[]
    )
    application = Application.builder().token(API_TOKEN).build()
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('addevent', add_event))
    application.add_handler(CommandHandler('events', show_events))
    application.add_handler(CommandHandler('delevent', delete_event))

    application.run_polling()

if __name__ == '__main__':
    main()