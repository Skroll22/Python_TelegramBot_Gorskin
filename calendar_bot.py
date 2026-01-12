# calendar_bot.py
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    CallbackContext
)
from secrets import API_TOKEN, DB_CONFIG
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
DATE, TITLE, DESCRIPTION, EVENT_ID, NEW_TITLE, NEW_DESCRIPTION, REGISTER = range(7)


# Состояния пользователя
class UserState(Enum):
    IDLE = "idle"
    CREATING_EVENT = "creating_event"
    UPDATING_EVENT = "updating_event"
    VIEWING_EVENTS = "viewing_events"


class Calendar:
    def __init__(self, db_config: Dict):
        """
        Инициализация календаря с подключением к PostgreSQL
        """
        self.db_config = db_config
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Подключение к базе данных"""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            print("✅ Успешное подключение к PostgreSQL")
        except Exception as e:
            print(f"❌ Ошибка подключения к PostgreSQL: {e}")
            raise

    def create_tables(self):
        """Создание таблиц users и events, если они не существуют"""
        create_users_table = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            language_code VARCHAR(10),
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_events_table = """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);",
            "CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);",
            "CREATE INDEX IF NOT EXISTS idx_events_user_date ON events(user_id, date);"
        ]

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(create_users_table)
                cursor.execute(create_events_table)

                for index_query in create_indexes:
                    try:
                        cursor.execute(index_query)
                    except Exception as e:
                        print(f"⚠️  Не удалось создать индекс: {e}")

                self.conn.commit()
                print("✅ Таблицы users и events созданы или уже существуют")
        except Exception as e:
            print(f"❌ Ошибка создания таблиц: {e}")
            self.conn.rollback()
            raise

    def close(self):
        """Закрытие соединения с БД"""
        if self.conn:
            self.conn.close()
            print("✅ Соединение с PostgreSQL закрыто")

    def register_user(self, telegram_id: int, username: str = None,
                      first_name: str = None, last_name: str = None,
                      language_code: str = None) -> Dict[str, Any]:
        """
        Регистрация или обновление информации о пользователе

        Returns:
            Информация о пользователе
        """
        insert_query = """
        INSERT INTO users (telegram_id, username, first_name, last_name, language_code)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (telegram_id) 
        DO UPDATE SET 
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            language_code = EXCLUDED.language_code,
            last_seen = CURRENT_TIMESTAMP
        RETURNING id, telegram_id, username, first_name, last_name, registered_at;
        """

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(insert_query, (telegram_id, username, first_name, last_name, language_code))
                user = cursor.fetchone()
                self.conn.commit()
                return user
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при регистрации пользователя: {e}")
            return None

    def get_user_by_telegram_id(self, telegram_id: int) -> Dict[str, Any]:
        """Получить пользователя по telegram_id"""
        select_query = "SELECT * FROM users WHERE telegram_id = %s;"

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(select_query, (telegram_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя: {e}")
            return None

    def update_user_state(self, telegram_id: int, state: str):
        """Обновить состояние пользователя (в реальном проекте можно добавить поле в таблицу users)"""
        # Здесь можно реализовать хранение состояния в БД или кэше
        pass

    def create_event(self, telegram_id: int, date: str, title: str, description: str = "") -> str:
        """
        Создание нового события в БД

        Args:
            telegram_id: ID пользователя в Telegram
            date: Дата в формате DD.MM.YYYY
            title: Название события
            description: Описание события

        Returns:
            Сообщение о результате операции
        """
        # Получаем внутренний ID пользователя
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return "❌ Пользователь не найден. Используйте /start для регистрации."

        try:
            date_obj = datetime.datetime.strptime(date, "%d.%m.%Y").date()
        except ValueError:
            return "❌ Неверный формат даты. Используйте DD.MM.YYYY"

        insert_query = """
        INSERT INTO events (user_id, date, title, description, created_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        RETURNING id;
        """

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(insert_query, (user['id'], date_obj, title, description))
                event_id = cursor.fetchone()[0]
                self.conn.commit()
                return f"✅ Событие '{title}' на {date} создано (ID: {event_id})"
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при создании события: {e}")
            return f"❌ Ошибка при создании события: {e}"

    def read_event(self, telegram_id: int, event_id: int) -> str:
        """
        Чтение события по ID из БД

        Args:
            telegram_id: ID пользователя в Telegram
            event_id: ID события

        Returns:
            Информация о событии или сообщение об ошибке
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return "❌ Пользователь не найден."

        select_query = """
        SELECT e.id, e.date, e.title, e.description, e.created_at, e.updated_at
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE e.id = %s AND u.telegram_id = %s;
        """

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(select_query, (event_id, telegram_id))
                event = cursor.fetchone()

                if event:
                    date_str = event['date'].strftime("%d.%m.%Y")
                    created_at = event['created_at'].strftime("%d.%m.%Y %H:%M")
                    updated_at = event['updated_at'].strftime("%d.%m.%Y %H:%M") if event[
                        'updated_at'] else "Не обновлялось"

                    return (f"📅 Событие ID: {event['id']}\n"
                            f"Дата: {date_str}\n"
                            f"Название: {event['title']}\n"
                            f"Описание: {event['description'] or 'Нет описания'}\n"
                            f"Создано: {created_at}\n"
                            f"Обновлено: {updated_at}")
                else:
                    return f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"
        except Exception as e:
            logger.error(f"Ошибка при чтении события: {e}")
            return f"❌ Ошибка при чтении события: {e}"

    def update_event(self, telegram_id: int, event_id: int, title: str = None, description: str = None) -> str:
        """
        Обновление события в БД

        Args:
            telegram_id: ID пользователя в Telegram
            event_id: ID события
            title: Новое название
            description: Новое описание

        Returns:
            Сообщение о результате операции
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return "❌ Пользователь не найден."

        # Проверяем существование события у данного пользователя
        check_query = """
        SELECT e.id 
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE e.id = %s AND u.telegram_id = %s;
        """

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(check_query, (event_id, telegram_id))
                if not cursor.fetchone():
                    return f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"

                # Строим динамический запрос UPDATE
                updates = []
                params = []

                if title is not None:
                    updates.append("title = %s")
                    params.append(title)

                if description is not None:
                    updates.append("description = %s")
                    params.append(description)

                if not updates:
                    return "ℹ️ Нечего обновлять"

                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.extend([event_id])

                update_query = f"""
                UPDATE events 
                SET {', '.join(updates)}
                WHERE id = %s;
                """

                cursor.execute(update_query, params)
                self.conn.commit()

                return f"✅ Событие ID {event_id} успешно обновлено"
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при обновлении события: {e}")
            return f"❌ Ошибка при обновлении события: {e}"

    def delete_event(self, telegram_id: int, event_id: int) -> str:
        """
        Удаление события из БД

        Args:
            telegram_id: ID пользователя в Telegram
            event_id: ID события

        Returns:
            Сообщение о результате операции
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return "❌ Пользователь не найден."

        # Сначала получаем название события для сообщения
        select_query = """
        SELECT e.title 
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE e.id = %s AND u.telegram_id = %s;
        """

        delete_query = """
        DELETE FROM events 
        WHERE id = %s AND user_id = %s;
        """

        try:
            with self.conn.cursor() as cursor:
                # Получаем название
                cursor.execute(select_query, (event_id, telegram_id))
                result = cursor.fetchone()

                if not result:
                    return f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"

                title = result[0]

                # Удаляем событие
                cursor.execute(delete_query, (event_id, user['id']))
                self.conn.commit()

                return f"✅ Событие '{title}' (ID: {event_id}) удалено"
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка при удалении события: {e}")
            return f"❌ Ошибка при удалении события: {e}"

    def list_events(self, telegram_id: int, sort_by_date: bool = True) -> str:
        """
        Показать все события пользователя из БД

        Args:
            telegram_id: ID пользователя в Telegram
            sort_by_date: Сортировать по дате

        Returns:
            Список всех событий
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return "❌ Пользователь не найден."

        order_by = "ORDER BY e.date, e.id" if sort_by_date else "ORDER BY e.id"

        select_query = f"""
        SELECT e.id, e.date, e.title, e.description
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE u.telegram_id = %s
        {order_by};
        """

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(select_query, (telegram_id,))
                events = cursor.fetchall()

                if not events:
                    return "📭 В вашем календаре пока нет событий"

                result = "📅 Все события в календаре:\n\n"
                for event in events:
                    date_str = event['date'].strftime("%d.%m.%Y")
                    result += f"ID: {event['id']} | {date_str} - {event['title']}\n"
                    if event['description']:
                        result += f"   Описание: {event['description']}\n"
                    result += "─" * 40 + "\n"

                return result
        except Exception as e:
            logger.error(f"Ошибка при получении списка событий: {e}")
            return f"❌ Ошибка при получении списка событий: {e}"

    def get_events_for_date(self, telegram_id: int, date: str) -> List[Dict[str, Any]]:
        """
        Получить события на определенную дату из БД

        Args:
            telegram_id: ID пользователя в Telegram
            date: Дата в формате DD.MM.YYYY

        Returns:
            Список событий на указанную дату
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return []

        try:
            date_obj = datetime.datetime.strptime(date, "%d.%m.%Y").date()
        except ValueError:
            return []

        select_query = """
        SELECT e.id, e.title, e.description
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE u.telegram_id = %s AND e.date = %s
        ORDER BY e.id;
        """

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(select_query, (telegram_id, date_obj))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении событий на дату: {e}")
            return []

    def get_today_events(self, telegram_id: int) -> List[Dict[str, Any]]:
        """
        Получить события на сегодня из БД

        Args:
            telegram_id: ID пользователя в Telegram

        Returns:
            Список событий на сегодня
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return []

        today = datetime.date.today()

        select_query = """
        SELECT e.id, e.title, e.description
        FROM events e
        JOIN users u ON e.user_id = u.id
        WHERE u.telegram_id = %s AND e.date = %s
        ORDER BY e.id;
        """

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(select_query, (telegram_id, today))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении событий на сегодня: {e}")
            return []

    def get_user_stats(self, telegram_id: int) -> Dict[str, Any]:
        """
        Получить статистику пользователя

        Args:
            telegram_id: ID пользователя в Telegram

        Returns:
            Статистика пользователя
        """
        user = self.get_user_by_telegram_id(telegram_id)
        if not user:
            return {}

        stats_queries = {
            'total_events': """
            SELECT COUNT(*) 
            FROM events e
            JOIN users u ON e.user_id = u.id
            WHERE u.telegram_id = %s;
            """,
            'today_events': """
            SELECT COUNT(*) 
            FROM events e
            JOIN users u ON e.user_id = u.id
            WHERE u.telegram_id = %s AND e.date = CURRENT_DATE;
            """,
            'future_events': """
            SELECT COUNT(*) 
            FROM events e
            JOIN users u ON e.user_id = u.id
            WHERE u.telegram_id = %s AND e.date > CURRENT_DATE;
            """,
            'past_events': """
            SELECT COUNT(*) 
            FROM events e
            JOIN users u ON e.user_id = u.id
            WHERE u.telegram_id = %s AND e.date < CURRENT_DATE;
            """,
            'closest_event': """
            SELECT e.title, e.date 
            FROM events e
            JOIN users u ON e.user_id = u.id
            WHERE u.telegram_id = %s AND e.date >= CURRENT_DATE 
            ORDER BY e.date 
            LIMIT 1;
            """
        }

        stats = {}
        try:
            with self.conn.cursor() as cursor:
                for stat_name, query in stats_queries.items():
                    cursor.execute(query, (telegram_id,))
                    result = cursor.fetchone()
                    stats[stat_name] = result[0] if result else None
            return stats
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return {}

    def get_all_users_count(self) -> int:
        """Получить общее количество пользователей"""
        query = "SELECT COUNT(*) FROM users;"

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query)
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка при получении количества пользователей: {e}")
            return 0


# Создаем глобальный экземпляр Calendar
calendar_db = Calendar(DB_CONFIG)

# Словарь для хранения состояний пользователей (в реальном проекте лучше использовать Redis или БД)
user_states: Dict[int, UserState] = {}


def get_user_state(telegram_id: int) -> UserState:
    """Получить состояние пользователя"""
    return user_states.get(telegram_id, UserState.IDLE)


def set_user_state(telegram_id: int, state: UserState):
    """Установить состояние пользователя"""
    user_states[telegram_id] = state


# Обработчики команд
async def ensure_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка и автоматическая регистрация пользователя"""
    user = update.effective_user
    telegram_id = user.id

    # Автоматически регистрируем пользователя при первом взаимодействии
    user_info = calendar_db.register_user(
        telegram_id=telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code
    )

    if user_info:
        # Обновляем контекст с информацией о пользователе
        context.user_data['user_info'] = user_info
        return True
    else:
        await update.message.reply_text("❌ Ошибка регистрации. Попробуйте снова.")
        return False


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    welcome_text = f"""
    👋 Привет, {user.first_name}! Я многопользовательский бот-календарь.

    📊 Статистика системы:
    • Всего пользователей: {calendar_db.get_all_users_count()}

    📋 Доступные команды:
    /start - начать работу
    /help - помощь
    /profile - мой профиль
    /create - создать событие
    /read <ID> - посмотреть событие
    /update <ID> - изменить событие
    /delete <ID> - удалить событие
    /list - показать все мои события
    /today - мои события на сегодня
    /events <дата> - мои события на дату (DD.MM.YYYY)
    /stats - моя статистика
    /cancel - отменить текущее действие
    """
    await update.message.reply_text(welcome_text)
    set_user_state(user.id, UserState.IDLE)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
    📖 Справка по командам:

    👤 Учетная запись:
    /start - регистрация и начало работы
    /profile - информация о вашем профиле

    📝 Управление событиями:
    /create - создать новое событие (бот запросит данные)
    /read <ID> - посмотреть конкретное событие
    /update <ID> - изменить название или описание события
    /delete <ID> - удалить событие
    /list - все ваши события (сортировка по дате)
    /today - ваши события на сегодня
    /events <дата> - ваши события на определенную дату
    /stats - ваша статистика событий

    ⚙️ Другие команды:
    /cancel - отменить текущее действие
    /help - эта справка

    🔐 Особенности:
    • Каждый пользователь видит только свои события
    • Ваши данные защищены и доступны только вам
    • Все события хранятся в защищенной базе данных

    Примеры:
    /read 1
    /events 25.12.2024
    /delete 3
    /stats
    """
    await update.message.reply_text(help_text)
    await ensure_registered(update, context)


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /profile"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    user_info = calendar_db.get_user_by_telegram_id(user.id)

    if user_info:
        stats = calendar_db.get_user_stats(user.id)

        profile_text = f"""
        👤 Ваш профиль:

        📝 Основная информация:
        • ID: {user_info['telegram_id']}
        • Имя: {user_info['first_name'] or 'Не указано'}
        • Фамилия: {user_info['last_name'] or 'Не указано'}
        • Username: @{user_info['username'] or 'Не указано'}
        • Язык: {user_info['language_code'] or 'Не указано'}

        📅 Статистика событий:
        • Всего событий: {stats.get('total_events', 0)}
        • Сегодня: {stats.get('today_events', 0)}
        • Будущих: {stats.get('future_events', 0)}
        • Прошедших: {stats.get('past_events', 0)}

        ⏰ Учетная запись:
        • Зарегистрирован: {user_info['registered_at'].strftime('%d.%m.%Y %H:%M')}
        • Последний визит: {user_info['last_seen'].strftime('%d.%m.%Y %H:%M')}
        """

        await update.message.reply_text(profile_text)
    else:
        await update.message.reply_text("❌ Информация о профиле не найдена.")


async def create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс создания события"""
    if not await ensure_registered(update, context):
        return

    set_user_state(update.effective_user.id, UserState.CREATING_EVENT)
    await update.message.reply_text(
        "📅 Создание нового события.\n"
        "Введите дату в формате ДД.ММ.ГГГГ (например, 25.12.2024):\n"
        "Или /cancel для отмены"
    )
    return DATE


async def date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка даты события"""
    context.user_data['date'] = update.message.text
    await update.message.reply_text("Введите название события:")
    return TITLE


async def title_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка названия события"""
    context.user_data['title'] = update.message.text
    await update.message.reply_text("Введите описание события (или /skip чтобы пропустить):")
    return DESCRIPTION


async def description_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка описания события"""
    if update.message.text != '/skip':
        context.user_data['description'] = update.message.text
    else:
        context.user_data['description'] = ""

    # Создаем событие в БД
    user_id = update.effective_user.id

    result = calendar_db.create_event(
        telegram_id=user_id,
        date=context.user_data['date'],
        title=context.user_data['title'],
        description=context.user_data.get('description', '')
    )

    set_user_state(user_id, UserState.IDLE)
    await update.message.reply_text(result)
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    user_id = update.effective_user.id
    current_state = get_user_state(user_id)

    if current_state != UserState.IDLE:
        set_user_state(user_id, UserState.IDLE)
        await update.message.reply_text("❌ Действие отменено. Возвращаюсь в главное меню.")
    else:
        await update.message.reply_text("ℹ️ Нет активных действий для отмены.")

    return ConversationHandler.END


async def read_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /read"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите ID события. Пример: /read 1")
        return

    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID события должен быть числом. Пример: /read 1")
        return

    user_id = update.effective_user.id
    result = calendar_db.read_event(user_id, event_id)
    await update.message.reply_text(result)


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /delete"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите ID события. Пример: /delete 1")
        return

    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID события должен быть числом. Пример: /delete 1")
        return

    user_id = update.effective_user.id
    result = calendar_db.delete_event(user_id, event_id)
    await update.message.reply_text(result)


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /list"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    result = calendar_db.list_events(user_id)
    await update.message.reply_text(result)


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /today"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    events = calendar_db.get_today_events(user_id)

    if not events:
        today = datetime.date.today().strftime("%d.%m.%Y")
        await update.message.reply_text(f"📭 На сегодня ({today}) нет запланированных событий.")
        return

    result = f"📅 Ваши события на сегодня ({datetime.date.today().strftime('%d.%m.%Y')}):\n\n"
    for event in events:
        result += f"ID: {event['id']} - {event['title']}\n"
        if event['description']:
            result += f"   {event['description']}\n"
        result += "─" * 30 + "\n"

    await update.message.reply_text(result)


async def events_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /events"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите дату. Пример: /events 25.12.2024")
        return

    date = context.args[0]
    user_id = update.effective_user.id
    events = calendar_db.get_events_for_date(user_id, date)

    if not events:
        await update.message.reply_text(f"📭 На {date} у вас нет запланированных событий.")
        return

    result = f"📅 Ваши события на {date}:\n\n"
    for event in events:
        result += f"ID: {event['id']} - {event['title']}\n"
        if event['description']:
            result += f"   {event['description']}\n"
        result += "─" * 30 + "\n"

    await update.message.reply_text(result)


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    stats = calendar_db.get_user_stats(user_id)

    if not stats:
        await update.message.reply_text("❌ Не удалось получить статистику.")
        return

    result = "📊 Статистика ваших событий:\n\n"
    result += f"Всего событий: {stats.get('total_events', 0)}\n"
    result += f"Событий сегодня: {stats.get('today_events', 0)}\n"
    result += f"Будущих событий: {stats.get('future_events', 0)}\n"
    result += f"Прошедших событий: {stats.get('past_events', 0)}\n\n"

    if stats.get('closest_event'):
        closest_date = stats['closest_event'][1].strftime("%d.%m.%Y") if stats['closest_event'][1] else "Неизвестно"
        result += f"Ближайшее событие: {stats['closest_event'][0]}\n"
        result += f"Дата: {closest_date}"
    else:
        result += "Ближайших событий нет"

    await update.message.reply_text(result)


async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /update"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите ID события. Пример: /update 1")
        return

    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID события должен быть числом. Пример: /update 1")
        return

    user_id = update.effective_user.id

    # Проверяем, есть ли дополнительные параметры
    if len(context.args) >= 3:
        # Формат: /update ID "новое название" "новое описание"
        new_title = context.args[1].strip('"')
        new_description = context.args[2].strip('"') if len(context.args) > 2 else None
        result = calendar_db.update_event(user_id, event_id, new_title, new_description)
        await update.message.reply_text(result)
    else:
        set_user_state(user_id, UserState.UPDATING_EVENT)

        # Получаем текущее событие для отображения
        current_event_info = calendar_db.read_event(user_id, event_id)

        if "❌" in current_event_info:
            await update.message.reply_text(current_event_info)
            set_user_state(user_id, UserState.IDLE)
            return ConversationHandler.END

        await update.message.reply_text(
            f"{current_event_info}\n\n"
            f"Введите новое название (или /skip чтобы оставить текущее):"
        )
        context.user_data['update_event_id'] = event_id
        return NEW_TITLE


async def new_title_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового названия события"""
    if update.message.text != '/skip':
        context.user_data['new_title'] = update.message.text
    else:
        context.user_data['new_title'] = None

    await update.message.reply_text(
        "Введите новое описание (или /skip чтобы оставить текущее):"
    )
    return NEW_DESCRIPTION


async def new_description_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового описания события"""
    if update.message.text != '/skip':
        context.user_data['new_description'] = update.message.text
    else:
        context.user_data['new_description'] = None

    # Обновляем событие в БД
    user_id = update.effective_user.id
    event_id = context.user_data['update_event_id']

    result = calendar_db.update_event(
        user_id,
        event_id,
        context.user_data.get('new_title'),
        context.user_data.get('new_description')
    )

    set_user_state(user_id, UserState.IDLE)
    await update.message.reply_text(result)
    return ConversationHandler.END


async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик неизвестных команд"""
    await ensure_registered(update, context)

    current_state = get_user_state(update.effective_user.id)

    if current_state != UserState.IDLE:
        await update.message.reply_text(
            "⚠️  Сначала завершите текущее действие или отмените его командой /cancel."
        )
    else:
        await update.message.reply_text(
            "❌ Извините, я не понимаю эту команду.\n"
            "Используйте /help для списка команд."
        )


def main():
    """Основная функция бота"""
    # Создаем Application
    application = Application.builder().token(API_TOKEN).build()

    # Создаем ConversationHandler для создания событий
    create_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('create', create_handler)],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_handler)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_handler)],
            DESCRIPTION: [MessageHandler(filters.TEXT, description_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    # Создаем ConversationHandler для обновления событий
    update_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('update', update_handler)],
        states={
            NEW_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_title_handler)],
            NEW_DESCRIPTION: [MessageHandler(filters.TEXT, new_description_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    # Регистрируем обработчики команд
    application.add_handler(create_conv_handler)
    application.add_handler(update_conv_handler)
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("profile", profile_handler))
    application.add_handler(CommandHandler("read", read_handler))
    application.add_handler(CommandHandler("delete", delete_handler))
    application.add_handler(CommandHandler("list", list_handler))
    application.add_handler(CommandHandler("today", today_handler))
    application.add_handler(CommandHandler("events", events_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("cancel", cancel_handler))

    # Обработчик неизвестных команд (должен быть последним)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_handler))

    # Запускаем бота
    print("📅 Многопользовательский бот-календарь запускается...")
    print("🌐 Подключение к PostgreSQL...")
    print(f"👥 Всего пользователей в системе: {calendar_db.get_all_users_count()}")
    print("Используйте Ctrl+C для остановки")

    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    finally:
        # Закрываем соединение с БД при завершении работы
        calendar_db.close()


if __name__ == '__main__':
    main()