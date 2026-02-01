# calendar_bot_old.py
import os
import sys
from pathlib import Path

from django.db.models import Q

BASE_DIR = Path(__file__).resolve().parent.parent
django_path = BASE_DIR / 'django_admin'
sys.path.append(str(django_path))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'calendar_admin.settings')

import django

django.setup()

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
from secrets import API_TOKEN
import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging
import asyncio

# Импорты для работы с Django в async контексте
from django.utils import timezone
from django.db import DatabaseError, models

from calendar_app.models import (
    TelegramUser, CalendarEvent, BotStatistics,
    UserInteraction, EventChangeLog
)

from calendar_app.models import Meeting, MeetingParticipant, MeetingNotification

from calendar_app.notifications import (
    create_meeting_invitation,
    send_meeting_confirmation,
    send_meeting_declination,
    get_unread_notifications_count
)
import datetime as dt_module
from datetime import datetime, date, time, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
DATE, TITLE, DESCRIPTION, EVENT_ID, NEW_TITLE, NEW_DESCRIPTION, REGISTER = range(7)
CREATE_MEETING_DATE, CREATE_MEETING_TITLE, CREATE_MEETING_DESCRIPTION, \
CREATE_MEETING_START_TIME, CREATE_MEETING_END_TIME, CREATE_MEETING_PARTICIPANTS = range(6, 12)
PUBLISH_SELECT_EVENT, PUBLISH_CONFIRM = range(12, 14)
UNPUBLISH_SELECT_EVENT, UNPUBLISH_CONFIRM = range(14, 16)
VIEW_SHARED_EVENTS = range(16, 17)
EXPORT_SELECT_TYPE, EXPORT_SELECT_FORMAT, EXPORT_SELECT_DATE_RANGE = range(17, 20)

# константы для форматов
EXPORT_FORMATS = ['json', 'csv', 'ical']
EXPORT_TYPES = ['all', 'calendar', 'meetings']

# Состояния пользователя
class UserState(Enum):
    IDLE = "idle"
    CREATING_EVENT = "creating_event"
    UPDATING_EVENT = "updating_event"
    VIEWING_EVENTS = "viewing_events"


# Словарь для хранения состояний пользователей
user_states: Dict[int, UserState] = {}


def get_user_state(telegram_id: int) -> UserState:
    """Получить состояние пользователя"""
    return user_states.get(telegram_id, UserState.IDLE)


def set_user_state(telegram_id: int, state: UserState):
    """Установить состояние пользователя"""
    user_states[telegram_id] = state


# Синхронные функции для работы с Django ORM
def get_or_create_user_sync(telegram_id: int, **user_data) -> TelegramUser:
    """Синхронная функция для получения или создания пользователя"""
    # Очищаем данные от None значений
    cleaned_data = {}
    for key, value in user_data.items():
        if value is not None:
            cleaned_data[key] = value
        else:
            cleaned_data[key] = ""

    try:
        user, created = TelegramUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults=cleaned_data
        )

        # Если пользователь уже существует, обновляем информацию
        if not created:
            update_fields = []
            for field, value in cleaned_data.items():
                if value and hasattr(user, field) and getattr(user, field) != value:
                    setattr(user, field, value)
                    update_fields.append(field)

            if update_fields:
                user.save(update_fields=update_fields)

        # Обновляем last_seen при каждом обращении
        user.last_seen = timezone.now()
        user.save(update_fields=['last_seen'])

        # Обновляем статистику о новых пользователях
        if created:
            stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())
            stats.daily_new_users += 1
            stats.save()

        return user
    except Exception as e:
        logger.error(f"Ошибка в get_or_create_user_sync: {e}")
        raise


def create_calendar_event_sync(telegram_id: int, date_str: str, title: str, description: str = "") -> Tuple[
    bool, str, Optional[CalendarEvent]]:
    """Синхронная функция для создания события"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
    except TelegramUser.DoesNotExist:
        return False, "❌ Пользователь не найден. Используйте /start для регистрации.", None

    try:
        # Преобразуем строку даты в объект date
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        return False, "❌ Неверный формат даты. Используйте DD.MM.YYYY", None

    try:
        event = CalendarEvent.objects.create(
            user=user,
            date=date_obj,
            title=title,
            description=description if description else None
        )

        # Обновляем статистику
        stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())
        stats.daily_created_events += 1
        stats.save()

        # Логируем создание
        EventChangeLog.objects.create(
            event=event,
            user=user,
            action='create',
            new_data={
                'date': date_str,
                'title': title,
                'description': description
            }
        )

        return True, f"✅ Событие '{title}' на {date_str} создано (ID: {event.id})", event
    except Exception as e:
        logger.error(f"Ошибка при создании события: {e}")
        return False, f"❌ Ошибка при создании события: {str(e)}", None


def get_event_by_id_sync(telegram_id: int, event_id: int) -> Optional[CalendarEvent]:
    """Синхронная функция для получения события по ID"""
    try:
        event = CalendarEvent.objects.get(id=event_id, user__telegram_id=telegram_id)
        return event
    except CalendarEvent.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении события: {e}")
        return None


def update_calendar_event_sync(telegram_id: int, event_id: int, title: Optional[str] = None,
                               description: Optional[str] = None) -> Tuple[bool, str]:
    """Синхронная функция для обновления события"""
    try:
        event = CalendarEvent.objects.get(id=event_id, user__telegram_id=telegram_id)
        user = TelegramUser.objects.get(telegram_id=telegram_id)
    except (CalendarEvent.DoesNotExist, TelegramUser.DoesNotExist):
        return False, f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"

    try:
        # Сохраняем старые данные для лога
        old_data = {
            'title': event.title,
            'description': event.description,
            'date': event.date.strftime("%d.%m.%Y")
        }

        # Обновляем поля
        update_fields = []
        if title is not None:
            event.title = title
            update_fields.append('title')

        if description is not None:
            event.description = description if description else None
            update_fields.append('description')

        if not update_fields:
            return True, "ℹ️ Нечего обновлять"

        event.save(update_fields=update_fields)

        # Обновляем статистику
        stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())
        stats.daily_updated_events += 1
        stats.save()

        # Логируем изменение
        EventChangeLog.objects.create(
            event=event,
            user=user,
            action='update',
            old_data=old_data,
            new_data={
                'title': event.title,
                'description': event.description,
                'date': event.date.strftime("%d.%m.%Y")
            }
        )

        return True, f"✅ Событие ID {event_id} успешно обновлено"
    except Exception as e:
        logger.error(f"Ошибка при обновлении события: {e}")
        return False, f"❌ Ошибка при обновлении события: {str(e)}"


def delete_calendar_event_sync(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    """Синхронная функция для удаления события"""
    try:
        event = CalendarEvent.objects.get(id=event_id, user__telegram_id=telegram_id)
        user = TelegramUser.objects.get(telegram_id=telegram_id)
    except (CalendarEvent.DoesNotExist, TelegramUser.DoesNotExist):
        return False, f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"

    try:
        # Сохраняем данные для лога
        event_data = {
            'title': event.title,
            'date': event.date.strftime("%d.%m.%Y"),
            'description': event.description
        }

        # Удаляем событие
        event_id_copy = event.id
        event.delete()

        # Обновляем статистику
        stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())
        stats.daily_deleted_events += 1
        stats.save()

        # Логируем удаление
        EventChangeLog.objects.create(
            user=user,
            action='delete',
            old_data=event_data
        )

        return True, f"✅ Событие '{event_data['title']}' (ID: {event_id_copy}) удалено"
    except Exception as e:
        logger.error(f"Ошибка при удалении события: {e}")
        return False, f"❌ Ошибка при удалении события: {str(e)}"


def get_user_events_sync(telegram_id: int, sort_by_date: bool = True) -> List[CalendarEvent]:
    """Синхронная функция для получения событий пользователя"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        events = CalendarEvent.objects.filter(user=user)

        if sort_by_date:
            events = events.order_by('date', 'created_at')
        else:
            events = events.order_by('-created_at')

        return list(events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении событий пользователя: {e}")
        return []


def get_events_for_date_sync(telegram_id: int, date_str: str) -> List[CalendarEvent]:
    """Синхронная функция для получения событий на дату"""
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        return []

    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        events = CalendarEvent.objects.filter(user=user, date=date_obj).order_by('created_at')
        return list(events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении событий на дату: {e}")
        return []


def get_today_events_sync(telegram_id: int) -> List[CalendarEvent]:
    """Синхронная функция для получения событий на сегодня"""
    today = date.today()

    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        events = CalendarEvent.objects.filter(user=user, date=today).order_by('created_at')
        return list(events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении событий на сегодня: {e}")
        return []


def get_user_stats_sync(telegram_id: int) -> Dict[str, Any]:
    """Синхронная функция для получения статистики пользователя"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        today = date.today()

        stats = {
            'total_events': CalendarEvent.objects.filter(user=user).count(),
            'today_events': CalendarEvent.objects.filter(user=user, date=today).count(),
            'future_events': CalendarEvent.objects.filter(user=user, date__gt=today).count(),
            'past_events': CalendarEvent.objects.filter(user=user, date__lt=today).count(),
        }

        # Ближайшее будущее событие
        closest_event = CalendarEvent.objects.filter(
            user=user,
            date__gte=today
        ).order_by('date').first()

        if closest_event:
            stats['closest_event'] = {
                'title': closest_event.title,
                'date': closest_event.date,
                'id': closest_event.id
            }
        else:
            stats['closest_event'] = None

        return stats
    except TelegramUser.DoesNotExist:
        return {}
    except Exception as e:
        logger.error(f"Ошибка при получении статистики пользователя: {e}")
        return {}


def get_all_users_count_sync() -> int:
    """Синхронная функция для получения количества пользователей"""
    return TelegramUser.objects.count()


def log_user_interaction_sync(telegram_id: int, command: str, **kwargs):
    """Синхронная функция для логирования взаимодействий"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        interaction = UserInteraction.objects.create(
            user=user,
            command=command,
            parameters=kwargs
        )

        # Обновляем статистику команд
        stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())

        if command == '/start':
            stats.daily_start_commands += 1
        elif command == '/help':
            stats.daily_help_commands += 1
        elif command == '/list':
            stats.daily_list_commands += 1
        elif command == '/today':
            stats.daily_today_commands += 1
        elif command == '/stats':
            stats.daily_stats_commands += 1
        elif command == 'create_event':
            stats.daily_created_events += 1

        stats.save()
        return interaction
    except TelegramUser.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Ошибка при логировании взаимодействия: {e}")
        return None


def get_user_busy_slots_sync(telegram_id: int, date: date) -> List[Dict[str, Any]]:
    """Получить занятые временные интервалы пользователя на дату"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)

        # События календаря
        calendar_events = CalendarEvent.objects.filter(
            user=user,
            date=date
        ).values('title', 'description').annotate(
            start_time=models.Value(time(0, 0), output_field=models.TimeField()),
            end_time=models.Value(time(23, 59), output_field=models.TimeField())
        )

        # Подтвержденные встречи
        confirmed_meetings = Meeting.objects.filter(
            participants=user,
            date=date,
            status='confirmed'
        ).values('title', 'start_time', 'end_time')

        # Встречи, ожидающие подтверждения
        pending_meetings = Meeting.objects.filter(
            participants=user,
            date=date,
            status='pending'
        ).values('title', 'start_time', 'end_time')

        busy_slots = []

        for event in calendar_events:
            busy_slots.append({
                'type': 'calendar_event',
                'title': event['title'],
                'start': time(0, 0),
                'end': time(23, 59),
                'description': event['description']
            })

        for meeting in confirmed_meetings:
            busy_slots.append({
                'type': 'confirmed_meeting',
                'title': meeting['title'],
                'start': meeting['start_time'],
                'end': meeting['end_time']
            })

        for meeting in pending_meetings:
            busy_slots.append({
                'type': 'pending_meeting',
                'title': meeting['title'],
                'start': meeting['start_time'],
                'end': meeting['end_time']
            })

        return busy_slots

    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении занятых слотов: {e}")
        return []


def check_user_availability_sync(telegram_id: int, date: date,
                                 start_time: time, end_time: time) -> bool:
    """Проверить, свободен ли пользователь в указанное время"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)

        # Проверяем события календаря
        has_calendar_events = CalendarEvent.objects.filter(
            user=user,
            date=date
        ).exists()

        if has_calendar_events:
            return False

        # Проверяем пересечения с подтвержденными встречами
        overlapping_meetings = Meeting.objects.filter(
            participants=user,
            date=date,
            status='confirmed'
        ).filter(
            models.Q(
                start_time__lt=end_time,
                end_time__gt=start_time
            )
        ).exists()

        return not overlapping_meetings

    except TelegramUser.DoesNotExist:
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке доступности: {e}")
        return False


def create_meeting_sync(telegram_id: int, title: str, description: str,
                        date_str: str, start_time_str: str, end_time_str: str,
                        participant_ids: List[int]) -> Tuple[bool, str, Optional[Meeting]]:
    """Создать встречу"""
    try:
        organizer = TelegramUser.objects.get(telegram_id=telegram_id)

        # Парсим дату и время
        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        # Проверяем, что время окончания позже времени начала
        if end_time <= start_time:
            return False, "❌ Время окончания должно быть позже времени начала", None

        # Проверяем доступность организатора
        if not check_user_availability_sync(telegram_id, date_obj, start_time, end_time):
            return False, "❌ У вас уже есть планы на это время", None

        # Создаем встречу
        meeting = Meeting.objects.create(
            title=title,
            description=description,
            date=date_obj,
            start_time=start_time,
            end_time=end_time,
            organizer=organizer,
            status='pending'
        )

        # Добавляем организатора как участника
        MeetingParticipant.objects.create(
            meeting=meeting,
            participant=organizer,
            status='confirmed'
        )

        # Добавляем участников
        participants_added = []
        for participant_id in participant_ids:
            try:
                participant = TelegramUser.objects.get(telegram_id=participant_id)

                # Пропускаем, если это организатор
                if participant.telegram_id == telegram_id:
                    continue

                # Проверяем доступность участника
                if check_user_availability_sync(participant_id, date_obj, start_time, end_time):
                    MeetingParticipant.objects.create(
                        meeting=meeting,
                        participant=participant,
                        status='pending'
                    )
                    participants_added.append(participant)

                    # СОЗДАЕМ УВЕДОМЛЕНИЕ ДЛЯ УЧАСТНИКА
                    MeetingNotification.objects.create(
                        meeting=meeting,
                        user=participant,
                        notification_type='invitation',
                        message=f"Вас пригласили на встречу '{title}' {date_str} с {start_time_str} до {end_time_str}"
                    )

                    logger.info(f"Приглашение отправлено участнику {participant_id}")
                else:
                    # Добавляем с статусом declined
                    MeetingParticipant.objects.create(
                        meeting=meeting,
                        participant=participant,
                        status='declined'
                    )
                    logger.info(f"Участник {participant_id} занят в это время")

            except TelegramUser.DoesNotExist:
                logger.warning(f"Пользователь {participant_id} не найден")

        # Обновляем статистику
        stats, _ = BotStatistics.objects.get_or_create(date=timezone.now().date())
        stats.save()

        return True, f"✅ Встреча '{title}' создана. Приглашения отправлены {len(participants_added)} участникам.", meeting

    except Exception as e:
        logger.error(f"Ошибка при создании встречи: {e}")
        return False, f"❌ Ошибка при создании встречи: {str(e)}", None


def get_user_meetings_sync(telegram_id: int) -> List[Meeting]:
    """Получить встречи пользователя"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)

        # Встречи, где пользователь организатор или участник
        meetings = Meeting.objects.filter(
            models.Q(organizer=user) |
            models.Q(participants=user)
        ).distinct().select_related('organizer').order_by('date', 'start_time')

        return list(meetings)

    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении встреч: {e}")
        return []


def respond_to_meeting_invitation_sync(telegram_id: int, meeting_id: int,
                                       response: str) -> Tuple[bool, str]:
    """Ответить на приглашение на встречу"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        meeting = Meeting.objects.get(id=meeting_id)

        # Проверяем, приглашен ли пользователь
        try:
            participant = MeetingParticipant.objects.get(
                meeting=meeting,
                participant=user,
                status='pending'
            )
        except MeetingParticipant.DoesNotExist:
            return False, "❌ Вы не приглашены на эту встречу или уже ответили"

        # Обновляем статус
        if response.lower() in ['подтвердить', 'confirm', 'да', 'yes']:
            participant.status = 'confirmed'
            response_text = "подтвердил"
            notification_type = 'confirmation'
        else:
            participant.status = 'declined'
            response_text = "отклонил"
            notification_type = 'cancellation'

        participant.save()

        # Создаем уведомление для организатора
        MeetingNotification.objects.create(
            meeting=meeting,
            user=meeting.organizer,
            notification_type=notification_type,
            message=f"{user.first_name or user.username or 'Пользователь'} {response_text} ваше приглашение на встречу '{meeting.title}'"
        )

        # Создаем уведомление для участника
        MeetingNotification.objects.create(
            meeting=meeting,
            user=user,
            notification_type=notification_type,
            message=f"Вы {response_text} приглашение на встречу '{meeting.title}'"
        )

        return True, f"✅ Вы {response_text} приглашение на встречу '{meeting.title}'"

    except Meeting.DoesNotExist:
        return False, "❌ Встреча не найдена"
    except Exception as e:
        logger.error(f"Ошибка при ответе на приглашение: {e}")
        return False, f"❌ Ошибка: {str(e)}"


def get_user_events_with_privacy_sync(telegram_id: int, include_public: bool = True) -> List[CalendarEvent]:
    """Получить события пользователя с учетом приватности"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        events = CalendarEvent.objects.filter(user=user)

        # Если не включаем публичные, фильтруем только приватные
        if not include_public:
            events = events.filter(is_public=False)

        events = events.order_by('date', 'created_at')
        return list(events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении событий пользователя: {e}")
        return []


def get_public_events_sync(telegram_id: int) -> List[CalendarEvent]:
    """Получить публичные события других пользователей"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)

        # Получаем публичные события всех пользователей, кроме себя
        public_events = CalendarEvent.objects.filter(
            is_public=True
        ).exclude(
            user=user
        ).select_related(
            'user'
        ).order_by('date', 'created_at')

        return list(public_events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении публичных событий: {e}")
        return []


def get_public_events_by_user_sync(owner_id: int, viewer_id: int) -> List[CalendarEvent]:
    """Получить публичные события конкретного пользователя"""
    try:
        owner = TelegramUser.objects.get(telegram_id=owner_id)
        viewer = TelegramUser.objects.get(telegram_id=viewer_id)

        # Получаем публичные события владельца
        public_events = CalendarEvent.objects.filter(
            user=owner,
            is_public=True
        ).order_by('date', 'created_at')

        return list(public_events)
    except TelegramUser.DoesNotExist:
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении публичных событий пользователя: {e}")
        return []


def publish_event_sync(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    """Сделать событие публичным"""
    try:
        event = CalendarEvent.objects.get(id=event_id, user__telegram_id=telegram_id)

        if event.is_public:
            return False, f"❌ Событие '{event.title}' уже является публичным"

        event.is_public = True
        event.published_at = timezone.now()
        event.save()

        # Логируем изменение
        EventChangeLog.objects.create(
            event=event,
            user=event.user,
            action='publish',
            new_data={
                'title': event.title,
                'date': event.date.strftime("%d.%m.%Y"),
                'published_at': event.published_at.strftime("%d.%m.%Y %H:%M")
            }
        )

        return True, f"✅ Событие '{event.title}' теперь публичное!"

    except CalendarEvent.DoesNotExist:
        return False, f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"
    except Exception as e:
        logger.error(f"Ошибка при публикации события: {e}")
        return False, f"❌ Ошибка при публикации: {str(e)}"


def unpublish_event_sync(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    """Сделать событие приватным"""
    try:
        event = CalendarEvent.objects.get(id=event_id, user__telegram_id=telegram_id)

        if not event.is_public:
            return False, f"❌ Событие '{event.title}' уже является приватным"

        event.is_public = False
        event.save()

        # Логируем изменение
        EventChangeLog.objects.create(
            event=event,
            user=event.user,
            action='unpublish',
            old_data={
                'title': event.title,
                'date': event.date.strftime("%d.%m.%Y"),
                'published_at': event.published_at.strftime("%d.%m.%Y %H:%M") if event.published_at else None
            }
        )

        return True, f"✅ Событие '{event.title}' теперь приватное!"

    except CalendarEvent.DoesNotExist:
        return False, f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа"
    except Exception as e:
        logger.error(f"Ошибка при снятии публикации события: {e}")
        return False, f"❌ Ошибка при снятии публикации: {str(e)}"


# экспорт
def generate_export_url(telegram_id: int, format_type: str, filters: Dict[str, Any] = None) -> str:
    """Генерация URL для экспорта"""
    base_url = "http://localhost:8000"  # В реальном приложении нужно использовать правильный домен
    url = f"{base_url}/api/export/{telegram_id}/{format_type}/"

    if filters:
        params = []
        if filters.get('date_from'):
            params.append(f"from={filters['date_from']}")
        if filters.get('date_to'):
            params.append(f"to={filters['date_to']}")
        if filters.get('event_type') and filters['event_type'] != 'all':
            params.append(f"type={filters['event_type']}")

        if params:
            url += "?" + "&".join(params)

    return url


def get_public_event_stats_sync(telegram_id: int) -> Dict[str, Any]:
    """Получить статистику по публичным событиям"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)

        stats = {
            'total_public': CalendarEvent.objects.filter(user=user, is_public=True).count(),
            'total_private': CalendarEvent.objects.filter(user=user, is_public=False).count(),
            'others_public': CalendarEvent.objects.filter(is_public=True).exclude(user=user).count(),
            'recently_published': CalendarEvent.objects.filter(
                user=user,
                is_public=True,
                published_at__gte=timezone.now() - timedelta(days=7)
            ).count()
        }

        return stats
    except TelegramUser.DoesNotExist:
        return {}
    except Exception as e:
        logger.error(f"Ошибка при получении статистики публичных событий: {e}")
        return {}


# Асинхронные обертки
async def get_user_busy_slots(telegram_id: int, date_obj: date) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(get_user_busy_slots_sync, telegram_id, date_obj)


async def check_user_availability(telegram_id: int, date_obj: date,
                                  start_time: time, end_time: time) -> bool:
    return await asyncio.to_thread(check_user_availability_sync, telegram_id, date_obj, start_time, end_time)


async def create_meeting(telegram_id: int, title: str, description: str,
                         date_str: str, start_time_str: str, end_time_str: str,
                         participant_ids: List[int]) -> Tuple[bool, str, Optional[Meeting]]:
    return await asyncio.to_thread(create_meeting_sync, telegram_id, title, description,
                                   date_str, start_time_str, end_time_str, participant_ids)


async def get_user_meetings(telegram_id: int) -> List[Meeting]:
    return await asyncio.to_thread(get_user_meetings_sync, telegram_id)

async def send_telegram_notification_to_user(context: ContextTypes.DEFAULT_TYPE,
                                             telegram_id: int,
                                             message: str) -> bool:
    """Отправить уведомление пользователю через Telegram"""
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=message,
            parse_mode='Markdown'
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения {telegram_id}: {e}")
        return False


async def respond_to_meeting_invitation(telegram_id: int, meeting_id: int, response: str) -> Tuple[bool, str]:
    return await asyncio.to_thread(respond_to_meeting_invitation_sync, telegram_id, meeting_id, response)

# Асинхронные обертки с использованием asyncio.to_thread
async def get_or_create_user(telegram_id: int, **user_data) -> TelegramUser:
    """Асинхронная обертка для получения или создания пользователя"""
    return await asyncio.to_thread(get_or_create_user_sync, telegram_id, **user_data)


async def create_calendar_event(telegram_id: int, date_str: str, title: str, description: str = "") -> Tuple[
    bool, str, Optional[CalendarEvent]]:
    """Асинхронная обертка для создания события"""
    return await asyncio.to_thread(create_calendar_event_sync, telegram_id, date_str, title, description)


async def get_event_by_id(telegram_id: int, event_id: int) -> Optional[CalendarEvent]:
    """Асинхронная обертка для получения события по ID"""
    return await asyncio.to_thread(get_event_by_id_sync, telegram_id, event_id)


async def update_calendar_event(telegram_id: int, event_id: int, title: Optional[str] = None,
                                description: Optional[str] = None) -> Tuple[bool, str]:
    """Асинхронная обертка для обновления события"""
    return await asyncio.to_thread(update_calendar_event_sync, telegram_id, event_id, title, description)


async def delete_calendar_event(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    """Асинхронная обертка для удаления события"""
    return await asyncio.to_thread(delete_calendar_event_sync, telegram_id, event_id)


async def get_user_events(telegram_id: int, sort_by_date: bool = True) -> List[CalendarEvent]:
    """Асинхронная обертка для получения событий пользователя"""
    return await asyncio.to_thread(get_user_events_sync, telegram_id, sort_by_date)


async def get_events_for_date(telegram_id: int, date_str: str) -> List[CalendarEvent]:
    """Асинхронная обертка для получения событий на дату"""
    return await asyncio.to_thread(get_events_for_date_sync, telegram_id, date_str)


async def get_today_events(telegram_id: int) -> List[CalendarEvent]:
    """Асинхронная обертка для получения событий на сегодня"""
    return await asyncio.to_thread(get_today_events_sync, telegram_id)


async def get_user_stats(telegram_id: int) -> Dict[str, Any]:
    """Асинхронная обертка для получения статистики пользователя"""
    return await asyncio.to_thread(get_user_stats_sync, telegram_id)


async def get_all_users_count() -> int:
    """Асинхронная обертка для получения количества пользователей"""
    return await asyncio.to_thread(get_all_users_count_sync)


async def log_user_interaction(telegram_id: int, command: str, **kwargs):
    """Асинхронная обертка для логирования взаимодействий"""
    return await asyncio.to_thread(log_user_interaction_sync, telegram_id, command, **kwargs)

async def get_user_events_with_privacy(telegram_id: int, include_public: bool = True) -> List[CalendarEvent]:
    return await asyncio.to_thread(get_user_events_with_privacy_sync, telegram_id, include_public)

async def get_public_events(telegram_id: int) -> List[CalendarEvent]:
    return await asyncio.to_thread(get_public_events_sync, telegram_id)

async def get_public_events_by_user(owner_id: int, viewer_id: int) -> List[CalendarEvent]:
    return await asyncio.to_thread(get_public_events_by_user_sync, owner_id, viewer_id)

async def publish_event(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    return await asyncio.to_thread(publish_event_sync, telegram_id, event_id)

async def unpublish_event(telegram_id: int, event_id: int) -> Tuple[bool, str]:
    return await asyncio.to_thread(unpublish_event_sync, telegram_id, event_id)

async def get_public_event_stats(telegram_id: int) -> Dict[str, Any]:
    return await asyncio.to_thread(get_public_event_stats_sync, telegram_id)


# Обработчики команд
async def ensure_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка и автоматическая регистрация пользователя"""
    user = update.effective_user
    telegram_id = user.id

    try:
        user_obj = await get_or_create_user(
            telegram_id=telegram_id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            language_code=user.language_code or ""
        )

        # Сохраняем информацию о пользователе в контексте
        context.user_data['user_obj'] = user_obj
        return True
    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя {telegram_id}: {e}")
        await update.message.reply_text("❌ Ошибка регистрации. Попробуйте снова.")
        return False


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user

    # Логируем взаимодействие
    await log_user_interaction(user.id, '/start')

    total_users = await get_all_users_count()

    welcome_text = f"""
    👋 Привет, {user.first_name}! Я многопользовательский бот-календарь.

    📊 Статистика системы:
    • Всего пользователей: {total_users}

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

    📤 Экспорт событий:
    /export - экспортировать события (выбор формата и параметров)
    /export_quick - быстрый экспорт всех событий в JSON

    🔓 Публичные события:
    /share - сделать событие публичным
    /unshare - сделать публичное событие приватным
    /shared - просмотреть публичные события других пользователей
    /shared_by <ID> - просмотреть публичные события конкретного пользователя
    /share_stats - статистика публичных событий

    👤 Учетная запись:
    /start - регистрация и начало работы
    /profile - информация о вашем профиле
    /my_id - узнать свой ID для приглашений на встречи
    /notifications - мои уведомления

    👥 Встречи:
    /meetings - показать все мои встречи
    /meeting <ID> - показать детали встречи
    /create_meeting - создать новую встречу
    /invitations - показать приглашения на встречи
    /check_availability <ID> <дата> <время начала> [время окончания] - проверить доступность

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

    💡 Как экспортировать события:
    1. Используйте /export для выбора параметров
    2. Выберите формат (JSON, CSV, iCal)
    3. Получите ссылку для скачивания
    4. Откройте ссылку в браузере
    """
    await update.message.reply_text(help_text)
    await ensure_registered(update, context)

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /profile"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user

    try:
        # Получаем пользователя через асинхронную обертку
        async def get_user_profile():
            user_obj = TelegramUser.objects.get(telegram_id=user.id)
            stats = get_user_stats_sync(user.id)
            return user_obj, stats

        user_obj, stats = await asyncio.to_thread(
            lambda: (
                TelegramUser.objects.get(telegram_id=user.id),
                get_user_stats_sync(user.id)
            )
        )

        profile_text = f"""
        👤 Ваш профиль:

        📝 Основная информация:
        • ID: {user_obj.telegram_id}
        • Имя: {user_obj.first_name or 'Не указано'}
        • Фамилия: {user_obj.last_name or 'Не указано'}
        • Username: @{user_obj.username or 'Не указано'}
        • Язык: {user_obj.language_code or 'Не указано'}

        📅 Статистика событий:
        • Всего событий: {stats.get('total_events', 0)}
        • Сегодня: {stats.get('today_events', 0)}
        • Будущих: {stats.get('future_events', 0)}
        • Прошедших: {stats.get('past_events', 0)}

        ⏰ Учетная запись:
        • Зарегистрирован: {user_obj.registered_at.strftime('%d.%m.%Y %H:%M')}
        • Последний визит: {user_obj.last_seen.strftime('%d.%m.%Y %H:%M')}
        """

        await update.message.reply_text(profile_text)
    except TelegramUser.DoesNotExist:
        await update.message.reply_text("❌ Пользователь не найден. Используйте /start для регистрации.")
    except Exception as e:
        logger.error(f"Ошибка в profile_handler: {e}")
        await update.message.reply_text("❌ Ошибка при получении профиля.")


async def create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс создания события"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user

    # Логируем взаимодействие
    await log_user_interaction(user.id, '/create')

    set_user_state(user.id, UserState.CREATING_EVENT)
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

    # Создаем событие
    user_id = update.effective_user.id

    success, result, _ = await create_calendar_event(
        telegram_id=user_id,
        date_str=context.user_data['date'],
        title=context.user_data['title'],
        description=context.user_data.get('description', '')
    )

    # Логируем взаимодействие
    if success:
        await log_user_interaction(user_id, 'create_event')

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
    event = await get_event_by_id(user_id, event_id)

    if not event:
        await update.message.reply_text(f"❌ Событие с ID {event_id} не найдено или у вас нет к нему доступа")
        return

    # Форматируем информацию о событии
    event_text = f"""
    📅 Событие ID: {event.id}
    Дата: {event.date.strftime('%d.%m.%Y')}
    Название: {event.title}
    Описание: {event.description or 'Нет описания'}
    Создано: {event.created_at.strftime('%d.%m.%Y %H:%M')}
    Обновлено: {event.updated_at.strftime('%d.%m.%Y %H:%M')}

    Статус: {"🔴 Прошедшее" if event.date < date.today() else "🟢 Сегодня" if event.date == date.today() else "🔵 Будущее"}
    """

    await update.message.reply_text(event_text)


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
    success, result = await delete_calendar_event(user_id, event_id)

    # Логируем взаимодействие
    if success:
        await log_user_interaction(user_id, 'delete_event')

    await update.message.reply_text(result)


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /list"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    events = await get_user_events(user_id, sort_by_date=True)

    if not events:
        await update.message.reply_text("📭 В вашем календаре пока нет событий")
        return

    result = "📅 Все ваши события:\n\n"

    # Разделяем публичные и приватные
    public_events = [e for e in events if e.is_public]
    private_events = [e for e in events if not e.is_public]

    if public_events:
        result += "🔓 Публичные события:\n"
        for event in public_events:
            date_str = event.date.strftime("%d.%m.%Y")
            result += f"   📢 ID: {event.id} | {date_str} - {event.title}\n"
            if event.description:
                desc = event.description[:50]
                if len(event.description) > 50:
                    desc += "..."
                result += f"      Описание: {desc}\n"
        result += "\n"

    if private_events:
        result += "🔒 Приватные события:\n"
        for event in private_events:
            date_str = event.date.strftime("%d.%m.%Y")
            today = date.today()
            status = "🔴" if event.date < today else "🟢" if event.date == today else "🔵"
            result += f"   {status} ID: {event.id} | {date_str} - {event.title}\n"
            if event.description:
                desc = event.description[:50]
                if len(event.description) > 50:
                    desc += "..."
                result += f"      Описание: {desc}\n"

    result += f"\n📊 Всего событий: {len(events)}"
    if public_events:
        result += f" (публичных: {len(public_events)})"

    # Добавляем подсказку
    result += "\n\n💡 Используйте /share чтобы сделать событие публичным"

    await update.message.reply_text(result)


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /today"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    events = await get_today_events(user_id)

    if not events:
        today = date.today().strftime("%d.%m.%Y")
        await update.message.reply_text(f"📭 На сегодня ({today}) нет запланированных событий.")
        return

    result = f"📅 Ваши события на сегодня ({date.today().strftime('%d.%m.%Y')}):\n\n"
    for event in events:
        result += f"🟢 ID: {event.id} - {event.title}\n"
        if event.description:
            desc = event.description[:100]
            if len(event.description) > 100:
                desc += "..."
            result += f"   {desc}\n"
        result += "─" * 30 + "\n"

    result += f"\n📊 Всего на сегодня: {len(events)} событий"

    await update.message.reply_text(result)


async def events_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /events"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите дату. Пример: /events 25.12.2024")
        return

    date_input = context.args[0]
    user_id = update.effective_user.id
    events = await get_events_for_date(user_id, date_input)

    if not events:
        await update.message.reply_text(f"📭 На {date_input} у вас нет запланированных событий.")
        return

    result = f"📅 Ваши события на {date_input}:\n\n"
    for event in events:
        result += f"📌 ID: {event.id} - {event.title}\n"
        if event.description:
            desc = event.description[:100]
            if len(event.description) > 100:
                desc += "..."
            result += f"   {desc}\n"
        result += "─" * 30 + "\n"

    result += f"\n📊 Всего на {date_input}: {len(events)} событий"

    await update.message.reply_text(result)


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stats"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)

    if not stats:
        await update.message.reply_text("❌ Не удалось получить статистику.")
        return

    result = "📊 Статистика ваших событий:\n\n"
    result += f"Всего событий: {stats.get('total_events', 0)}\n"
    result += f"Событий сегодня: {stats.get('today_events', 0)}\n"
    result += f"Будущих событий: {stats.get('future_events', 0)}\n"
    result += f"Прошедших событий: {stats.get('past_events', 0)}\n\n"

    closest_event = stats.get('closest_event')
    if closest_event:
        closest_date = closest_event['date'].strftime("%d.%m.%Y")
        result += f"Ближайшее событие: {closest_event['title']}\n"
        result += f"Дата: {closest_date}\n"
        result += f"ID события: {closest_event['id']}"
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
        success, result = await update_calendar_event(user_id, event_id, new_title, new_description)

        # Логируем взаимодействие
        if success:
            await log_user_interaction(user_id, 'update_event')

        await update.message.reply_text(result)
    else:
        set_user_state(user_id, UserState.UPDATING_EVENT)

        # Получаем текущее событие
        event = await get_event_by_id(user_id, event_id)

        if not event:
            await update.message.reply_text(f"❌ Событие с ID {event_id} не найдено.")
            set_user_state(user_id, UserState.IDLE)
            return ConversationHandler.END

        event_text = f"""
        📅 Текущее событие ID: {event.id}
        Дата: {event.date.strftime('%d.%m.%Y')}
        Текущее название: {event.title}
        Текущее описание: {event.description or 'Нет описания'}
        """

        await update.message.reply_text(
            f"{event_text}\n\n"
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

    # Обновляем событие
    user_id = update.effective_user.id
    event_id = context.user_data['update_event_id']

    success, result = await update_calendar_event(
        user_id,
        event_id,
        context.user_data.get('new_title'),
        context.user_data.get('new_description')
    )

    # Логируем взаимодействие
    if success:
        await log_user_interaction(user_id, 'update_event')

    set_user_state(user_id, UserState.IDLE)
    await update.message.reply_text(result)
    return ConversationHandler.END


async def meetings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /meetings"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    meetings = await get_user_meetings(user_id)

    if not meetings:
        await update.message.reply_text("📭 У вас пока нет встреч")
        return

    result = "📅 Ваши встречи:\n\n"

    for meeting in meetings:
        date_str = meeting.date.strftime("%d.%m.%Y")
        time_str = f"{meeting.start_time.strftime('%H:%M')} - {meeting.end_time.strftime('%H:%M')}"

        # Определяем иконку статуса
        if meeting.status == 'confirmed':
            status_icon = "🟢"
        elif meeting.status == 'pending':
            status_icon = "🟡"
        elif meeting.status == 'cancelled':
            status_icon = "🔴"
        else:
            status_icon = "⚪"

        # Определяем тип участия
        if meeting.organizer.telegram_id == user_id:
            role = "👑 Организатор"
        else:
            role = "👤 Участник"

        result += f"{status_icon} {date_str} {time_str}\n"
        result += f"📌 {meeting.title}\n"
        result += f"👥 {role} | Статус: {meeting.get_status_display()}\n"
        result += f"ID: {meeting.id}\n"
        result += "─" * 40 + "\n"

    result += f"\n📊 Всего встреч: {len(meetings)}"

    await update.message.reply_text(result)


# Обработчик команды /share - начать публикацию события
async def share_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс публикации события"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    await log_user_interaction(user.id, '/share')

    # Получаем приватные события пользователя
    private_events = await get_user_events_with_privacy(user.id, include_public=False)

    if not private_events:
        await update.message.reply_text(
            "📭 У вас нет приватных событий для публикации.\n"
            "Сначала создайте события с помощью /create"
        )
        return ConversationHandler.END

    # Формируем список событий для выбора
    events_text = "📋 Ваши приватные события:\n\n"
    for i, event in enumerate(private_events, 1):
        date_str = event.date.strftime("%d.%m.%Y")
        events_text += f"{i}. ID: {event.id} | {date_str} - {event.title}\n"
        if event.description:
            desc = event.description[:50] + "..." if len(event.description) > 50 else event.description
            events_text += f"   Описание: {desc}\n"
        events_text += "─" * 30 + "\n"

    events_text += (
        "\nВведите ID события, которое хотите сделать публичным:\n"
        "Или /cancel для отмены"
    )

    context.user_data['private_events'] = private_events
    set_user_state(user.id, UserState.CREATING_EVENT)

    await update.message.reply_text(events_text)
    return PUBLISH_SELECT_EVENT


# Обработчик выбора события для публикации
async def publish_select_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора события для публикации"""
    try:
        event_id = int(update.message.text)

        # Проверяем, что событие есть в списке приватных
        private_events = context.user_data.get('private_events', [])
        event = next((e for e in private_events if e.id == event_id), None)

        if not event:
            await update.message.reply_text(
                "❌ Неверный ID события. Пожалуйста, выберите ID из списка выше."
            )
            return PUBLISH_SELECT_EVENT

        # Сохраняем выбранное событие
        context.user_data['publish_event_id'] = event_id
        context.user_data['publish_event'] = event

        # Запрашиваем подтверждение
        confirm_text = (
            f"📢 Вы хотите сделать публичным событие:\n\n"
            f"📅 Дата: {event.date.strftime('%d.%m.%Y')}\n"
            f"📌 Название: {event.title}\n"
            f"📝 Описание: {event.description or 'Нет описания'}\n\n"
            f"После публикации это событие смогут увидеть другие пользователи.\n\n"
            f"Подтвердите публикацию (да/нет):"
        )

        await update.message.reply_text(confirm_text)
        return PUBLISH_CONFIRM

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите числовой ID события.")
        return PUBLISH_SELECT_EVENT


# Обработчик подтверждения публикации
async def publish_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения публикации"""
    response = update.message.text.lower()

    if response in ['да', 'yes', 'y', 'д', 'ок', 'ok']:
        user_id = update.effective_user.id
        event_id = context.user_data['publish_event_id']

        success, result = await publish_event(user_id, event_id)

        set_user_state(user_id, UserState.IDLE)
        await update.message.reply_text(result)

        # Отправляем дополнительную информацию
        if success:
            stats = await get_public_event_stats(user_id)
            info_text = (
                f"\n📊 Ваша статистика публичных событий:\n"
                f"• Публичных: {stats.get('total_public', 0)}\n"
                f"• Приватных: {stats.get('total_private', 0)}\n"
                f"• Опубликовано за неделю: {stats.get('recently_published', 0)}"
            )
            await update.message.reply_text(info_text)

        return ConversationHandler.END
    elif response in ['нет', 'no', 'n', 'н', 'отмена']:
        set_user_state(update.effective_user.id, UserState.IDLE)
        await update.message.reply_text("❌ Публикация отменена.")
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Пожалуйста, ответьте 'да' или 'нет'.\n"
            "Подтвердите публикацию события (да/нет):"
        )
        return PUBLISH_CONFIRM


# Обработчик команды /unshare - снять публикацию
async def unshare_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс снятия публикации события"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    await log_user_interaction(user.id, '/unshare')

    # Получаем публичные события пользователя
    public_events = await get_user_events_with_privacy(user.id)
    public_events = [e for e in public_events if e.is_public]

    if not public_events:
        await update.message.reply_text(
            "📭 У вас нет публичных событий.\n"
            "Чтобы сделать событие публичным, используйте /share"
        )
        return ConversationHandler.END

    # Формируем список публичных событий
    events_text = "📋 Ваши публичные события:\n\n"
    for i, event in enumerate(public_events, 1):
        date_str = event.date.strftime("%d.%m.%Y")
        published_date = event.published_at.strftime("%d.%m.%Y %H:%M") if event.published_at else "Неизвестно"
        events_text += f"{i}. ID: {event.id} | {date_str} - {event.title}\n"
        events_text += f"   Опубликовано: {published_date}\n"
        events_text += "─" * 30 + "\n"

    events_text += (
        "\nВведите ID события, которое хотите сделать приватным:\n"
        "Или /cancel для отмены"
    )

    context.user_data['public_events'] = public_events
    set_user_state(user.id, UserState.CREATING_EVENT)

    await update.message.reply_text(events_text)
    return UNPUBLISH_SELECT_EVENT


# Обработчик выбора события для снятия публикации
async def unpublish_select_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора события для снятия публикации"""
    try:
        event_id = int(update.message.text)

        # Проверяем, что событие есть в списке публичных
        public_events = context.user_data.get('public_events', [])
        event = next((e for e in public_events if e.id == event_id), None)

        if not event:
            await update.message.reply_text(
                "❌ Неверный ID события. Пожалуйста, выберите ID из списка выше."
            )
            return UNPUBLISH_SELECT_EVENT

        # Сохраняем выбранное событие
        context.user_data['unpublish_event_id'] = event_id
        context.user_data['unpublish_event'] = event

        # Запрашиваем подтверждение
        confirm_text = (
            f"🔒 Вы хотите сделать приватным событие:\n\n"
            f"📅 Дата: {event.date.strftime('%d.%m.%Y')}\n"
            f"📌 Название: {event.title}\n"
            f"📝 Описание: {event.description or 'Нет описания'}\n"
            f"📅 Опубликовано: {event.published_at.strftime('%d.%m.%Y %H:%M') if event.published_at else 'Неизвестно'}\n\n"
            f"После этого другие пользователи не смогут видеть это событие.\n\n"
            f"Подтвердите снятие публикации (да/нет):"
        )

        await update.message.reply_text(confirm_text)
        return UNPUBLISH_CONFIRM

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите числовой ID события.")
        return UNPUBLISH_SELECT_EVENT


# Обработчик подтверждения снятия публикации
async def unpublish_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения снятия публикации"""
    response = update.message.text.lower()

    if response in ['да', 'yes', 'y', 'д', 'ок', 'ok']:
        user_id = update.effective_user.id
        event_id = context.user_data['unpublish_event_id']

        success, result = await unpublish_event(user_id, event_id)

        set_user_state(user_id, UserState.IDLE)
        await update.message.reply_text(result)

        # Отправляем статистику
        if success:
            stats = await get_public_event_stats(user_id)
            info_text = (
                f"\n📊 Ваша статистика публичных событий:\n"
                f"• Публичных: {stats.get('total_public', 0)}\n"
                f"• Приватных: {stats.get('total_private', 0)}"
            )
            await update.message.reply_text(info_text)

        return ConversationHandler.END
    elif response in ['нет', 'no', 'n', 'н', 'отмена']:
        set_user_state(update.effective_user.id, UserState.IDLE)
        await update.message.reply_text("✅ Публикация сохранена.")
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Пожалуйста, ответьте 'да' или 'нет'.\n"
            "Подтвердите снятие публикации события (да/нет):"
        )
        return UNPUBLISH_CONFIRM


# Обработчик команды /shared - просмотр публичных событий
async def shared_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать публичные события других пользователей"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    await log_user_interaction(user.id, '/shared')

    # Получаем публичные события
    public_events = await get_public_events(user.id)

    if not public_events:
        await update.message.reply_text(
            "📭 Пока нет публичных событий от других пользователей.\n"
            "Вы можете поделиться своими событиями с помощью /share"
        )
        return

    # Группируем события по пользователям
    events_by_user = {}
    for event in public_events:
        user_key = f"{event.user.first_name or event.user.username or f'Пользователь {event.user.telegram_id}'}"
        if user_key not in events_by_user:
            events_by_user[user_key] = []
        events_by_user[user_key].append(event)

    # Формируем ответ
    result = "👥 Общие события от других пользователей:\n\n"

    for user_name, events in events_by_user.items():
        result += f"👤 {user_name}:\n"

        for event in events:
            date_str = event.date.strftime("%d.%m.%Y")
            published_date = event.published_at.strftime("%d.%m.%Y") if event.published_at else ""

            result += f"  📅 {date_str} - {event.title}\n"
            if event.description:
                desc = event.description[:50] + "..." if len(event.description) > 50 else event.description
                result += f"     {desc}\n"
            if published_date:
                result += f"     📅 Опубликовано: {published_date}\n"
            result += "  " + "─" * 30 + "\n"

        result += "\n"

    result += f"📊 Всего публичных событий: {len(public_events)} от {len(events_by_user)} пользователей"

    # Добавляем статистику
    stats = await get_public_event_stats(user.id)
    result += f"\n\n📈 Ваша статистика:\n"
    result += f"• Ваших публичных событий: {stats.get('total_public', 0)}\n"
    result += f"• Всего публичных событий в системе: {stats.get('others_public', 0) + stats.get('total_public', 0)}"

    await update.message.reply_text(result)


# Обработчик команды /shared_by
async def shared_by_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать публичные события конкретного пользователя"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Укажите ID пользователя.\n"
            "Пример: /shared_by 123456789\n\n"
            "Чтобы узнать ID пользователя, попросите его отправить команду /my_id"
        )
        return

    try:
        owner_id = int(context.args[0])
        viewer_id = update.effective_user.id

        # Проверяем, не пытается ли пользователь посмотреть свои же события
        if owner_id == viewer_id:
            await update.message.reply_text(
                "ℹ️ Чтобы посмотреть свои публичные события, используйте команду /list"
            )
            return

        # Получаем публичные события пользователя
        public_events = await get_public_events_by_user(owner_id, viewer_id)

        if not public_events:
            # Проверяем, существует ли пользователь
            try:
                def check_user_exists():
                    return TelegramUser.objects.filter(telegram_id=owner_id).exists()

                user_exists = await asyncio.to_thread(check_user_exists)

                if user_exists:
                    await update.message.reply_text(
                        f"📭 У пользователя {owner_id} нет публичных событий."
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Пользователь с ID {owner_id} не найден."
                    )
            except Exception as e:
                logger.error(f"Ошибка при проверке пользователя: {e}")
                await update.message.reply_text(
                    f"📭 У пользователя {owner_id} нет публичных событий или он не найден."
                )
            return

        # Получаем информацию о владельце
        def get_owner_info():
            owner = TelegramUser.objects.get(telegram_id=owner_id)
            return owner

        owner = await asyncio.to_thread(get_owner_info)
        owner_name = owner.first_name or owner.username or f"Пользователь {owner_id}"

        # Формируем ответ
        result = f"👤 Публичные события пользователя {owner_name}:\n\n"

        for event in public_events:
            date_str = event.date.strftime("%d.%m.%Y")
            published_date = event.published_at.strftime("%d.%m.%Y %H:%M") if event.published_at else ""

            result += f"📅 {date_str} - {event.title}\n"
            if event.description:
                result += f"📝 {event.description}\n"
            if published_date:
                result += f"📅 Опубликовано: {published_date}\n"
            result += "─" * 40 + "\n"

        result += f"\n📊 Всего публичных событий: {len(public_events)}"

        await update.message.reply_text(result)

    except ValueError:
        await update.message.reply_text("❌ ID пользователя должен быть числом.")
    except Exception as e:
        logger.error(f"Ошибка при получении публичных событий пользователя: {e}")
        await update.message.reply_text("❌ Ошибка при получении публичных событий.")


# Обработчик команды /share_stats - статистика публичных событий
async def share_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику публичных событий"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    stats = await get_public_event_stats(user_id)

    if not stats:
        await update.message.reply_text("❌ Не удалось получить статистику.")
        return

    result = "📊 Статистика публичных событий:\n\n"

    result += "👤 Ваши события:\n"
    result += f"• Публичных: {stats.get('total_public', 0)}\n"
    result += f"• Приватных: {stats.get('total_private', 0)}\n"
    result += f"• Опубликовано за неделю: {stats.get('recently_published', 0)}\n\n"

    result += "👥 В системе:\n"
    result += f"• Всего публичных событий: {stats.get('others_public', 0) + stats.get('total_public', 0)}"

    # Получаем топ пользователей по публичным событиям
    def get_top_users():
        from django.db.models import Count
        top_users = TelegramUser.objects.filter(
            events__is_public=True
        ).annotate(
            public_count=Count('events')
        ).order_by('-public_count')[:5]

        return [
            {
                'name': user.first_name or user.username or f"User{user.telegram_id}",
                'count': user.public_count,
                'id': user.telegram_id
            }
            for user in top_users
        ]

    try:
        top_users = await asyncio.to_thread(get_top_users)
        if top_users:
            result += "\n\n🏆 Топ пользователей по публичным событиям:\n"
            for i, user in enumerate(top_users, 1):
                result += f"{i}. {user['name']}: {user['count']} событий (ID: {user['id']})\n"
    except Exception as e:
        logger.error(f"Ошибка при получении топ пользователей: {e}")

    await update.message.reply_text(result)




async def create_meeting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс создания встречи"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user

    # Логируем взаимодействие
    await log_user_interaction(user.id, '/create_meeting')

    set_user_state(user.id, UserState.CREATING_EVENT)
    await update.message.reply_text(
        "👥 Создание новой встречи.\n"
        "Введите дату встречи в формате ДД.ММ.ГГГГ (например, 25.12.2024):\n"
        "Или /cancel для отмены"
    )
    return CREATE_MEETING_DATE


# Обработчик команды /export - начать экспорт
async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс экспорта событий"""
    if not await ensure_registered(update, context):
        return

    user = update.effective_user
    await log_user_interaction(user.id, '/export')

    # Проверяем, есть ли события у пользователя
    events_count = await get_user_events_count(user.id)
    meetings_count = await get_user_meetings_count(user.id)

    if events_count == 0 and meetings_count == 0:
        await update.message.reply_text(
            "📭 У вас пока нет событий для экспорта.\n"
            "Сначала создайте события с помощью /create или встречи с помощью /create_meeting"
        )
        return ConversationHandler.END

    # Показываем меню выбора типа экспорта
    menu_text = (
        f"📊 У вас есть:\n"
        f"• Календарных событий: {events_count}\n"
        f"• Встреч: {meetings_count}\n\n"
        f"Что вы хотите экспортировать?\n\n"
        f"1. Все события (календарь + встречи)\n"
        f"2. Только календарные события\n"
        f"3. Только встречи\n\n"
        f"Введите номер выбранного варианта (1-3):\n"
        f"Или /cancel для отмены"
    )

    set_user_state(user.id, UserState.CREATING_EVENT)
    await update.message.reply_text(menu_text)
    return EXPORT_SELECT_TYPE


# Обработчик выбора типа экспорта
async def export_select_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа экспорта"""
    try:
        choice = int(update.message.text)

        if choice < 1 or choice > 3:
            await update.message.reply_text(
                "❌ Пожалуйста, выберите вариант от 1 до 3.\n"
                "Введите номер выбранного варианта (1-3):"
            )
            return EXPORT_SELECT_TYPE

        # Сохраняем выбранный тип
        type_map = {1: 'all', 2: 'calendar', 3: 'meetings'}
        context.user_data['export_type'] = type_map[choice]

        # Показываем меню выбора формата
        menu_text = (
            "📁 Выберите формат экспорта:\n\n"
            "1. JSON (рекомендуется для программной обработки)\n"
            "2. CSV (рекомендуется для Excel/Google Sheets)\n"
            "3. iCal (рекомендуется для импорта в календарь)\n\n"
            "Введите номер выбранного формата (1-3):\n"
            "Или /cancel для отмены"
        )

        await update.message.reply_text(menu_text)
        return EXPORT_SELECT_FORMAT

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите число от 1 до 3.\n"
            "Введите номер выбранного варианта (1-3):"
        )
        return EXPORT_SELECT_TYPE


# Обработчик выбора формата экспорта
async def export_select_format_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора формата экспорта"""
    try:
        choice = int(update.message.text)

        if choice < 1 or choice > 3:
            await update.message.reply_text(
                "❌ Пожалуйста, выберите вариант от 1 до 3.\n"
                "Введите номер выбранного формата (1-3):"
            )
            return EXPORT_SELECT_FORMAT

        # Сохраняем выбранный формат
        format_map = {1: 'json', 2: 'csv', 3: 'ical'}
        context.user_data['export_format'] = format_map[choice]

        # Предлагаем выбор диапазона дат
        menu_text = (
            "📅 Хотите указать диапазон дат?\n\n"
            "1. Экспортировать все события\n"
            "2. Указать диапазон дат\n\n"
            "Введите номер выбранного варианта (1-2):\n"
            "Или /cancel для отмены"
        )

        await update.message.reply_text(menu_text)
        return EXPORT_SELECT_DATE_RANGE

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите число от 1 до 3.\n"
            "Введите номер выбранного формата (1-3):"
        )
        return EXPORT_SELECT_FORMAT


# Обработчик выбора диапазона дат
async def export_select_date_range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора диапазона дат"""
    try:
        choice = int(update.message.text)

        if choice == 1:
            # Экспортировать все события
            context.user_data['export_date_from'] = None
            context.user_data['export_date_to'] = None

            # Генерируем ссылку для скачивания
            await generate_and_send_export_link(update, context)
            return ConversationHandler.END

        elif choice == 2:
            # Запрашиваем диапазон дат
            await update.message.reply_text(
                "Введите начальную дату в формате ДД.ММ.ГГГГ (например, 01.01.2024):\n"
                "Или /cancel для отмены"
            )
            context.user_data['awaiting_date_from'] = True
            return EXPORT_SELECT_DATE_RANGE

        else:
            await update.message.reply_text(
                "❌ Пожалуйста, выберите вариант 1 или 2.\n"
                "Введите номер выбранного варианта (1-2):"
            )
            return EXPORT_SELECT_DATE_RANGE

    except ValueError:
        # Возможно, пользователь ввел дату
        if context.user_data.get('awaiting_date_from'):
            # Обработка начальной даты
            try:
                date_from = datetime.strptime(update.message.text, "%d.%m.%Y").date()
                context.user_data['export_date_from'] = date_from.strftime("%Y-%m-%d")
                context.user_data['awaiting_date_from'] = False
                context.user_data['awaiting_date_to'] = True

                await update.message.reply_text(
                    "Введите конечную дату в формате ДД.ММ.ГГГГ (например, 31.12.2024):\n"
                    "Или /cancel для отмены"
                )
                return EXPORT_SELECT_DATE_RANGE

            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ\n"
                    "Введите начальную дату:"
                )
                return EXPORT_SELECT_DATE_RANGE

        elif context.user_data.get('awaiting_date_to'):
            # Обработка конечной даты
            try:
                date_to = datetime.strptime(update.message.text, "%d.%m.%Y").date()
                context.user_data['export_date_to'] = date_to.strftime("%Y-%m-%d")
                context.user_data['awaiting_date_to'] = False

                # Генерируем ссылку для скачивания
                await generate_and_send_export_link(update, context)
                return ConversationHandler.END

            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ\n"
                    "Введите конечную дату:"
                )
                return EXPORT_SELECT_DATE_RANGE

        else:
            await update.message.reply_text(
                "❌ Пожалуйста, введите число от 1 до 2.\n"
                "Введите номер выбранного варианта (1-2):"
            )
            return EXPORT_SELECT_DATE_RANGE


# Функция генерации и отправки ссылки для скачивания
async def generate_and_send_export_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация и отправка ссылки для скачивания"""
    user_id = update.effective_user.id

    # Собираем параметры фильтрации
    filters = {
        'event_type': context.user_data.get('export_type', 'all'),
        'date_from': context.user_data.get('export_date_from'),
        'date_to': context.user_data.get('export_date_to')
    }

    format_type = context.user_data.get('export_format', 'json')

    # Генерируем URL
    export_url = generate_export_url(user_id, format_type, filters)

    # Формируем сообщение с информацией
    format_names = {
        'json': 'JSON',
        'csv': 'CSV',
        'ical': 'iCalendar'
    }

    type_names = {
        'all': 'все события',
        'calendar': 'календарные события',
        'meetings': 'встречи'
    }

    info_text = (
        f"✅ Экспорт настроен!\n\n"
        f"📋 Параметры экспорта:\n"
        f"• Тип: {type_names.get(filters['event_type'], filters['event_type'])}\n"
        f"• Формат: {format_names.get(format_type, format_type)}\n"
    )

    if filters['date_from'] or filters['date_to']:
        date_range = []
        if filters['date_from']:
            date_range.append(f"с {filters['date_from']}")
        if filters['date_to']:
            date_range.append(f"по {filters['date_to']}")
        info_text += f"• Диапазон дат: {' '.join(date_range)}\n"

    info_text += f"\n📎 Ссылка для скачивания:\n{export_url}\n\n"
    info_text += "⚠️ Внимание! Эта ссылка действительна в течение ограниченного времени."

    # Отправляем сообщение
    await update.message.reply_text(info_text)

    # Отправляем инструкции
    instructions = (
        "📥 Инструкции по скачиванию:\n\n"
        "1. Скопируйте ссылку выше\n"
        "2. Откройте её в браузере\n"
        "3. Файл автоматически скачается\n\n"
        "💡 Совет: Для iCal файла:\n"
        "• Откройте файл в приложении Календарь\n"
        "• Или импортируйте в Google Calendar, Outlook и т.д."
    )

    await update.message.reply_text(instructions)

    # Сбрасываем состояние
    set_user_state(user_id, UserState.IDLE)

    # Очищаем временные данные
    context.user_data.pop('export_type', None)
    context.user_data.pop('export_format', None)
    context.user_data.pop('export_date_from', None)
    context.user_data.pop('export_date_to', None)
    context.user_data.pop('awaiting_date_from', None)
    context.user_data.pop('awaiting_date_to', None)


# Добавим вспомогательные функции
async def get_user_events_count(telegram_id: int) -> int:
    """Получить количество событий пользователя"""
    try:
        def count_sync():
            user = TelegramUser.objects.get(telegram_id=telegram_id)
            return CalendarEvent.objects.filter(user=user).count()

        return await asyncio.to_thread(count_sync)
    except Exception as e:
        logger.error(f"Ошибка при подсчете событий: {e}")
        return 0


async def get_user_meetings_count(telegram_id: int) -> int:
    """Получить количество встреч пользователя"""
    try:
        def count_sync():
            user = TelegramUser.objects.get(telegram_id=telegram_id)
            return Meeting.objects.filter(
                Q(organizer=user) | Q(participants=user)
            ).distinct().count()

        return await asyncio.to_thread(count_sync)
    except Exception as e:
        logger.error(f"Ошибка при подсчете встреч: {e}")
        return 0


# Обработчик команды /export_quick - быстрый экспорт
async def export_quick_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрый экспорт в формате JSON"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id
    await log_user_interaction(user_id, '/export_quick')

    # Генерируем ссылку для быстрого экспорта (все события в JSON)
    export_url = generate_export_url(user_id, 'json')

    message = (
        "⚡ Быстрый экспорт всех событий в формате JSON\n\n"
        f"📎 Ссылка для скачивания:\n{export_url}\n\n"
        "Нажмите на ссылку, чтобы скачать файл.\n"
        "Файл будет содержать все ваши события и встречи."
    )

    await update.message.reply_text(message)


async def create_meeting_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка даты встречи"""
    context.user_data['meeting_date'] = update.message.text
    await update.message.reply_text("Введите название встречи:")
    return CREATE_MEETING_TITLE


async def create_meeting_title_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка названия встречи"""
    context.user_data['meeting_title'] = update.message.text
    await update.message.reply_text("Введите описание встречи (или /skip чтобы пропустить):")
    return CREATE_MEETING_DESCRIPTION


async def create_meeting_description_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка описания встречи"""
    if update.message.text != '/skip':
        context.user_data['meeting_description'] = update.message.text
    else:
        context.user_data['meeting_description'] = ""

    await update.message.reply_text(
        "Введите время начала встречи в формате ЧЧ:ММ (например, 14:30):"
    )
    return CREATE_MEETING_START_TIME


async def create_meeting_start_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка времени начала встречи"""
    context.user_data['meeting_start_time'] = update.message.text
    await update.message.reply_text(
        "Введите время окончания встречи в формате ЧЧ:ММ (например, 15:30):"
    )
    return CREATE_MEETING_END_TIME


async def create_meeting_end_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка времени окончания встречи"""
    context.user_data['meeting_end_time'] = update.message.text

    await update.message.reply_text(
        "Введите ID участников через запятую (например: 123456, 789012):\n"
        "Или введите 0, чтобы создать встречу только для себя"
    )
    return CREATE_MEETING_PARTICIPANTS


async def create_meeting_participants_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка участников встречи"""
    user_id = update.effective_user.id

    if update.message.text.strip() == '0':
        participant_ids = []
    else:
        try:
            participant_ids = [int(pid.strip()) for pid in update.message.text.split(',')]
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Используйте числа, разделенные запятыми.")
            return ConversationHandler.END

    # Создаем встречу
    success, result, meeting = await create_meeting(
        telegram_id=user_id,
        title=context.user_data['meeting_title'],
        description=context.user_data.get('meeting_description', ''),
        date_str=context.user_data['meeting_date'],
        start_time_str=context.user_data['meeting_start_time'],
        end_time_str=context.user_data['meeting_end_time'],
        participant_ids=participant_ids
    )

    if success and meeting:
        # Отправляем реальные приглашения участникам
        try:
            def get_pending_participants():
                pending_participants = MeetingParticipant.objects.filter(
                    meeting=meeting,
                    status='pending'
                ).select_related('participant')

                logger.info(f"Найдено {pending_participants.count()} участников, ожидающих подтверждения")
                return [mp.participant for mp in pending_participants]

            pending_participants = await asyncio.to_thread(get_pending_participants)

            if pending_participants:
                await send_meeting_invitations(context, meeting, pending_participants)
                result += f"\n\n📨 Приглашения отправлены {len(pending_participants)} участникам в Telegram!"
            else:
                result += f"\n\nℹ️ Нет участников, ожидающих приглашений."
        except Exception as e:
            logger.error(f"Ошибка при отправке приглашений: {e}")
            result += f"\n\n⚠️ Приглашения сохранены в системе, но возникла ошибка при отправке в Telegram."

    set_user_state(user_id, UserState.IDLE)
    await update.message.reply_text(result)
    return ConversationHandler.END

    # Создаем встречу
    success, result, _ = await create_meeting(
        telegram_id=user_id,
        title=context.user_data['meeting_title'],
        description=context.user_data.get('meeting_description', ''),
        date_str=context.user_data['meeting_date'],
        start_time_str=context.user_data['meeting_start_time'],
        end_time_str=context.user_data['meeting_end_time'],
        participant_ids=participant_ids
    )

    set_user_state(user_id, UserState.IDLE)
    await update.message.reply_text(result)
    return ConversationHandler.END


async def meeting_invitations_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать приглашения на встречи"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id

    try:
        # Синхронная функция для получения приглашений
        def get_invitations_sync():
            user = TelegramUser.objects.get(telegram_id=user_id)
            invitations = MeetingParticipant.objects.filter(
                participant=user,
                status='pending'
            ).select_related('meeting', 'meeting__organizer')
            return list(invitations)

        invitations = await asyncio.to_thread(get_invitations_sync)

        if not invitations:
            await update.message.reply_text("📭 У вас нет новых приглашений на встречи")
            return

        result = "📨 Ваши приглашения на встречи:\n\n"

        for i, invitation in enumerate(invitations, 1):
            meeting = invitation.meeting
            date_str = meeting.date.strftime("%d.%m.%Y")
            time_str = f"{meeting.start_time.strftime('%H:%M')} - {meeting.end_time.strftime('%H:%M')}"

            result += f"{i}. 📅 {date_str} {time_str}\n"
            result += f"   📌 {meeting.title}\n"
            result += f"   👤 Организатор: {meeting.organizer.first_name or meeting.organizer.username or meeting.organizer.telegram_id}\n"
            if meeting.description:
                result += f"   📝 {meeting.description[:50]}...\n"
            result += f"   ID встречи: {meeting.id}\n"
            result += f"   Подтвердить: /confirm_meeting_{meeting.id}\n"
            result += f"   Отклонить: /decline_meeting_{meeting.id}\n"
            result += "─" * 40 + "\n"

        await update.message.reply_text(result)

    except Exception as e:
        logger.error(f"Ошибка при получении приглашений: {e}")
        await update.message.reply_text("❌ Ошибка при получении приглашений")


async def confirm_meeting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтвердить встречу"""
    if not await ensure_registered(update, context):
        return

    # Извлекаем ID встречи из команды
    command = update.message.text
    meeting_id = int(command.replace('/confirm_meeting_', ''))

    user_id = update.effective_user.id
    success, result = await respond_to_meeting_invitation(user_id, meeting_id, 'confirm')

    if success:
        # Отправляем сообщение пользователю
        await update.message.reply_text(result)

        try:
            # Получаем детали встречи для отправки уведомления организатору
            def get_meeting_details():
                meeting = Meeting.objects.get(id=meeting_id)
                user = TelegramUser.objects.get(telegram_id=user_id)
                return meeting, user

            meeting, user = await asyncio.to_thread(get_meeting_details)

            # Отправляем уведомление организатору
            organizer_message = (
                f"✅ {user.first_name or user.username or 'Пользователь'} "
                f"подтвердил(а) ваше приглашение на встречу '{meeting.title}'"
            )

            # СОБИРАЕМ КОНТЕКСТ ДЛЯ ОТПРАВКИ
            await send_telegram_notification_to_user(
                context,
                meeting.organizer.telegram_id,
                organizer_message
            )

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления организатору: {e}")
    else:
        await update.message.reply_text(result)


async def decline_meeting_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклонить встречу"""
    if not await ensure_registered(update, context):
        return

    # Извлекаем ID встречи из команды
    command = update.message.text
    meeting_id = int(command.replace('/decline_meeting_', ''))

    user_id = update.effective_user.id
    success, result = await respond_to_meeting_invitation(user_id, meeting_id, 'decline')

    if success:
        # Отправляем сообщение пользователю
        await update.message.reply_text(result)

        try:
            # Получаем детали встречи для отправки уведомления организатору
            def get_meeting_details():
                meeting = Meeting.objects.get(id=meeting_id)
                user = TelegramUser.objects.get(telegram_id=user_id)
                return meeting, user

            meeting, user = await asyncio.to_thread(get_meeting_details)

            # Отправляем уведомление организатору
            organizer_message = (
                f"❌ {user.first_name or user.username or 'Пользователь'} "
                f"отклонил(а) ваше приглашение на встречу '{meeting.title}'"
            )

            await send_telegram_notification_to_user(
                context,
                meeting.organizer.telegram_id,
                organizer_message
            )

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления организатору: {e}")
    else:
        await update.message.reply_text(result)


async def notifications_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать уведомления пользователя"""
    if not await ensure_registered(update, context):
        return

    user_id = update.effective_user.id

    try:
        # Синхронная функция для получения уведомлений
        def get_notifications_sync():
            user = TelegramUser.objects.get(telegram_id=user_id)
            notifications = MeetingNotification.objects.filter(
                user=user
            ).select_related('meeting').order_by('-sent_at')[:20]  # Последние 20 уведомлений

            return list(notifications)

        notifications = await asyncio.to_thread(get_notifications_sync)

        if not notifications:
            await update.message.reply_text("📭 У вас нет уведомлений")
            return

        result = "📨 Ваши уведомления:\n\n"
        unread_count = 0

        for i, notification in enumerate(notifications, 1):
            read_status = "✅" if notification.read_at else "🆕"
            if not notification.read_at:
                unread_count += 1

            type_icon = {
                'invitation': '📨',
                'confirmation': '✅',
                'cancellation': '❌',
                'reminder': '⏰',
                'update': '🔄'
            }.get(notification.notification_type, '📧')

            time_str = notification.sent_at.strftime('%d.%m.%Y %H:%M')
            result += f"{i}. {read_status} {type_icon} {time_str}\n"
            result += f"   {notification.message}\n"

            # Для приглашений показываем кнопки действий
            if notification.notification_type == 'invitation' and notification.meeting:
                result += f"   Действия: /confirm_meeting_{notification.meeting.id} /decline_meeting_{notification.meeting.id}\n"

            result += "─" * 40 + "\n"

        result += f"\n📊 Всего уведомлений: {len(notifications)}"
        if unread_count > 0:
            result += f" (🆕 {unread_count} новых)"

        await update.message.reply_text(result)

    except Exception as e:
        logger.error(f"Ошибка при получении уведомлений: {e}")
        await update.message.reply_text("❌ Ошибка при получении уведомлений")

async def meeting_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детали встречи"""
    if not await ensure_registered(update, context):
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите ID встречи. Пример: /meeting 1")
        return

    try:
        meeting_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID встречи должен быть числом")
        return

    user_id = update.effective_user.id

    try:
        # Синхронная функция для получения деталей встречи
        def get_meeting_detail_sync():
            meeting = Meeting.objects.get(id=meeting_id)

            # Проверяем, имеет ли пользователь доступ к встрече
            if (meeting.organizer.telegram_id != user_id and
                    not meeting.participants.filter(telegram_id=user_id).exists()):
                return None

            # Получаем участников с их статусами
            participants = MeetingParticipant.objects.filter(
                meeting=meeting
            ).select_related('participant')

            return meeting, list(participants)

        result = await asyncio.to_thread(get_meeting_detail_sync)

        if not result:
            await update.message.reply_text("❌ Встреча не найдена или у вас нет доступа")
            return

        meeting, participants = result

        # Форматируем информацию о встрече
        date_str = meeting.date.strftime("%d.%m.%Y")
        start_time = meeting.start_time.strftime("%H:%M")
        end_time = meeting.end_time.strftime("%H:%M")

        result_text = f"""
        📅 Детали встречи:

        ID: {meeting.id}
        Название: {meeting.title}
        Дата: {date_str}
        Время: {start_time} - {end_time}
        Статус: {meeting.get_status_display()}

        👑 Организатор:
        • {meeting.organizer.first_name or meeting.organizer.username or meeting.organizer.telegram_id}

        👥 Участники:
        """

        for participant in participants:
            status_icon = "🟢" if participant.status == 'confirmed' else "🟡" if participant.status == 'pending' else "🔴"
            name = participant.participant.first_name or participant.participant.username or participant.participant.telegram_id
            result_text += f"• {status_icon} {name} ({participant.get_status_display()})\n"

        if meeting.description:
            result_text += f"\n📝 Описание:\n{meeting.description}"

        await update.message.reply_text(result_text)

    except Meeting.DoesNotExist:
        await update.message.reply_text("❌ Встреча не найдена")
    except Exception as e:
        logger.error(f"Ошибка при получении деталей встречи: {e}")
        await update.message.reply_text("❌ Ошибка при получении деталей встречи")


async def send_meeting_invitations(context: ContextTypes.DEFAULT_TYPE,
                                   meeting: Meeting,
                                   participants: List[TelegramUser]):
    """Отправить приглашения на встречу участникам"""
    for participant in participants:
        try:
            invitation_message = (
                f"📨 Вас пригласили на встречу!\n\n"
                f"📅 **{meeting.title}**\n"
                f"📅 Дата: {meeting.date.strftime('%d.%m.%Y')}\n"
                f"🕐 Время: {meeting.start_time.strftime('%H:%M')} - {meeting.end_time.strftime('%H:%M')}\n"
                f"👑 Организатор: {meeting.organizer.first_name or meeting.organizer.username}\n"
                f"📝 Описание: {meeting.description or 'Нет описания'}\n\n"
                f"Для подтверждения используйте команду:\n"
                f"`/confirm_meeting_{meeting.id}`\n\n"
                f"Для отклонения:\n"
                f"`/decline_meeting_{meeting.id}`"
            )

            await send_telegram_notification_to_user(
                context,
                participant.telegram_id,
                invitation_message
            )

            logger.info(f"Приглашение отправлено пользователю {participant.telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка при отправке приглашения {participant.telegram_id}: {e}")

async def check_availability_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить доступность пользователя"""
    if not await ensure_registered(update, context):
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ Формат: /check_availability <ID_пользователя> <дата ДД.ММ.ГГГГ> <время начала ЧЧ:ММ> <время окончания ЧЧ:ММ>\n"
            "Пример: /check_availability 123456 25.12.2024 14:00 15:00"
        )
        return

    try:
        target_user_id = int(context.args[0])
        date_str = context.args[1]
        start_time_str = context.args[2]
        end_time_str = context.args[3] if len(context.args) > 3 else "23:59"

        date_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        # Проверяем доступность
        is_available = await check_user_availability(target_user_id, date_obj, start_time, end_time)

        if is_available:
            await update.message.reply_text(
                f"✅ Пользователь {target_user_id} свободен {date_str} с {start_time_str} до {end_time_str}"
            )
        else:
            await update.message.reply_text(
                f"❌ Пользователь {target_user_id} занят {date_str} с {start_time_str} до {end_time_str}"
            )

    except ValueError:
        await update.message.reply_text("❌ Неверный формат данных")
    except Exception as e:
        logger.error(f"Ошибка при проверке доступности: {e}")
        await update.message.reply_text("❌ Ошибка при проверке доступности")


async def my_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ID пользователя"""
    user = update.effective_user

    # Получаем информацию о пользователе из базы
    try:
        # Проверяем регистрацию
        if not await ensure_registered(update, context):
            return

        # Формируем сообщение
        message = f"""
        👤 Ваш профиль:

        📋 Ваши ID для приглашений:
        • **Telegram ID**: `{user.id}`

        💡 Как использовать:
        1. Отправьте этот номер другу: `{user.id}`
        2. Друг вводит этот ID при создании встречи

        📝 Пример:
        При создании встречи в поле "Участники" введите:
        `{user.id}`

        🔒 Ваш ID защищен и виден только вам.
        """

        await update.message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Ошибка в my_id_handler: {e}")
        await update.message.reply_text(
            "❌ Ошибка при получении ID. Попробуйте снова или используйте /start"
        )


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


async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin_stats"""
    user_id = update.effective_user.id

    # Проверка на администратора
    ADMIN_IDS = [123456789]  # Замените на ваш ID

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
        return

    try:
        # Синхронная функция для получения статистики
        def get_admin_stats_sync():
            from django.db.models import Q
            stats, created = BotStatistics.objects.get_or_create(date=timezone.now().date())

            # Обновляем статистику
            stats.total_users = TelegramUser.objects.count()
            stats.total_events = CalendarEvent.objects.count()

            # Активные пользователи за сегодня
            today = timezone.now().date()
            active_users_today = TelegramUser.objects.filter(
                Q(events__created_at__date=today) |
                Q(last_seen__date=today)
            ).distinct().count()
            stats.daily_active_users = active_users_today

            stats.save()
            return stats

        stats = await asyncio.to_thread(get_admin_stats_sync)

        message = f"""
        📊 Административная статистика бота

        👥 Пользователи:
        • Всего пользователей: {stats.total_users}
        • Новых сегодня: {stats.daily_new_users}
        • Активных сегодня: {stats.daily_active_users}

        📅 События:
        • Всего событий: {stats.total_events}
        • Создано сегодня: {stats.daily_created_events}
        • Обновлено сегодня: {stats.daily_updated_events}
        • Удалено сегодня: {stats.daily_deleted_events}

        📋 Команды за сегодня:
        • /start: {stats.daily_start_commands}
        • /help: {stats.daily_help_commands}
        • /list: {stats.daily_list_commands}
        • /today: {stats.daily_today_commands}
        • /stats: {stats.daily_stats_commands}

        🕒 Статистика обновлена: {stats.updated_at.strftime('%H:%M:%S')}
        """

        await update.message.reply_text(message)

    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await update.message.reply_text("❌ Ошибка при получении статистики.")


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

    # Создаем ConversationHandler для создания встреч
    create_meeting_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('create_meeting', create_meeting_handler)],
        states={
            CREATE_MEETING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_meeting_date_handler)],
            CREATE_MEETING_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_meeting_title_handler)],
            CREATE_MEETING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_meeting_description_handler)],
            CREATE_MEETING_START_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_meeting_start_time_handler)],
            CREATE_MEETING_END_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_meeting_end_time_handler)],
            CREATE_MEETING_PARTICIPANTS: [MessageHandler(filters.TEXT, create_meeting_participants_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    # Создаем ConversationHandler для публикации событий
    share_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('share', share_handler)],
        states={
            PUBLISH_SELECT_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, publish_select_event_handler)],
            PUBLISH_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, publish_confirm_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    # Создаем ConversationHandler для снятия публикации событий
    unshare_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('unshare', unshare_handler)],
        states={
            UNPUBLISH_SELECT_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, unpublish_select_event_handler)],
            UNPUBLISH_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, unpublish_confirm_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    # Создаем ConversationHandler для экспорта
    export_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('export', export_handler)],
        states={
            EXPORT_SELECT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, export_select_type_handler)],
            EXPORT_SELECT_FORMAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, export_select_format_handler)],
            EXPORT_SELECT_DATE_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, export_select_date_range_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )

    application.add_handler(CommandHandler("my_id", my_id_handler))

    # Регистрируем обработчики команд
    application.add_handler(create_conv_handler)
    application.add_handler(update_conv_handler)
    application.add_handler(create_meeting_conv_handler)
    application.add_handler(share_conv_handler)
    application.add_handler(unshare_conv_handler)
    application.add_handler(export_conv_handler)
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("profile", profile_handler))
    application.add_handler(CommandHandler("read", read_handler))
    application.add_handler(CommandHandler("delete", delete_handler))
    application.add_handler(CommandHandler("list", list_handler))
    application.add_handler(CommandHandler("today", today_handler))
    application.add_handler(CommandHandler("events", events_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("meetings", meetings_handler))
    application.add_handler(CommandHandler("meeting", meeting_detail_handler))
    application.add_handler(CommandHandler("invitations", meeting_invitations_handler))
    application.add_handler(CommandHandler("notifications", notifications_handler))
    application.add_handler(CommandHandler("check_availability", check_availability_handler))
    application.add_handler(CommandHandler("shared", shared_handler))
    application.add_handler(CommandHandler("shared_by", shared_by_handler))
    application.add_handler(CommandHandler("share_stats", share_stats_handler))
    application.add_handler(CommandHandler("export_quick", export_quick_handler))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    application.add_handler(CommandHandler("admin_stats", admin_stats_handler))

    # Динамические обработчики для подтверждения/отклонения встреч
    application.add_handler(MessageHandler(
        filters.Regex(r'^/confirm_meeting_\d+$'),
        confirm_meeting_handler
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r'^/decline_meeting_\d+$'),
        decline_meeting_handler
    ))

    # Обработчик неизвестных команд (должен быть последним)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_handler))

    # Запускаем бота
    print("📅 Бот-календарь запускается...")
    print("Используйте Ctrl+C для остановки")

    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        print("✅ Бот остановлен")


if __name__ == '__main__':
    main()