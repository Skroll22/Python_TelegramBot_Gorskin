#!/bin/bash

echo "🐳 Запуск тестов в Docker..."

# Собираем и запускаем контейнеры
docker-compose -f docker-compose.dev.yml up --build test

# Копируем отчеты из контейнера
docker cp $(docker-compose -f docker-compose.dev.yml ps -q test):/app/coverage.xml ./coverage.xml 2>/dev/null || true
docker cp $(docker-compose -f docker-compose.dev.yml ps -q test):/app/coverage_html ./coverage_html 2>/dev/null || true

echo "✅ Тесты в Docker завершены!"