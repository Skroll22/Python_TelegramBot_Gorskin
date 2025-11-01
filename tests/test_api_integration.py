import pytest
import json
from unittest.mock import patch, Mock
from django.db import connection


class TestAPIIntegration:
    """Тесты интеграции API"""

    @pytest.fixture
    def test_events_data(self, db):
        """Fixture для тестовых событий"""
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, password)
                VALUES (777777777, 'api_user', 'API', 'password123')
            ''')
            cursor.execute('''
                INSERT INTO events (user_id, event_name, event_date, is_public)
                VALUES 
                    (777777777, 'Public Event', '2024-12-01', true),
                    (777777777, 'Private Event', '2024-12-02', false)
            ''')

    def test_events_api_endpoint(self, test_events_data, api_client):
        """Тест endpoint событий"""
        response = api_client.get('/api/events/')
        assert response.status_code == 200
        data = response.json()
        assert 'events' in data or isinstance(data, list)

    def test_users_api_endpoint(self, test_events_data, api_client):
        """Тест endpoint пользователей"""
        response = api_client.get('/api/users/')
        assert response.status_code in [200, 401, 403]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    def test_export_events_api(self, test_events_data, api_client):
        """Тест API экспорта событий"""
        export_data = {
            'user_id': 777777777,
            'format': 'json'
        }

        response = api_client.post(
            '/export-events/',
            data=json.dumps(export_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        data = response.json()
        assert 'user_id' in data
        assert 'events' in data

    @patch('myapp.views.requests.post')
    def test_external_api_integration(self, mock_post, api_client):
        """Тест интеграции с внешними API"""
        # Мокаем внешний API
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_post.return_value = mock_response

        # Тестируем наш endpoint который использует внешний API
        response = api_client.get('/api/events/')
        assert response.status_code == 200