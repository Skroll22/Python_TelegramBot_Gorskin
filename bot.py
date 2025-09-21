import datetime
from enum import Enum, auto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
from secrets import API_TOKEN
from db import get_conn
from typing import Tuple, List

class States(Enum):
    REGISTER = auto()
    ADD_EVENT = auto()
    VIEW_EVENTS = auto()
    DELETE_EVENT = auto()

class Calendar:
    def __init__(self):
        self.conn = get_conn()
        self.user_states = {}

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
                return cursor.fetchone() is not None
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
                    '''SELECT event_name, TO_CHAR(event_date, 'DD.MM.YYYY')
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
    calendar = context.bot_data['calendar']
    user = update.message.from_user
    calendar.user_states[user.id] = None
    await update.message.reply_text(
        "Привет! Я календарный бот.\n"
        "Доступные команды:\n"
        "/register - регистрация\n"
        "/addevent - добавить событие\n"
        "/events - просмотреть события\n"
        "/delevent - удалить событие"
    )

    await calendar._ensure_user_exists(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )

async def register(update, context):
    calendar = context.bot_data['calendar']
    user = update.message.from_user

    if await calendar.is_user_registered(user.id):
        await update.message.reply_text('Вы уже зарегистрированы')
        return ConversationHandler.END

    await update.message.reply_text("Придумайте пароль:")
    return States.REGISTER


async def register_password(update, context):
    calendar = Calendar()
    user = update.message.from_user
    password = update.message.text

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
    user = update.message.from_user
    calendar = context.bot_data['calendar']
    calendar.user_states[user.id] = States.ADD_EVENT

    await update.message.reply_text(
        "Введите название и дату события в формате:\n"
        "Название Дата(ДД.ММ.ГГГГ)\n"
        "Например: Встреча 15.12.2025"
    )
    return States.ADD_EVENT

async def handle_add_event(update, context):
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    try:
        event_name, event_date = update.message.text.rsplit(' ', 1)
        datetime.datetime.strptime(event_date, '%d.%m.%Y')

        if await calendar.add_event(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                event_name=event_name,
                event_date=event_date
        ):
            await update.message.reply_text(f'Событие "{event_name}" добавлено!')
        else:
            await update.message.reply_text(f'Ошибка при добавлении события')
    except ValueError:
        await update.message.reply_text(f'Неверный формат, попробуйте ещё раз')
        return States.ADD_EVENT

    calendar.user_states[user.id] = None
    return ConversationHandler.END

async def show_events(update, context):
    calendar = context.bot_data['calendar']
    user = update.message.from_user
    events = await calendar.get_events(user.id)

    if not events:
        await update.message.reply_text("У вас нет запланированных событий.")
        return

    response = "Ваши события:\n"
    for i, (event_name, event_date) in enumerate(events, 1):
        response += f"{i}) {event_name} ({event_date})\n"

    await update.message.reply_text(response)

async def delete_event(update, context):
    user = update.message.from_user
    calendar = context.bot_data['calendar']
    events = await calendar.get_events(user.id)

    if not events:
        return await update.message.reply_text("У вас нет событий для удаления")

    response = 'Ваши события:\n'
    for i, (event_name, event_date) in enumerate(events, 1):
        response += (f"{i}) {event_name} ({event_date})\n"
                     f"Какое событие удалить?\n")
    await update.message.reply_text(response)

    calendar.user_states[user.id] = States.DELETE_EVENT
    return States.DELETE_EVENT

async def handle_delete_event(update, context):
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    try:
        event_num = int(update.message.text)
        events = await calendar.get_events(user.id)
        if 1 <= event_num <= len(events):
            event_name = events[event_num - 1][0]
            if await calendar.delete_event(user.id, event_name):
                await update.message.reply_text('Событие удалено!')
            else:
                await update.message.reply_text('Ошибка удаления')
        else:
            await update.message.reply_text('Неверный номер')
    except ValueError:
        await update.message.reply_text('Введите номер события')
    return ConversationHandler.END

async def cancel(update, context):
    user = update.message.from_user
    calendar = context.bot_data['calendar']
    calendar.user_states[user.id] = None

    await update.message.reply_text("Операция отменена")
    return ConversationHandler.END

def main():
    application = Application.builder().token(API_TOKEN).build()
    application.bot_data['calendar'] = Calendar()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('addevent', add_event),
            CommandHandler('register', register),
            CommandHandler('events', show_events),
            CommandHandler('delevent', delete_event)
        ],
        states={
            States.REGISTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
            States.ADD_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_event)],
            States.DELETE_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_event)],
            States.VIEW_EVENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_events)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()