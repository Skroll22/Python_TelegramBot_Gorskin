import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta


class TestNotifications:
    """Тесты системы уведомлений"""

    @pytest.mark.asyncio
    async def test_meeting_notifications(self):
        """Тест уведомлений о встречах"""
        from bot import Calendar

        calendar = Calendar()

        with patch('bot.Calendar.create_meeting') as mock_create:
            mock_create.return_value = 123

            with patch('bot.Application.bot.send_message') as mock_send:
                mock_send.return_value = None

                # Создаем встречу (это должно отправить уведомления)
                meeting_data = {
                    'title': 'Test Meeting',
                    'description': 'Test Description',
                    'meeting_date': datetime.now().date(),
                    'meeting_time': datetime.now().time(),
                    'duration': 60,
                    'organizer': 111111111,
                    'participants': [222222222, 333333333]
                }

                meeting_id = await calendar.create_meeting(**meeting_data)

                # Проверяем что уведомления отправлены
                assert mock_send.call_count == 2  # Два участника

    @pytest.mark.asyncio
    async def test_event_reminders(self):
        """Тест напоминаний о событиях"""
        from bot import Calendar

        calendar = Calendar()

        # Мокаем проверку событий для напоминаний
        with patch('bot.Calendar.get_events') as mock_events:
            mock_events.return_value = [
                ('Urgent Event', '29.10.2024'),
                ('Regular Event', '30.10.2024')
            ]

            with patch('bot.Application.bot.send_message') as mock_send:
                # Здесь можно тестировать логику напоминаний
                # (нужно добавить соответствующую функцию в боте)
                pass