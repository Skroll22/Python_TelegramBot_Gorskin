import pytest
from django.test import TestCase
from django.utils import timezone
from datetime import datetime, timedelta


@pytest.mark.django_db
class TestUserEventIntegration(TestCase):
    """Интеграционные тесты для пользователей и событий"""

    def setUp(self):
        from calendar_app.models import TelegramUser, CalendarEvent

        self.TelegramUser = TelegramUser
        self.CalendarEvent = CalendarEvent

        # Создаем пользователя
        self.user = self.TelegramUser.objects.create(
            telegram_id=444444444,
            username="integration_user"
        )

    def test_user_events_flow(self):
        """Тест полного потока работы с событиями пользователя"""
        # 1. Создание событий
        event1 = self.CalendarEvent.objects.create(
            user=self.user,
            date=timezone.now().date() + timedelta(days=1),
            title="Event 1",
            is_public=True
        )

        event2 = self.CalendarEvent.objects.create(
            user=self.user,
            date=timezone.now().date() + timedelta(days=2),
            title="Event 2",
            is_public=False
        )

        # 2. Проверка подсчета
        assert self.user.events_count() == 2

        # 3. Проверка публичных/приватных
        public_events = self.CalendarEvent.objects.filter(
            user=self.user,
            is_public=True
        )
        assert public_events.count() == 1

        private_events = self.CalendarEvent.objects.filter(
            user=self.user,
            is_public=False
        )
        assert private_events.count() == 1

        # 4. Обновление события
        event1.title = "Updated Event 1"
        event1.save()

        updated_event = self.CalendarEvent.objects.get(id=event1.id)
        assert updated_event.title == "Updated Event 1"

        # 5. Удаление события
        event_id = event2.id
        event2.delete()

        with pytest.raises(self.CalendarEvent.DoesNotExist):
            self.CalendarEvent.objects.get(id=event_id)

        # 6. Проверка итогового количества
        assert self.user.events_count() == 1


@pytest.mark.django_db
class TestMeetingIntegration(TestCase):
    """Интеграционные тесты для встреч"""

    def setUp(self):
        from calendar_app.models import TelegramUser, Meeting, MeetingParticipant

        self.TelegramUser = TelegramUser
        self.Meeting = Meeting
        self.MeetingParticipant = MeetingParticipant

        # Создаем пользователей
        self.organizer = self.TelegramUser.objects.create(
            telegram_id=555555555,
            username="organizer"
        )

        self.participant1 = self.TelegramUser.objects.create(
            telegram_id=666666666,
            username="participant1"
        )

        self.participant2 = self.TelegramUser.objects.create(
            telegram_id=777777777,
            username="participant2"
        )

    def test_meeting_participants_flow(self):
        """Тест потока участников встречи"""
        # 1. Создание встречи
        meeting = self.Meeting.objects.create(
            title="Team Meeting",
            date=timezone.now().date() + timedelta(days=3),
            start_time=datetime.strptime("14:00", "%H:%M").time(),
            end_time=datetime.strptime("15:30", "%H:%M").time(),
            organizer=self.organizer,
            status='pending'
        )

        # 2. Добавление участников
        participant1 = self.MeetingParticipant.objects.create(
            meeting=meeting,
            participant=self.participant1,
            status='pending'
        )

        participant2 = self.MeetingParticipant.objects.create(
            meeting=meeting,
            participant=self.participant2,
            status='pending'
        )

        # 3. Проверка начального состояния
        assert meeting.participants.count() == 2
        assert meeting.status == 'pending'

        # 4. Участник 1 подтверждает
        participant1.status = 'confirmed'
        participant1.save()

        # 5. Участник 2 отклоняет
        participant2.status = 'declined'
        participant2.save()

        # 6. Проверка итогового состояния
        meeting.refresh_from_db()

        confirmed = meeting.meeting_participants.filter(status='confirmed')
        declined = meeting.meeting_participants.filter(status='declined')

        assert confirmed.count() == 1
        assert declined.count() == 1