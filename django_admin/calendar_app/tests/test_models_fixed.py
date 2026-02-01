import pytest
from django.test import TestCase
from django.utils import timezone
from datetime import date


@pytest.mark.django_db
class TestTelegramUserModel(TestCase):
    """Тесты модели TelegramUser"""

    def test_create_user(self):
        """Тест создания пользователя"""
        from calendar_app.models import TelegramUser

        user = TelegramUser.objects.create(
            telegram_id=123456789,
            username="testuser",
            first_name="Иван"
        )

        assert user.telegram_id == 123456789
        assert user.username == "testuser"
        assert user.first_name == "Иван"
        assert user.registered_at is not None

        # Проверяем строковое представление
        str_repr = str(user)
        assert "123456789" in str_repr
        print(f"✅ Создан пользователь: {user}")

    def test_user_uniqueness(self):
        """Тест уникальности telegram_id"""
        from calendar_app.models import TelegramUser

        # Создаем первого пользователя
        TelegramUser.objects.create(telegram_id=999888777)

        # Попытка создать второго с таким же ID должна вызвать ошибку
        with pytest.raises(Exception):
            TelegramUser.objects.create(telegram_id=999888777)


@pytest.mark.django_db
class TestCalendarEventModel(TestCase):
    """Тесты модели CalendarEvent"""

    def setUp(self):
        from calendar_app.models import TelegramUser, CalendarEvent
        self.TelegramUser = TelegramUser
        self.CalendarEvent = CalendarEvent

        self.user = self.TelegramUser.objects.create(
            telegram_id=111222333,
            username="eventuser"
        )

    def test_create_event(self):
        """Тест создания события"""
        event = self.CalendarEvent.objects.create(
            user=self.user,
            date=date.today(),
            title="Тестовое событие",
            description="Описание события"
        )

        assert event.user == self.user
        assert event.title == "Тестовое событие"
        assert event.date == date.today()
        assert not event.is_public  # По умолчанию приватное

        print(f"✅ Создано событие: {event}")

    def test_event_status_methods(self):
        """Тест методов статуса события"""
        # Событие на сегодня
        today_event = self.CalendarEvent.objects.create(
            user=self.user,
            date=date.today(),
            title="Сегодня"
        )

        # Событие в будущем
        future_event = self.CalendarEvent.objects.create(
            user=self.user,
            date=date.today().replace(year=date.today().year + 1),
            title="Будущее"
        )

        # Событие в прошлом
        past_event = self.CalendarEvent.objects.create(
            user=self.user,
            date=date.today().replace(year=date.today().year - 1),
            title="Прошлое"
        )

        # Проверяем методы
        assert today_event.is_today()
        assert future_event.is_future()
        assert past_event.is_past()

        print("✅ Методы статуса событий работают корректно")