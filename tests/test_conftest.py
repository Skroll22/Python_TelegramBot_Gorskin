import os
import django
import pytest
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'calendarbot.settings')
django.setup()

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    """Включает доступ к БД для всех тестов"""
    pass

@pytest.fixture
def api_client():
    """Fixture для API клиента"""
    from rest_framework.test import APIClient
    return APIClient()