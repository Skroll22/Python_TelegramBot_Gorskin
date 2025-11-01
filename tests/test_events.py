import pytest
from datetime import datetime, date
from django.db import connection
import asyncio


class TestEventManagement:
    """Тесты управления событиями"""

    @pytest.fixture
    def test_user(self, db):
        """Fixture для тестового пользователя"""
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, password)
                VALUES (%s, %s, %s, %s)
                RETURNING user_id
            ''', (123456, 'event_user', 'Event', 'password123'))
            return cursor.fetchone()[0]

    def test_add_event(self, test_user, db):
        """Тест добавления события"""
        from bot import Calendar

        calendar = Calendar()

        event_data = {
            'user_id': test_user,
            'username': 'event_user',
            'first_name': 'Event',
            'last_name': 'User',
            'event_name': 'Тестовое событие',
            'event_date': '15.12.2024'
        }

        result = asyncio.run(calendar.add_event(**event_data))
        assert result is True

        # Проверяем что событие добавлено в БД
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_name FROM events WHERE user_id = %s",
                [test_user]
            )
            event = cursor.fetchone()
            assert event is not None
            assert event[0] == 'Тестовое событие'

    def test_get_events(self, test_user, db):
        """Тест получения событий пользователя"""
        from bot import Calendar

        calendar = Calendar()

        # Добавляем тестовые события
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO events (user_id, event_name, event_date)
                VALUES 
                    (%s, 'Event 1', '2024-12-01'),
                    (%s, 'Event 2', '2024-12-02')
            ''', [test_user, test_user])

        events = asyncio.run(calendar.get_events(test_user))

        assert len(events) == 2
        assert events[0][0] == 'Event 1'
        assert events[1][0] == 'Event 2'

    def test_delete_event(self, test_user, db):
        """Тест удаления события"""
        from bot import Calendar

        calendar = Calendar()

        # Добавляем событие для удаления
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO events (user_id, event_name, event_date)
                VALUES (%s, 'Event to delete', '2024-12-01')
            ''', [test_user])

        result = asyncio.run(calendar.delete_event(test_user, 'Event to delete'))
        assert result is True

        # Проверяем что событие удалено
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM events WHERE user_id = %s AND event_name = %s",
                [test_user, 'Event to delete']
            )
            event = cursor.fetchone()
            assert event is None

    def test_event_visibility_toggle(self, test_user, db):
        """Тест переключения видимости события"""
        from bot import Calendar

        calendar = Calendar()

        # Добавляем событие
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO events (user_id, event_name, event_date, is_public)
                VALUES (%s, 'Test Event', '2024-12-01', false)
                RETURNING id
            ''', [test_user])
            event_id = cursor.fetchone()[0]

        # Переключаем видимость
        result = asyncio.run(calendar.toggle_event_visibility(event_id, test_user))
        assert result is True

        # Проверяем что видимость изменилась
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_public FROM events WHERE id = %s",
                [event_id]
            )
            is_public = cursor.fetchone()[0]
            assert is_public is True