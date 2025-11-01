# tests/test_users.py
import pytest
from django.db import connection
from myapp.models import BotStatistics
from unittest.mock import patch
import asyncio


class TestUserManagement:
    """Тесты управления пользователями"""

    def test_user_registration(self, db):
        """Тест регистрации пользователя в базе данных"""
        from bot import Calendar

        calendar = Calendar()

        # Тестовые данные
        user_data = {
            'user_id': 999999999,
            'username': 'test_user',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'testpass123'
        }

        # Регистрируем пользователя
        result = asyncio.run(calendar.register_user(**user_data))

        assert result is True

        # Проверяем что пользователь добавлен в БД
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT username FROM users WHERE user_id = %s",
                [user_data['user_id']]
            )
            user = cursor.fetchone()
            assert user is not None
            assert user[0] == user_data['username']

    def test_is_user_registered(self, db):
        """Тест проверки регистрации пользователя"""
        from bot import Calendar

        calendar = Calendar()

        # Сначала добавляем тестового пользователя
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, password)
                VALUES (%s, %s, %s, %s, %s)
            ''', (888888888, 'registered_user', 'John', 'Doe', 'password123'))

        # Проверяем что пользователь зарегистрирован
        result = asyncio.run(calendar.is_user_registered(888888888))
        assert result is True

        # Проверяем что несуществующий пользователь не зарегистрирован
        result = asyncio.run(calendar.is_user_registered(111111111))
        assert result is False

    def test_user_statistics_update(self, db):
        """Тест обновления статистики пользователей"""
        from bot import Calendar

        calendar = Calendar()

        # Добавляем тестовых пользователей и события
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, password) 
                VALUES (111, 'user1', 'pass1'), (222, 'user2', 'pass2')
            ''')
            cursor.execute('''
                INSERT INTO events (user_id, event_name, event_date) 
                VALUES (111, 'Event 1', '2024-01-01'), (222, 'Event 2', '2024-01-02')
            ''')

        # Обновляем статистику
        asyncio.run(calendar.update_statistics())

        # Проверяем что статистика обновилась
        stats = BotStatistics.objects.last()
        assert stats.total_users == 2
        assert stats.total_events == 2
        assert stats.active_users == 2