import asyncio
import logging
from typing import List, Optional
from django.utils import timezone
from datetime import datetime, timedelta

from .models import Meeting, MeetingParticipant, MeetingNotification, TelegramUser

logger = logging.getLogger(__name__)


async def send_telegram_notification(telegram_id: int, message: str) -> bool:
    """Отправить уведомление в Telegram"""
    try:
        # Здесь будет логика отправки через Telegram API
        # Пока просто логируем
        logger.info(f"Уведомление для {telegram_id}: {message}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")
        return False


async def create_meeting_invitation(meeting: Meeting, participants: List[TelegramUser]) -> List[MeetingNotification]:
    """Создать приглашения на встречу"""
    notifications = []

    for participant in participants:
        # Создаем уведомление в базе
        notification = MeetingNotification.objects.create(
            meeting=meeting,
            user=participant,
            notification_type='invitation',
            message=f"Вас пригласили на встречу '{meeting.title}' {meeting.date.strftime('%d.%m.%Y')} "
                    f"с {meeting.start_time.strftime('%H:%M')} до {meeting.end_time.strftime('%H:%M')}"
        )
        notifications.append(notification)

        # Отправляем в Telegram
        telegram_message = (
            f"📨 Вас пригласили на встречу!\n\n"
            f"📅 {meeting.title}\n"
            f"📅 Дата: {meeting.date.strftime('%d.%m.%Y')}\n"
            f"🕐 Время: {meeting.start_time.strftime('%H:%M')} - {meeting.end_time.strftime('%H:%M')}\n"
            f"👑 Организатор: {meeting.organizer.first_name or meeting.organizer.username}\n\n"
            f"Подтвердить: /confirm_meeting_{meeting.id}\n"
            f"Отклонить: /decline_meeting_{meeting.id}"
        )

        await send_telegram_notification(participant.telegram_id, telegram_message)

    return notifications


async def send_meeting_confirmation(meeting: Meeting, participant: TelegramUser) -> bool:
    """Отправить подтверждение встречи организатору"""
    try:
        message = (
            f"✅ {participant.first_name or participant.username} подтвердил(а) ваше приглашение "
            f"на встречу '{meeting.title}'"
        )

        # Создаем уведомление в базе
        MeetingNotification.objects.create(
            meeting=meeting,
            user=meeting.organizer,
            notification_type='confirmation',
            message=message
        )

        # Отправляем в Telegram
        await send_telegram_notification(meeting.organizer.telegram_id, message)
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке подтверждения: {e}")
        return False


async def send_meeting_declination(meeting: Meeting, participant: TelegramUser) -> bool:
    """Отправить уведомление об отказе организатору"""
    try:
        message = (
            f"❌ {participant.first_name or participant.username} отклонил(а) ваше приглашение "
            f"на встречу '{meeting.title}'"
        )

        # Создаем уведомление в базе
        MeetingNotification.objects.create(
            meeting=meeting,
            user=meeting.organizer,
            notification_type='cancellation',
            message=message
        )

        # Отправляем в Telegram
        await send_telegram_notification(meeting.organizer.telegram_id, message)
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке отказа: {e}")
        return False


async def send_reminders():
    """Отправить напоминания о предстоящих встречах"""
    try:
        now = timezone.now()
        reminder_time = now + timedelta(hours=1)  # За час до встречи

        # Находим встречи, которые начнутся через час
        upcoming_meetings = Meeting.objects.filter(
            date=reminder_time.date(),
            start_time__hour=reminder_time.hour,
            status='confirmed'
        )

        for meeting in upcoming_meetings:
            # Получаем подтвержденных участников
            confirmed_participants = meeting.get_confirmed_participants()

            for participant in confirmed_participants:
                message = (
                    f"⏰ Напоминание о встрече!\n\n"
                    f"📅 {meeting.title}\n"
                    f"📅 Дата: {meeting.date.strftime('%d.%m.%Y')}\n"
                    f"🕐 Время: {meeting.start_time.strftime('%H:%M')} - {meeting.end_time.strftime('%H:%M')}\n"
                    f"📍 Организатор: {meeting.organizer.first_name or meeting.organizer.username}"
                )

                # Создаем уведомление в базе
                MeetingNotification.objects.create(
                    meeting=meeting,
                    user=participant,
                    notification_type='reminder',
                    message=message
                )

                # Отправляем в Telegram
                await send_telegram_notification(participant.telegram_id, message)

    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний: {e}")


def get_unread_notifications_count(telegram_id: int) -> int:
    """Получить количество непрочитанных уведомлений"""
    try:
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        return MeetingNotification.objects.filter(user=user, read_at__isnull=True).count()
    except TelegramUser.DoesNotExist:
        return 0