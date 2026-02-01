import pytest
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, datetime


@pytest.mark.django_db
class TestMeetingNotifications(TestCase):
    """Тесты для системы уведомлений"""

    def setUp(self):
        from calendar_app.models import (
            TelegramUser, Meeting, MeetingNotification
        )

        self.TelegramUser = TelegramUser
        self.Meeting = Meeting
        self.MeetingNotification = MeetingNotification

        # Создаем пользователей
        self.organizer = self.TelegramUser.objects.create(
            telegram_id=888888888,
            username="org"
        )

        self.participant = self.TelegramUser.objects.create(
            telegram_id=999999999,
            username="part"
        )

        # Создаем встречу
        self.meeting = self.Meeting.objects.create(
            title="Notification Test Meeting",
            date=timezone.now().date() + timedelta(days=2),
            start_time=datetime.strptime("14:00", "%H:%M").time(),
            end_time=datetime.strptime("15:30", "%H:%M").time(),
            organizer=self.organizer,
            status='pending'
        )

    def test_notification_creation(self):
        """Тест создания уведомления"""
        notification = self.MeetingNotification.objects.create(
            meeting=self.meeting,
            user=self.participant,
            notification_type='invitation',
            message=f"Вас пригласили на встречу '{self.meeting.title}'"
        )

        assert notification.id is not None
        assert notification.sent_at is not None
        assert notification.read_at is None
        assert notification.notification_type == 'invitation'
        assert self.meeting.title in notification.message

        print(f"✅ Создано уведомление: {notification}")

    def test_notification_mark_as_read(self):
        """Тест пометки уведомления как прочитанного"""
        notification = self.MeetingNotification.objects.create(
            meeting=self.meeting,
            user=self.participant,
            notification_type='invitation',
            message="Test"
        )

        assert notification.read_at is None

        # Помечаем как прочитанное
        notification.mark_as_read()
        notification.refresh_from_db()

        assert notification.read_at is not None
        assert isinstance(notification.read_at, timezone.datetime)

        print(f"✅ Уведомление помечено как прочитанное: {notification.read_at}")