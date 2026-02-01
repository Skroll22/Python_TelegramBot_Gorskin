#!/bin/bash

echo "🐍 Запуск тестов Python проекта..."

# Активируем виртуальное окружение
if [ -d "venv_django" ]; then
    source venv_django/bin/activate
fi

# Устанавливаем зависимости для тестирования
echo "📦 Установка зависимостей для тестирования..."
pip install -r requirements.txt

# Запускаем миграции
echo "🔄 Применение миграций..."
python manage.py migrate

# Запускаем тесты
echo "🚀 Запуск тестов..."
pytest \
    --cov=calendar_app \
    --cov-report=term-missing \
    --cov-report=html:coverage_html \
    --cov-report=xml:coverage.xml \
    --junitxml=test-results.xml \
    -v

# Проверяем покрытие
echo "📊 Проверка покрытия кода..."
if [ -f "coverage.xml" ]; then
    COVERAGE=$(grep -o 'line-rate="[0-9.]*"' coverage.xml | cut -d'"' -f2)
    echo "✅ Покрытие кода: $(echo "scale=2; $COVERAGE * 100" | bc)%"
fi

echo "✅ Тестирование завершено!"