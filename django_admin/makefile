.PHONY: help test test-unit test-integration test-e2e coverage clean

help:
	@echo "Доступные команды:"
	@echo "  test           - Запустить все тесты"
	@echo "  test-unit      - Запустить unit тесты"
	@echo "  test-integration - Запустить интеграционные тесты"
	@echo "  test-e2e       - Запустить end-to-end тесты"
	@echo "  test-bot       - Запустить тесты бота"
	@echo "  test-api       - Запустить тесты API"
	@echo "  coverage       - Запустить тесты с покрытием"
	@echo "  clean          - Очистить временные файлы"

test:
	@pytest -v

test-unit:
	@pytest -m unit -v

test-integration:
	@pytest -m integration -v

test-e2e:
	@pytest -m e2e -v

test-bot:
	@pytest -m bot -v

test-api:
	@pytest -m api -v

coverage:
	@pytest --cov=calendar_app --cov-report=term-missing --cov-report=html:coverage_html --cov-report=xml:coverage.xml -v

clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@rm -rf coverage_html coverage.xml test-results.xml .pytest_cache .coverage htmlcov 2>/dev/null || true