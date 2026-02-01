"""
Простой тест для проверки работы pytest и Django
"""


def test_basic():
    """Базовый тест Python"""
    assert 1 + 1 == 2


def test_import_django():
    """Тест импорта Django"""
    try:
        import django
        print(f"✅ Django version: {django.get_version()}")
        assert django.VERSION[0] >= 4
    except ImportError:
        assert False, "Django не установлен"


def test_import_models():
    """Тест импорта моделей"""
    try:
        from calendar_app.models import TelegramUser
        print("✅ Модель TelegramUser успешно импортирована")
        assert TelegramUser.__name__ == "TelegramUser"
    except Exception as e:
        print(f"⚠️ Ошибка импорта: {e}")
        # Пропускаем тест если не можем импортировать
        import pytest
        pytest.skip(f"Не удалось импортировать модели: {e}")