import pytest
from unittest.mock import Mock, patch, AsyncMock
from telegram import Update, Message, Chat, User
from telegram.ext import CallbackContext
import asyncio


class TestTelegramAPI:
    """Тесты интеграции с Telegram API"""

    @pytest.fixture
    def mock_update(self):
        """Fixture для мока Update"""
        user = User(123456789, 'test_user', False)
        chat = Chat(123456789, 'private')
        message = Message(1, None, chat, from_user=user, text='/start')
        return Update(update_id=1, message=message)

    @pytest.fixture
    def mock_context(self):
        """Fixture для мока Context"""
        context = Mock(spec=CallbackContext)
        context.bot_data = {'calendar': Mock()}
        return context

    @pytest.mark.asyncio
    async def test_start_command(self, mock_update, mock_context):
        """Тест команды /start"""
        from bot import start

        with patch('bot.Calendar') as mock_calendar:
            mock_calendar_instance = mock_calendar.return_value
            mock_calendar_instance.user_states = {}

            await start(mock_update, mock_context)

            # Проверяем что бот отправил сообщение
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args[0][0]
            assert 'Привет! Я календарный бот' in call_args

    @pytest.mark.asyncio
    async def test_register_user(self, mock_update, mock_context):
        """Тест регистрации пользователя"""
        from bot import register

        mock_update.message.text = '/register'
        mock_context.user_data = {}

        with patch('bot.Calendar') as mock_calendar:
            mock_calendar_instance = mock_calendar.return_value
            mock_calendar_instance.is_user_registered.return_value = False

            result = await register(mock_update, mock_context)

            mock_update.message.reply_text.assert_called_with('Придумайте пароль:')
            assert result.name == 'REGISTER'