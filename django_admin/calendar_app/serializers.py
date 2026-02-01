from rest_framework import serializers
from .models import (
    TelegramUser, CalendarEvent, BotStatistics,
    UserInteraction, EventChangeLog, Meeting,
    MeetingParticipant, MeetingNotification
)
from django.utils import timezone
from datetime import datetime


class TelegramUserSerializer(serializers.ModelSerializer):
    """Сериализатор для пользователей Telegram"""
    events_count = serializers.IntegerField(read_only=True)
    meetings_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TelegramUser
        fields = [
            'telegram_id', 'username', 'first_name', 'last_name',
            'language_code', 'registered_at', 'last_seen',
            'events_count', 'meetings_count'
        ]
        read_only_fields = ['registered_at', 'last_seen']

    def get_events_count(self, obj):
        return obj.events.count()

    def get_meetings_count(self, obj):
        return obj.meetings.count() + obj.organized_meetings.count()


class CalendarEventSerializer(serializers.ModelSerializer):
    """Сериализатор для событий календаря"""
    user_details = TelegramUserSerializer(source='user', read_only=True)
    status = serializers.SerializerMethodField()
    days_until = serializers.SerializerMethodField()

    class Meta:
        model = CalendarEvent
        fields = [
            'id', 'user', 'user_details', 'date', 'title', 'description',
            'is_public', 'published_at', 'status', 'days_until',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'published_at']

    def get_status(self, obj):
        """Статус события: прошлое, сегодня, будущее"""
        today = timezone.now().date()
        if obj.date < today:
            return 'past'
        elif obj.date == today:
            return 'today'
        else:
            return 'future'

    def get_days_until(self, obj):
        """Количество дней до события"""
        today = timezone.now().date()
        if obj.date >= today:
            delta = obj.date - today
            return delta.days
        return None

    def validate_date(self, value):
        """Проверка даты события"""
        if value < timezone.now().date():
            raise serializers.ValidationError("Дата события не может быть в прошлом")
        return value

    def create(self, validated_data):
        """Создание события с автоматическим заполнением пользователя"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            # В реальном приложении здесь будет связь с аутентифицированным пользователем
            pass

        return super().create(validated_data)


class BotStatisticsSerializer(serializers.ModelSerializer):
    """Сериализатор для статистики бота"""
    commands_total = serializers.SerializerMethodField()
    events_total = serializers.SerializerMethodField()

    class Meta:
        model = BotStatistics
        fields = [
            'id', 'date', 'total_users', 'total_events',
            'daily_new_users', 'daily_active_users',
            'daily_created_events', 'daily_updated_events', 'daily_deleted_events',
            'daily_start_commands', 'daily_help_commands',
            'daily_list_commands', 'daily_today_commands', 'daily_stats_commands',
            'commands_total', 'events_total',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_commands_total(self, obj):
        """Общее количество команд за день"""
        return sum([
            obj.daily_start_commands,
            obj.daily_help_commands,
            obj.daily_list_commands,
            obj.daily_today_commands,
            obj.daily_stats_commands,
        ])

    def get_events_total(self, obj):
        """Общее количество действий с событиями за день"""
        return sum([
            obj.daily_created_events,
            obj.daily_updated_events,
            obj.daily_deleted_events,
        ])


class UserInteractionSerializer(serializers.ModelSerializer):
    """Сериализатор для взаимодействий пользователей"""
    user_details = TelegramUserSerializer(source='user', read_only=True)

    class Meta:
        model = UserInteraction
        fields = ['id', 'user', 'user_details', 'command', 'parameters', 'created_at']
        read_only_fields = ['created_at']


class EventChangeLogSerializer(serializers.ModelSerializer):
    """Сериализатор для логов изменений событий"""
    user_details = TelegramUserSerializer(source='user', read_only=True)
    event_details = CalendarEventSerializer(source='event', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = EventChangeLog
        fields = [
            'id', 'event', 'event_details', 'user', 'user_details',
            'action', 'action_display', 'old_data', 'new_data', 'created_at'
        ]
        read_only_fields = ['created_at']


class MeetingParticipantSerializer(serializers.ModelSerializer):
    """Сериализатор для участников встреч"""
    participant_details = TelegramUserSerializer(source='participant', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MeetingParticipant
        fields = [
            'id', 'meeting', 'participant', 'participant_details',
            'status', 'status_display', 'invited_at', 'responded_at'
        ]
        read_only_fields = ['invited_at', 'responded_at']


class MeetingSerializer(serializers.ModelSerializer):
    """Сериализатор для встреч"""
    organizer_details = TelegramUserSerializer(source='organizer', read_only=True)
    participants_details = MeetingParticipantSerializer(
        source='meeting_participants',
        many=True,
        read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration = serializers.SerializerMethodField()
    is_past = serializers.SerializerMethodField()
    is_upcoming = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            'id', 'title', 'description', 'date', 'start_time', 'end_time',
            'organizer', 'organizer_details', 'status', 'status_display',
            'participants_details', 'duration', 'is_past', 'is_upcoming',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_duration(self, obj):
        """Продолжительность встречи в часах"""
        return obj.duration()

    def get_is_past(self, obj):
        """Проверка, прошла ли встреча"""
        return obj.is_past()

    def get_is_upcoming(self, obj):
        """Проверка, предстоит ли встреча"""
        return obj.is_upcoming()

    def validate(self, data):
        """Валидация данных встречи"""
        # Проверяем, что время окончания позже времени начала
        if 'start_time' in data and 'end_time' in data:
            if data['start_time'] >= data['end_time']:
                raise serializers.ValidationError({
                    'end_time': 'Время окончания должно быть позже времени начала'
                })

        # Проверяем дату
        if 'date' in data and data['date'] < timezone.now().date():
            raise serializers.ValidationError({
                'date': 'Дата встречи не может быть в прошлом'
            })

        return data


class MeetingNotificationSerializer(serializers.ModelSerializer):
    """Сериализатор для уведомлений о встречах"""
    user_details = TelegramUserSerializer(source='user', read_only=True)
    meeting_details = MeetingSerializer(source='meeting', read_only=True)
    notification_type_display = serializers.CharField(
        source='get_notification_type_display',
        read_only=True
    )
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = MeetingNotification
        fields = [
            'id', 'meeting', 'meeting_details', 'user', 'user_details',
            'notification_type', 'notification_type_display',
            'message', 'sent_at', 'read_at', 'is_read'
        ]
        read_only_fields = ['sent_at', 'read_at']

    def get_is_read(self, obj):
        """Проверка, прочитано ли уведомление"""
        return obj.read_at is not None


# Сериализаторы для API отчетов и статистики
class UserStatsSerializer(serializers.Serializer):
    """Сериализатор для статистики пользователя"""
    telegram_id = serializers.IntegerField()
    username = serializers.CharField()
    total_events = serializers.IntegerField()
    total_meetings = serializers.IntegerField()
    public_events = serializers.IntegerField()
    last_active = serializers.DateTimeField()


class EventReportSerializer(serializers.Serializer):
    """Сериализатор для отчета по событиям"""
    date = serializers.DateField()
    total_events = serializers.IntegerField()
    public_events = serializers.IntegerField()
    new_users = serializers.IntegerField()
    active_users = serializers.IntegerField()


class MeetingReportSerializer(serializers.Serializer):
    """Сериализатор для отчета по встречам"""
    date = serializers.DateField()
    total_meetings = serializers.IntegerField()
    confirmed_meetings = serializers.IntegerField()
    pending_meetings = serializers.IntegerField()
    avg_participants = serializers.FloatField()