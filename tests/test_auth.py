import pytest
from django.db import connection
import asyncio

class TestAuth:
    """Тесты авторизации и аутентификации"""

    def test_user_authentication(self, db):
        """Тест аутентификации пользователя"""
        from bot import Calendar

        calendar = Calendar()

        # Добавляем пользователя с паролем
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, password)
                VALUES (%s, %s, %s)
            ''', (555555555, 'auth_user', 'secure_password'))

        # Проверяем аутентификацию
        result = asyncio.run(calendar.is_user_registered(555555555))
        assert result is True

        # Проверяем что пользователь без пароля не аутентифицирован
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, password)
                VALUES (%s, %s, %s)
            ''', (666666666, 'no_pass_user', None))

        result = asyncio.run(calendar.is_user_registered(666666666))
        assert result is False

    def test_api_authentication(self, api_client):
        """Тест аутентификации API"""
        # Тестируем endpoints без аутентификации
        response = api_client.get('/api/events/')
        assert response.status_code == 200

        response = api_client.get('/api/users/')
        # Если требует аутентификации - статус 403/401
        assert response.status_code in [200, 401, 403]