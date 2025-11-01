import datetime
import json
import requests
from enum import Enum, auto
from django.db import connection, models
from django.apps import apps
from asgiref.sync import sync_to_async

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
from my_secrets import API_TOKEN
from db import get_conn
from typing import Tuple, List, Dict

class States(Enum):
    REGISTER = auto()
    ADD_EVENT = auto()
    VIEW_EVENTS = auto()
    DELETE_EVENT = auto()
    EDIT_EVENT = auto()
    EDIT_EVENT_CHOOSE = auto()
    EDIT_EVENT_NEW_DATA = auto()
    CREATE_MEETING = auto()
    MEETING_TITLE = auto()
    MEETING_DATE = auto()
    MEETING_TIME = auto()
    MEETING_DURATION = auto()
    MEETING_PARTICIPANTS = auto()
    MEETING_DESCRIPTION = auto()
    SHARE_EVENT = auto()
    EXPORT_EVENTS = auto()

class Calendar:
    def __init__(self):
        self.conn = get_conn()
        self.user_states = {}

    async def update_statistics(self):
        """Обновление статистики в базе Django"""
        try:
            # Импортируем модель здесь, чтобы избежать циклических импортов
            BotStatistics = apps.get_model('myapp', 'BotStatistics')

            with self.conn.cursor() as cursor:
                # Получаем текущую статистику
                cursor.execute('SELECT COUNT(*) FROM users WHERE password IS NOT NULL')
                total_users = cursor.fetchone()[0]

                cursor.execute('SELECT COUNT(*) FROM events')
                total_events = cursor.fetchone()[0]

                cursor.execute('SELECT COUNT(DISTINCT user_id) FROM events')
                active_users = cursor.fetchone()[0]

            await self._update_statistics_async(total_users, total_events, active_users)

        except Exception as e:
            print(f'Ошибка обновления статистики: {e}')

    @sync_to_async
    def _update_statistics_async(self, total_users, total_events, active_users):
        """Синхронный метод для обновления статистики"""
        try:
            BotStatistics = apps.get_model('myapp', 'BotStatistics')
            today = datetime.date.today()
            stats, created = BotStatistics.objects.get_or_create(date=today)

            # Обновляем статистику
            stats.total_users = total_users
            stats.total_events = total_events
            stats.active_users = active_users
            stats.save()
        except Exception as e:
            print(f'Ошибка в _update_statistics_async: {e}')

    @sync_to_async
    def increment_deleted_events(self):
        """Увеличивает счетчик удаленных событий"""
        try:
            BotStatistics = apps.get_model('myapp', 'BotStatistics')
            today = datetime.date.today()
            stats, created = BotStatistics.objects.get_or_create(date=today)
            stats.deleted_events += 1
            stats.save()
        except Exception as e:
            print(f'Ошибка увеличения счетчика удаленных событий: {e}')

    @sync_to_async
    def increment_edited_events(self):
        """Увеличивает счетчик измененных событий"""
        try:
            BotStatistics = apps.get_model('myapp', 'BotStatistics')
            today = datetime.date.today()
            stats, created = BotStatistics.objects.get_or_create(date=today)
            stats.edited_events += 1
            stats.save()
        except Exception as e:
            print(f'Ошибка увеличения счетчика измененных событий: {e}')

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
                result = cursor.fetchone() is not None

                if result:
                    await self.update_statistics()

                return result
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
                        event_name: str, event_date: str) -> bool:
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
            await self.update_statistics()
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

    async def get_event_by_index(self, user_id: int, event_index: int) -> Tuple[str, str]:
        """Получить событие по индексу"""
        try:
            events = await self.get_events(user_id)
            if 0 <= event_index < len(events):
                return events[event_index]
            return None
        except Exception as e:
            print(f"Ошибка получения события по индексу: {e}")
            return None

    async def update_event(self, user_id: int, old_event_name: str, new_event_name: str, new_event_date: str) -> bool:
        """Обновить событие"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''UPDATE events 
                    SET event_name = %s, event_date = %s 
                    WHERE user_id = %s AND event_name = %s''',
                    (new_event_name, new_event_date, user_id, old_event_name)
                )
                self.conn.commit()
                result = cursor.rowcount > 0

                if result:
                    await self.increment_edited_events()
                    await self.update_statistics()

                return result
        except Exception as e:
            print(f"Ошибка обновления события: {e}")
            return False

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
                result = cursor.rowcount > 0

                if result:
                    await self.increment_deleted_events()
                    await self.update_statistics()

                return result

        except Exception as e:
            print(f"Ошибка удаления события: {e}")
            return False

    @sync_to_async
    def create_meeting(self, title, description, meeting_date, meeting_time, duration, organizer, participants):
        """Создать новую встречу"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')
            MeetingInvitation = apps.get_model('myapp', 'MeetingInvitation')

            # Создаем встречу
            meeting = Meeting.objects.create(
                title=title,
                description=description,
                meeting_date=meeting_date,
                meeting_time=meeting_time,
                duration=duration,
                organizer=organizer,
                participants=participants,
                status='pending'
            )

            # Создаем приглашения для участников
            for participant_id in participants:
                MeetingInvitation.objects.create(
                    meeting=meeting,
                    participant_id=participant_id,
                    status='pending'
                )

            return meeting.id
        except Exception as e:
            print(f'Ошибка создания встречи: {e}')
            return None

    @sync_to_async
    def get_user_busy_slots(self, user_id, target_date):
        """Получить занятые временные интервалы пользователя"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')

            # Получаем встречи пользователя на указанную дату
            meetings = Meeting.objects.filter(
                meeting_date=target_date
            ).filter(
                models.Q(organizer=user_id) | models.Q(participants__contains=[user_id])
            ).exclude(
                status__in=['cancelled', 'declined']
            )

            busy_slots = []
            for meeting in meetings:
                start_time = meeting.meeting_time
                end_time = (datetime.datetime.combine(datetime.date(1, 1, 1), meeting.meeting_time) +
                            datetime.timedelta(minutes=meeting.duration)).time()

                busy_slots.append({
                    'start': start_time,
                    'end': end_time,
                    'title': meeting.title,
                    'meeting_id': meeting.id
                })

            return busy_slots
        except Exception as e:
            print(f'Ошибка получения занятых слотов пользователя {user_id}: {e}')
            return []

    @sync_to_async
    def is_user_available(self, user_id, meeting_date, meeting_time, duration):
        """Проверить, свободен ли пользователь в указанное время"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')

            # Получаем все встречи пользователя на указанную дату
            meetings = Meeting.objects.filter(
                meeting_date=meeting_date
            ).filter(
                models.Q(organizer=user_id) | models.Q(participants__contains=[user_id])
            ).exclude(
                status__in=['cancelled', 'declined']
            )

            meeting_start = meeting_time
            meeting_end = (datetime.datetime.combine(datetime.date(1, 1, 1), meeting_time) +
                           datetime.timedelta(minutes=duration)).time()

            for meeting in meetings:
                slot_start = meeting.meeting_time
                slot_end = (datetime.datetime.combine(datetime.date(1, 1, 1), meeting.meeting_time) +
                            datetime.timedelta(minutes=meeting.duration)).time()

                # Проверяем пересечение временных интервалов
                # Встречи пересекаются если:
                # - начало новой встречи внутри существующей ИЛИ
                # - конец новой встречи внутри существующей ИЛИ
                # - новая встреча полностью содержит существующую
                if (meeting_start < slot_end and meeting_end > slot_start):
                    return False, meeting.title

            return True, None

        except Exception as e:
            print(f'Ошибка проверки доступности пользователя {user_id}: {e}')
            return True, None  # В случае ошибки считаем пользователя доступным

    @sync_to_async
    def get_user_meetings(self, user_id, status=None):
        """Получить встречи пользователя"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')

            query = Meeting.objects.filter(
                models.Q(organizer=user_id) | models.Q(participants__contains=[user_id])
            )

            if status:
                query = query.filter(status=status)

            return list(query.order_by('meeting_date', 'meeting_time'))
        except Exception as e:
            print(f'Ошибка получения встреч: {e}')
            return []

    @sync_to_async
    def update_meeting_status(self, meeting_id, status):
        """Обновить статус встречи"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')
            meeting = Meeting.objects.get(id=meeting_id)
            meeting.status = status
            meeting.save()
            return True
        except Exception as e:
            print(f'Ошибка обновления статуса встречи: {e}')
            return False

    @sync_to_async
    def respond_to_invitation(self, meeting_id, participant_id, response):
        """Обработать ответ на приглашение"""
        try:
            MeetingInvitation = apps.get_model('myapp', 'MeetingInvitation')
            Meeting = apps.get_model('myapp', 'Meeting')

            invitation = MeetingInvitation.objects.get(
                meeting_id=meeting_id,
                participant_id=participant_id
            )

            invitation.status = 'accepted' if response else 'declined'
            invitation.responded_at = datetime.datetime.now()
            invitation.save()

            # Обновляем статус встречи если нужно
            meeting = Meeting.objects.get(id=meeting_id)
            if response:
                # Если все приняли, меняем статус на confirmed
                pending_invitations = MeetingInvitation.objects.filter(
                    meeting_id=meeting_id,
                    status='pending'
                ).count()
                if pending_invitations == 0:
                    meeting.status = 'confirmed'
                    meeting.save()
            else:
                meeting.status = 'declined'
                meeting.save()

            return True
        except Exception as e:
            print(f'Ошибка обработки приглашения: {e}')
            return False

    @sync_to_async
    def get_meeting_by_id(self, meeting_id):
        """Получить встречу по ID"""
        try:
            Meeting = apps.get_model('myapp', 'Meeting')
            return Meeting.objects.get(id=meeting_id)
        except Meeting.DoesNotExist:
            return None

    async def get_user_events(self, user_id: int) -> List[Tuple[int, str, str, bool]]:
        """Получить события пользователя с ID событий"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, event_name, TO_CHAR(event_date, 'DD.MM.YYYY'), is_public
                    FROM events
                    WHERE user_id = %s
                    ORDER BY event_date''',
                    (user_id,)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Ошибка получения событий пользователя: {e}")
            return []

    async def toggle_event_visibility(self, event_id: int, user_id: int) -> bool:
        """Переключить видимость события (публичное/приватное)"""
        try:
            with self.conn.cursor() as cursor:
                # Получаем текущее состояние
                cursor.execute(
                    '''SELECT is_public FROM events WHERE id = %s AND user_id = %s''',
                    (event_id, user_id)
                )
                result = cursor.fetchone()

                if not result:
                    print(f"DEBUG: Event {event_id} not found for user {user_id}")
                    return False

                current_public = result[0]
                new_public = not current_public

                print(
                    f"DEBUG: Toggling visibility - event_id: {event_id}, current: {current_public}, new: {new_public}")

                # Обновляем статус
                if new_public:
                    # Делаем публичным
                    cursor.execute(
                        '''UPDATE events 
                        SET is_public = true, shared_by = %s
                        WHERE id = %s AND user_id = %s''',
                        (user_id, event_id, user_id)
                    )
                else:
                    # Делаем приватным
                    cursor.execute(
                        '''UPDATE events 
                        SET is_public = false, shared_by = NULL
                        WHERE id = %s AND user_id = %s''',
                        (event_id, user_id)
                    )

                self.conn.commit()
                success = cursor.rowcount > 0
                print(f"DEBUG: Update successful: {success}")
                return success

        except Exception as e:
            print(f"Ошибка переключения видимости события: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return False

    async def get_public_events(self, exclude_user_id: int = None) -> List[Tuple[str, str, str]]:
        """Получить публичные события других пользователей"""
        try:
            with self.conn.cursor() as cursor:
                if exclude_user_id:
                    cursor.execute(
                        '''SELECT e.event_name, TO_CHAR(e.event_date, 'DD.MM.YYYY'), 
                                  u.username, u.first_name, u.last_name
                        FROM events e
                        JOIN users u ON e.shared_by = u.user_id
                        WHERE e.is_public = true AND e.shared_by != %s
                        ORDER BY e.event_date''',
                        (exclude_user_id,)
                    )
                else:
                    cursor.execute(
                        '''SELECT e.event_name, TO_CHAR(e.event_date, 'DD.MM.YYYY'), 
                                  u.username, u.first_name, u.last_name
                        FROM events e
                        JOIN users u ON e.shared_by = u.user_id
                        WHERE e.is_public = true
                        ORDER BY e.event_date'''
                    )
                return cursor.fetchall()
        except Exception as e:
            print(f"Ошибка получения публичных событий: {e}")
            return []

    async def get_event_by_id(self, event_id: int, user_id: int) -> Tuple:
        """Получить событие по ID с проверкой владельца"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, event_name, TO_CHAR(event_date, 'DD.MM.YYYY'), is_public
                    FROM events
                    WHERE id = %s AND user_id = %s''',
                    (event_id, user_id)
                )
                result = cursor.fetchone()
                print(f"DEBUG: get_event_by_id - event_id: {event_id}, user_id: {user_id}, result: {result}")  # Отладка
                return result
        except Exception as e:
            print(f"Ошибка получения события по ID: {e}")
            return None

    async def export_events(self, user_id: int, format_type: str = 'json'):
        """Экспорт событий пользователя"""
        try:
            export_url = "http://localhost:8000/export-events/"

            data = {
                'user_id': user_id,
                'format': format_type
            }

            response = requests.post(
                export_url,
                json=data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                if format_type == 'csv':
                    return response.content, 'csv'
                else:
                    return response.json(), 'json'
            else:
                print(f"Ошибка экспорта: {response.status_code} - {response.text}")
                return None, None

        except Exception as e:
            print(f"Ошибка при экспорте событий: {e}")
            return None, None

async def create_meeting_start(update, context):
    """Начало создания встречи"""
    user = update.message.from_user

    await update.message.reply_text(
        "Давайте создадим встречу! 📅\n"
        "Введите название встречи:"
    )
    return States.MEETING_TITLE


async def meeting_title(update, context):
    """Обработка названия встречи"""
    context.user_data['meeting_title'] = update.message.text

    await update.message.reply_text(
        "Введите дату встречи (ДД.ММ.ГГГГ):\n"
        "Например: 25.12.2024"
    )
    return States.MEETING_DATE


async def meeting_date(update, context):
    """Обработка даты встречи"""
    try:
        meeting_date = datetime.datetime.strptime(update.message.text, '%d.%m.%Y').date()
        context.user_data['meeting_date'] = meeting_date

        await update.message.reply_text(
            "Введите время встречи (ЧЧ:ММ):\n"
            "Например: 14:30"
        )
        return States.MEETING_TIME
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Попробуйте снова:")
        return States.MEETING_DATE


async def meeting_time(update, context):
    """Обработка времени встречи"""
    try:
        meeting_time = datetime.datetime.strptime(update.message.text, '%H:%M').time()
        context.user_data['meeting_time'] = meeting_time

        await update.message.reply_text(
            "Введите длительность встречи в минутах:\n"
            "Например: 60 (для 1 часа)"
        )
        return States.MEETING_DURATION
    except ValueError:
        await update.message.reply_text("Неверный формат времени. Попробуйте снова:")
        return States.MEETING_TIME


async def meeting_duration(update, context):
    """Обработка длительности встречи"""
    try:
        duration = int(update.message.text)
        context.user_data['meeting_duration'] = duration

        await update.message.reply_text(
            "Введите ID участников через запятую:\n"
            "Например: 123456789, 987654321\n\n"
            "ID можно узнать с помощью команды /myid"
        )
        return States.MEETING_PARTICIPANTS
    except ValueError:
        await update.message.reply_text("Введите число (длительность в минутах):")
        return States.MEETING_DURATION


async def meeting_participants(update, context):
    """Обработка участников встречи"""
    try:
        participants_text = update.message.text
        participants = [int(pid.strip()) for pid in participants_text.split(',')]
        context.user_data['meeting_participants'] = participants

        await update.message.reply_text(
            "Введите описание встречи (или отправьте '-' чтобы пропустить):"
        )
        return States.MEETING_DESCRIPTION
    except ValueError:
        await update.message.reply_text("Неверный формат ID. Попробуйте снова:")
        return States.MEETING_PARTICIPANTS


async def meeting_description(update, context):
    """Обработка описания встречи и создание встречи"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    description = update.message.text
    if description == '-':
        description = ''

    # Получаем данные из контекста
    title = context.user_data.get('meeting_title')
    meeting_date = context.user_data.get('meeting_date')
    meeting_time = context.user_data.get('meeting_time')
    duration = context.user_data.get('meeting_duration')
    participants = context.user_data.get('meeting_participants', [])

    # Проверяем доступность организатора
    is_available, busy_with = await calendar.is_user_available(
        user.id, meeting_date, meeting_time, duration
    )

    if not is_available:
        await update.message.reply_text(
            f"❌ Вы заняты в это время!\n"
            f"У вас уже запланировано: {busy_with}\n"
            f"Пожалуйста, выберите другое время."
        )
        # Очищаем контекст
        context.user_data.clear()
        return ConversationHandler.END

    # Проверяем доступность участников
    unavailable_participants = []
    for participant_id in participants:
        is_available, busy_with = await calendar.is_user_available(
            participant_id, meeting_date, meeting_time, duration
        )
        if not is_available:
            unavailable_participants.append(f"{participant_id} (занят: {busy_with})")

    if unavailable_participants:
        await update.message.reply_text(
            f"❌ Некоторые участники заняты:\n" +
            "\n".join(unavailable_participants) +
            f"\n\nХотите все равно создать встречу? (да/нет)"
        )
        context.user_data['unavailable_participants'] = unavailable_participants
        context.user_data['meeting_data'] = {
            'title': title,
            'description': description,
            'meeting_date': meeting_date,
            'meeting_time': meeting_time,
            'duration': duration,
            'participants': participants,
            'organizer': user.id
        }
        return States.CREATE_MEETING
    else:
        # Все участники свободны, создаем встречу
        meeting_id = await calendar.create_meeting(
            title, description, meeting_date, meeting_time,
            duration, user.id, participants
        )

        if meeting_id:
            # Отправляем приглашения участникам
            for participant_id in participants:
                try:
                    await context.bot.send_message(
                        chat_id=participant_id,
                        text=f"📅 Вас приглашают на встречу!\n\n"
                             f"Название: {title}\n"
                             f"Дата: {meeting_date.strftime('%d.%m.%Y')}\n"
                             f"Время: {meeting_time.strftime('%H:%M')}\n"
                             f"Длительность: {duration} мин.\n"
                             f"Организатор: @{user.username or 'N/A'}\n"
                             f"Описание: {description or 'нет'}\n\n"
                             f"Подтвердите участие с помощью команды /meetings"
                    )
                except Exception as e:
                    print(f"Не удалось отправить сообщение пользователю {participant_id}: {e}")

            await update.message.reply_text(
                f"✅ Встреча '{title}' создана!\n"
                f"Приглашения отправлены участникам.\n"
                f"ID встречи: {meeting_id}"
            )
        else:
            await update.message.reply_text("❌ Ошибка при создании встречи")

    # Очищаем контекст
    context.user_data.clear()
    return ConversationHandler.END


async def confirm_meeting_creation(update, context):
    """Подтверждение создания встречи с занятыми участниками"""
    user_response = update.message.text.lower()

    if user_response in ['да', 'yes', 'y', 'д']:
        calendar = context.bot_data['calendar']
        meeting_data = context.user_data.get('meeting_data', {})

        meeting_id = await calendar.create_meeting(
            meeting_data['title'],
            meeting_data['description'],
            meeting_data['meeting_date'],
            meeting_data['meeting_time'],
            meeting_data['duration'],
            meeting_data['organizer'],
            meeting_data['participants']
        )

        if meeting_id:
            # Отправляем приглашения (как в предыдущей функции)
            for participant_id in meeting_data['participants']:
                try:
                    await context.bot.send_message(
                        chat_id=participant_id,
                        text=f"📅 Вас приглашают на встречу!\n\n"
                             f"Название: {meeting_data['title']}\n"
                             f"Дата: {meeting_data['meeting_date'].strftime('%d.%m.%Y')}\n"
                             f"Время: {meeting_data['meeting_time'].strftime('%H:%M')}\n"
                             f"Длительность: {meeting_data['duration']} мин.\n"
                             f"Организатор: @{update.message.from_user.username or 'N/A'}\n"
                             f"Описание: {meeting_data['description'] or 'нет'}\n\n"
                             f"Подтвердите участие с помощью команды /meetings"
                    )
                except Exception as e:
                    print(f"Не удалось отправить сообщение пользователю {participant_id}: {e}")

            await update.message.reply_text(
                f"✅ Встреча '{meeting_data['title']}' создана!\n"
                f"Приглашения отправлены участникам.\n"
                f"ID встречи: {meeting_id}"
            )
        else:
            await update.message.reply_text("❌ Ошибка при создании встречи")
    else:
        await update.message.reply_text("❌ Создание встречи отменено")

    # Очищаем контекст
    context.user_data.clear()
    return ConversationHandler.END


async def show_my_meetings(update, context):
    """Показать встречи пользователя"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    meetings = await calendar.get_user_meetings(user.id)

    if not meetings:
        await update.message.reply_text("У вас нет запланированных встреч.")
        return

    response = "📅 Ваши встречи:\n\n"
    for meeting in meetings:
        status_emoji = {
            'pending': '⏳',
            'confirmed': '✅',
            'cancelled': '❌',
            'declined': '🚫'
        }.get(meeting.status, '📅')

        response += (
            f"{status_emoji} {meeting.title}\n"
            f"📅 {meeting.meeting_date.strftime('%d.%m.%Y')} ⏰ {meeting.meeting_time.strftime('%H:%M')}\n"
            f"👤 Организатор: {meeting.organizer}\n"
            f"📊 Статус: {meeting.get_status_display()}\n"
            f"🆔 ID: {meeting.id}\n\n"
        )

    await update.message.reply_text(response)


async def show_meeting_invitations(update, context):
    """Показать приглашения на встречи"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    # Получаем встречи со статусом pending где пользователь участник
    pending_meetings = await calendar.get_user_meetings(user.id, 'pending')

    if not pending_meetings:
        await update.message.reply_text("У вас нет pending приглашений на встречи.")
        return

    response = "📨 Ваши приглашения на встречи:\n\n"
    keyboard = []

    for meeting in pending_meetings:
        response += (
            f"📅 {meeting.title}\n"
            f"Дата: {meeting.meeting_date.strftime('%d.%m.%Y')}\n"
            f"Время: {meeting.meeting_time.strftime('%H:%M')}\n"
            f"Организатор: {meeting.organizer}\n"
            f"Описание: {meeting.description or 'нет'}\n\n"
        )

        # Добавляем кнопки для ответа
        keyboard.append([
            InlineKeyboardButton(f"✅ Принять {meeting.id}", callback_data=f"accept_{meeting.id}"),
            InlineKeyboardButton(f"❌ Отклонить {meeting.id}", callback_data=f"decline_{meeting.id}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(response, reply_markup=reply_markup)


async def handle_meeting_response(update, context):
    """Обработка ответа на приглашение"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    calendar = context.bot_data['calendar']

    callback_data = query.data
    meeting_id = int(callback_data.split('_')[1])
    response = callback_data.split('_')[0] == 'accept'

    # Обрабатываем ответ
    success = await calendar.respond_to_invitation(meeting_id, user.id, response)

    if success:
        meeting = await calendar.get_meeting_by_id(meeting_id)
        status_text = "принял" if response else "отклонил"

        await query.edit_message_text(
            f"Вы {status_text} приглашение на встречу '{meeting.title}'"
        )

        # Уведомляем организатора
        try:
            await context.bot.send_message(
                chat_id=meeting.organizer,
                text=f"Участник {user.username or user.id} {status_text} ваше приглашение на встречу '{meeting.title}'"
            )
        except Exception as e:
            print(f"Не удалось уведомить организатора: {e}")
    else:
        await query.edit_message_text("❌ Ошибка при обработке вашего ответа")


async def export_events(update, context):
    """Начало процесса экспорта событий"""
    user = update.message.from_user

    keyboard = [
        [InlineKeyboardButton("📊 JSON", callback_data="export_json")],
        [InlineKeyboardButton("📈 CSV", callback_data="export_csv")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_export")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📤 Выберите формат для экспорта ваших событий:",
        reply_markup=reply_markup
    )

    return States.EXPORT_EVENTS


async def handle_export_choice(update, context):
    """Обработка выбора формата экспорта"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    calendar = context.bot_data['calendar']

    if query.data == "cancel_export":
        await query.edit_message_text("❌ Экспорт отменен")
        return ConversationHandler.END

    format_type = query.data.replace('export_', '')  # json или csv

    await query.edit_message_text(f"⏳ Подготавливаю экспорт в формате {format_type.upper()}...")

    # Выполняем экспорт
    result, result_type = await calendar.export_events(user.id, format_type)

    if result:
        if format_type == 'csv':
            # Отправляем CSV файл
            await context.bot.send_document(
                chat_id=user.id,
                document=result,
                filename=f"events_{user.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                caption="✅ Ваши события успешно экспортированы в CSV формате!"
            )
        else:
            # Отправляем JSON как текстовое сообщение (или файлом)
            json_text = json.dumps(result, ensure_ascii=False, indent=2)

            # Если JSON слишком большой, отправляем файлом
            if len(json_text) > 4000:
                json_file = json_text.encode('utf-8')
                await context.bot.send_document(
                    chat_id=user.id,
                    document=json_file,
                    filename=f"events_{user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    caption="✅ Ваши события успешно экспортированы в JSON формате!"
                )
            else:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=f"```json\n{json_text}\n```",
                    parse_mode='MarkdownV2'
                )

        await query.edit_message_text(f"✅ Экспорт завершен! Данные отправлены.")
    else:
        await query.edit_message_text("❌ Ошибка при экспорте событий. Попробуйте позже.")

    return ConversationHandler.END


async def show_my_id(update, context):
    """Показать ID пользователя"""
    user = update.message.from_user
    await update.message.reply_text(f"🆔 Ваш ID: {user.id}")

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
        "/delevent - удалить событие\n"
        "/edit - редактировать событие\n"
        "/share - поделиться событием\n"
        "/publicevents - общие события\n"
        "/createmeeting - создать встречу\n"
        "/meetings - мои встречи\n"
        "/invitations - приглашения\n"
        "/myid - мой ID\n"
        "/export - экспорт событий"
    )

    await calendar._ensure_user_exists(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
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
    calendar = context.bot_data['calendar']
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
        response += f"{i}) {event_name} ({event_date})\n"
    response += '\nКакое событие удалить? (введите номер)'
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


async def edit_event(update, context):
    """Начало процесса редактирования - показываем список событий"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']
    events = await calendar.get_events(user.id)

    if not events:
        await update.message.reply_text("У вас нет событий для редактирования")
        return ConversationHandler.END

    # Сохраняем события в контексте для дальнейшего использования
    context.user_data['events_to_edit'] = events

    response = 'Ваши события:\n'
    for i, (event_name, event_date) in enumerate(events, 1):
        response += f"{i}) {event_name} ({event_date})\n"
    response += '\nКакое событие хотите отредактировать? (введите номер)'

    await update.message.reply_text(response)
    return States.EDIT_EVENT_CHOOSE


async def share_event(update, context):
    """Начало процесса публикации события"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    events = await calendar.get_user_events(user.id)

    if not events:
        await update.message.reply_text("У вас нет событий для публикации.")
        return ConversationHandler.END

    # Создаем клавиатуру с событиями
    keyboard = []
    for event_id, event_name, event_date, is_public in events:
        status = "🔓 Публичное" if is_public else "🔒 Приватное"
        keyboard.append([
            InlineKeyboardButton(
                f"{event_name} ({event_date}) - {status}",
                callback_data=f"share_{event_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_share")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📤 Выберите событие для изменения видимости:\n"
        "🔓 - событие видно другим пользователям\n"
        "🔒 - событие приватное",
        reply_markup=reply_markup
    )

    return States.SHARE_EVENT


async def handle_share_choice(update, context):
    """Обработка выбора события для публикации"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    calendar = context.bot_data['calendar']

    if query.data == "cancel_share":
        await query.edit_message_text("❌ Операция отменена")
        return ConversationHandler.END

    try:
        # Извлекаем event_id из callback_data
        event_id = int(query.data.split('_')[1])
        print(f"DEBUG: Processing event_id {event_id} for user {user.id}")  # Для отладки

        # Получаем информацию о событии
        event = await calendar.get_event_by_id(event_id, user.id)
        if not event:
            await query.edit_message_text("❌ Событие не найдено")
            return ConversationHandler.END

        event_id, event_name, event_date, is_public = event
        print(f"DEBUG: Event found - {event_name}, current public: {is_public}")  # Для отладки

        # Переключаем видимость
        success = await calendar.toggle_event_visibility(event_id, user.id)

        if success:
            new_status = "публичным" if not is_public else "приватным"
            await query.edit_message_text(
                f"✅ Событие '{event_name}' ({event_date}) теперь {new_status}!"
            )
        else:
            await query.edit_message_text("❌ Ошибка при изменении видимости события")

    except ValueError as e:
        print(f"DEBUG: ValueError in handle_share_choice: {e}")
        await query.edit_message_text("❌ Ошибка: неверный формат данных события")
    except Exception as e:
        print(f"DEBUG: Exception in handle_share_choice: {e}")
        await query.edit_message_text("❌ Произошла ошибка при обработке запроса")

    return ConversationHandler.END


async def show_public_events(update, context):
    """Показать публичные события других пользователей"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    public_events = await calendar.get_public_events(user.id)

    if not public_events:
        await update.message.reply_text(
            "📭 Пока нет публичных событий от других пользователей.\n"
            "Вы можете поделиться своими событиями с помощью команды /share"
        )
        return

    response = "🔓 Общие события других пользователей:\n\n"

    for event_name, event_date, username, first_name, last_name in public_events:
        user_display = f"@{username}" if username else f"{first_name} {last_name}".strip()
        response += f"📅 {event_name}\n"
        response += f"   📅 Дата: {event_date}\n"
        response += f"   👤 Автор: {user_display}\n\n"

    await update.message.reply_text(response)


async def show_my_events_with_public(update, context):
    """Показать события пользователя с указанием статуса публичности"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    events = await calendar.get_user_events(user.id)

    if not events:
        await update.message.reply_text("У вас нет запланированных событий.")
        return

    response = "📅 Ваши события:\n"
    for event_id, event_name, event_date, is_public in events:
        status = "🔓" if is_public else "🔒"
        response += f"{status} {event_name} ({event_date})\n"

    response += "\n🔓 - публичное событие\n🔒 - приватное событие"

    await update.message.reply_text(response)

async def handle_edit_choose(update, context):
    """Обработка выбора события для редактирования"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    try:
        event_num = int(update.message.text)
        events = context.user_data.get('events_to_edit', [])

        if 1 <= event_num <= len(events):
            # Сохраняем выбранное событие в контексте
            old_event_name, old_event_date = events[event_num - 1]
            context.user_data['editing_event'] = {
                'old_name': old_event_name,
                'old_date': old_event_date,
                'index': event_num - 1
            }

            await update.message.reply_text(
                f"Редактируем событие: {old_event_name} ({old_event_date})\n\n"
                "Введите новые данные в формате:\n"
                "Название ДД.ММ.ГГГГ\n"
                "Например: Новая встреча 20.12.2025"
            )
            return States.EDIT_EVENT_NEW_DATA
        else:
            await update.message.reply_text('Неверный номер события')
            return States.EDIT_EVENT_CHOOSE
    except ValueError:
        await update.message.reply_text('Введите номер события')
        return States.EDIT_EVENT_CHOOSE


async def handle_edit_new_data(update, context):
    """Обработка новых данных для события"""
    user = update.message.from_user
    calendar = context.bot_data['calendar']

    try:
        # Получаем старые данные
        editing_data = context.user_data.get('editing_event', {})
        old_event_name = editing_data.get('old_name')

        if not old_event_name:
            await update.message.reply_text('Ошибка: событие не найдено')
            return ConversationHandler.END

        # Парсим новые данные
        new_event_name, new_event_date = update.message.text.rsplit(' ', 1)
        datetime.datetime.strptime(new_event_date, '%d.%m.%Y')

        # Обновляем событие в базе
        if await calendar.update_event(
                user_id=user.id,
                old_event_name=old_event_name,
                new_event_name=new_event_name,
                new_event_date=new_event_date
        ):
            await update.message.reply_text(
                f'Событие успешно обновлено!\n'
            )
        else:
            await update.message.reply_text('Ошибка при обновлении события')

        # Очищаем временные данные
        if 'editing_event' in context.user_data:
            del context.user_data['editing_event']
        if 'events_to_edit' in context.user_data:
            del context.user_data['events_to_edit']

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            'Неверный формат. Введите данные в формате:\n'
            'Название Дата(ДД.ММ.ГГГГ)\n'
            'Например: Встреча 15.12.2024'
        )
        return States.EDIT_EVENT_NEW_DATA
    except Exception as e:
        await update.message.reply_text(f'Ошибка: {e}')
        return ConversationHandler.END

async def cancel(update, context):
    user = update.message.from_user
    calendar = context.bot_data['calendar']
    calendar.user_states[user.id] = None

    if 'editing_event' in context.user_data:
        del context.user_data['editing_event']
    if 'events_to_edit' in context.user_data:
        del context.user_data['events_to_edit']

    await update.message.reply_text("Операция отменена")
    return ConversationHandler.END

def main():
    import os
    import django

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'calendarbot.settings')
    django.setup()

    application = Application.builder().token(API_TOKEN).build()
    application.bot_data['calendar'] = Calendar()

    # ConversationHandler для публикации событий
    share_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('share', share_event)],
        states={
            States.SHARE_EVENT: [CallbackQueryHandler(handle_share_choice, pattern='^(share_|cancel_share)')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        allow_reentry=True
    )

    # ConversationHandler для создания встреч
    meeting_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('createmeeting', create_meeting_start)],
        states={
            States.MEETING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_title)],
            States.MEETING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_date)],
            States.MEETING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_time)],
            States.MEETING_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_duration)],
            States.MEETING_PARTICIPANTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_participants)],
            States.MEETING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, meeting_description)],
            States.CREATE_MEETING: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_meeting_creation)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        allow_reentry=True
    )

    # ConversationHandler для экспорта событий
    export_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('export', export_events)],
        states={
            States.EXPORT_EVENTS: [
                CallbackQueryHandler(handle_export_choice, pattern='^(export_json|export_csv|cancel_export)')],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        allow_reentry=True
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('addevent', add_event),
            CommandHandler('register', register),
            CommandHandler('events', show_events),
            CommandHandler('delevent', delete_event),
            CommandHandler('edit', edit_event),

        ],
        states={
            States.REGISTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
            States.ADD_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_event)],
            States.DELETE_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_event)],
            States.EDIT_EVENT_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_choose)],
            States.EDIT_EVENT_NEW_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_new_data)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(meeting_conv_handler)
    application.add_handler(share_conv_handler)
    application.add_handler(CommandHandler('events', show_my_events_with_public))
    application.add_handler(CommandHandler('publicevents', show_public_events))
    application.add_handler(CommandHandler('meetings', show_my_meetings))
    application.add_handler(CommandHandler('invitations', show_meeting_invitations))
    application.add_handler(CommandHandler('myid', show_my_id))
    application.add_handler(CallbackQueryHandler(handle_meeting_response, pattern='^(accept|decline)_'))
    application.add_handler(export_conv_handler)

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()