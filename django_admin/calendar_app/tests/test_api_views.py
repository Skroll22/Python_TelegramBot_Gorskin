import pytest
import json
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta


@pytest.mark.django_db
class TestPublicEventsAPI(TestCase):
    """Тесты публичного API для событий"""

    def setUp(self):
        self.client = APIClient()

        from calendar_app.models import TelegramUser, CalendarEvent

        # Создаем пользователей
        self.user1 = TelegramUser.objects.create(
            telegram_id=111111111,
            username="user1"
        )

        self.user2 = TelegramUser.objects.create(
            telegram_id=222222222,
            username="user2"
        )

        # Создаем публичные и приватные события
        self.public_event1 = CalendarEvent.objects.create(
            user=self.user1,
            date=timezone.now().date() + timedelta(days=1),
            title="Public Event 1",
            is_public=True
        )

        self.public_event2 = CalendarEvent.objects.create(
            user=self.user2,
            date=timezone.now().date() + timedelta(days=2),
            title="Public Event 2",
            is_public=True
        )

        self.private_event = CalendarEvent.objects.create(
            user=self.user1,
            date=timezone.now().date() + timedelta(days=3),
            title="Private Event",
            is_public=False
        )

    def test_get_public_events(self):
        """Тест получения публичных событий"""
        url = '/api/public/events/'
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        # Проверяем что в ответе есть события
        if 'results' in response.data:  # Если есть пагинация
            events = response.data['results']
            assert len(events) >= 2
        else:
            events = response.data
            assert len(events) >= 2

        # Проверяем что только публичные события
        for event in events if isinstance(events, list) else []:
            assert event['is_public'] is True

    def test_get_public_stats(self):
        """Тест получения публичной статистики"""
        url = '/api/public/stats/'
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        # Проверяем структуру ответа
        expected_fields = [
            'total_users', 'total_events', 'public_events',
            'total_meetings', 'active_today', 'new_today'
        ]

        for field in expected_fields:
            assert field in response.data
            assert isinstance(response.data[field], int)


@pytest.mark.django_db
class TestCalendarEventAPI(TestCase):
    """Тесты API для событий"""

    def setUp(self):
        self.client = APIClient()

        from calendar_app.models import TelegramUser, CalendarEvent

        self.user = TelegramUser.objects.create(
            telegram_id=333333333,
            username="apiuser"
        )

        self.event = CalendarEvent.objects.create(
            user=self.user,
            date=timezone.now().date() + timedelta(days=5),
            title="API Test Event",
            description="For API testing",
            is_public=True
        )

    def test_get_event_list_unauthorized(self):
        """Тест получения списка событий без авторизации"""
        url = '/api/events/'
        response = self.client.get(url)

        # Без авторизации должен быть доступ запрещен
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ]

    def test_get_event_detail_unauthorized(self):
        """Тест получения деталей события без авторизации"""
        url = f'/api/events/{self.event.id}/'
        response = self.client.get(url)

        # Без авторизации должен быть доступ запрещен
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ]