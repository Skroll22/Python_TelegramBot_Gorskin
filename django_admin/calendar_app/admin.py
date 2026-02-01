# django_admin/calendar_app/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json
from .models import TelegramUser, CalendarEvent, BotStatistics, UserInteraction, EventChangeLog, Meeting, MeetingParticipant, MeetingNotification


class EventDateFilter(admin.SimpleListFilter):
    """Фильтр событий по дате"""
    title = 'Дата события'
    parameter_name = 'event_date'

    def lookups(self, request, model_admin):
        return (
            ('past', 'Прошедшие'),
            ('today', 'Сегодня'),
            ('future', 'Будущие'),
        )

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == 'past':
            return queryset.filter(date__lt=today)
        if self.value() == 'today':
            return queryset.filter(date=today)
        if self.value() == 'future':
            return queryset.filter(date__gt=today)


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'date', 'is_public_display', 'is_today', 'is_future', 'created_at']
    list_filter = [EventDateFilter, 'date', 'created_at', 'user', 'is_public']
    search_fields = ['title', 'description', 'user__username', 'user__first_name']
    readonly_fields = ['created_at', 'updated_at', 'published_at']
    date_hierarchy = 'date'
    list_per_page = 20

    fieldsets = (
        ('Основная информация', {
            'fields': ('user', 'date', 'title', 'description')
        }),
        ('Настройки приватности', {
            'fields': ('is_public', 'published_at')
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def is_public_display(self, obj):
        """Отображение статуса публичности с иконкой"""
        if obj.is_public:
            return "🔓 Публичное"
        return "🔒 Приватное"

    is_public_display.short_description = "Статус"

    actions = ['export_as_json', 'export_as_csv']

    def export_as_json(self, request, queryset):
        """Экспорт выбранных событий в JSON"""
        import json
        from django.http import HttpResponse

        data = []
        for event in queryset:
            data.append({
                'id': event.id,
                'user': str(event.user),
                'title': event.title,
                'description': event.description,
                'date': event.date.strftime('%Y-%m-%d'),
                'is_public': event.is_public,
                'created_at': event.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })

        response = HttpResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = 'attachment; filename="events_export.json"'
        return response

    export_as_json.short_description = "Экспортировать в JSON"

    def export_as_csv(self, request, queryset):
        """Экспорт выбранных событий в CSV"""
        import csv
        from django.http import HttpResponse
        import io

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')

        # Заголовок
        writer.writerow(['ID', 'Пользователь', 'Название', 'Описание', 'Дата', 'Публичное', 'Создано'])

        # Данные
        for event in queryset:
            writer.writerow([
                event.id,
                str(event.user),
                event.title,
                event.description or '',
                event.date.strftime('%Y-%m-%d'),
                'Да' if event.is_public else 'Нет',
                event.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="events_export.csv"'
        return response

    export_as_csv.short_description = "Экспортировать в CSV"


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ['telegram_id', 'username', 'first_name', 'last_name',
                    'events_count', 'registered_at', 'last_seen', 'activity_level']
    list_filter = ['registered_at', 'last_seen']
    search_fields = ['telegram_id', 'username', 'first_name', 'last_name']
    readonly_fields = ['registered_at', 'last_seen']
    list_per_page = 20

    fieldsets = (
        ('Основная информация', {
            'fields': ('telegram_id', 'username', 'first_name', 'last_name', 'language_code')
        }),
        ('Системная информация', {
            'fields': ('registered_at', 'last_seen'),
            'classes': ('collapse',)
        }),
    )

    def activity_level(self, obj):
        """Уровень активности пользователя"""
        events_count = obj.events_count()
        if events_count > 10:
            return '🔥 Высокая'
        elif events_count > 3:
            return '⚡ Средняя'
        else:
            return '💤 Низкая'

    activity_level.short_description = 'Активность'


@admin.register(BotStatistics)
class BotStatisticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_users', 'total_events', 'daily_new_users',
                    'daily_active_users', 'daily_created_events', 'commands_summary']
    list_filter = ['date']
    readonly_fields = ['created_at', 'updated_at', 'total_users', 'total_events',
                       'user_activity_data_display', 'event_type_data_display',
                       'daily_summary_display']
    date_hierarchy = 'date'
    actions = ['update_statistics']

    fieldsets = (
        ('Основная статистика', {
            'fields': ('date', 'total_users', 'total_events')
        }),
        ('Ежедневная активность', {
            'fields': ('daily_new_users', 'daily_active_users',
                       'daily_created_events', 'daily_updated_events',
                       'daily_deleted_events')
        }),
        ('Команды за день', {
            'fields': ('daily_start_commands', 'daily_help_commands',
                       'daily_list_commands', 'daily_today_commands',
                       'daily_stats_commands')
        }),
        ('Детальная статистика', {
            'fields': ('user_activity_data_display', 'event_type_data_display',
                       'daily_summary_display'),
            'classes': ('collapse',)
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def commands_summary(self, obj):
        """Сводка по командам"""
        total = sum([
            obj.daily_start_commands,
            obj.daily_help_commands,
            obj.daily_list_commands,
            obj.daily_today_commands,
            obj.daily_stats_commands,
        ])
        return f"{total} команд"

    commands_summary.short_description = 'Команды за день'

    def user_activity_data_display(self, obj):
        """Отображение данных активности пользователей"""
        data = obj.user_activity_data or {}

        html = "<h3>Активность по часам:</h3>"
        html += "<table style='border-collapse: collapse;'>"
        html += "<tr><th style='border: 1px solid #ccc; padding: 5px;'>Час</th><th style='border: 1px solid #ccc; padding: 5px;'>Событий</th></tr>"

        hour_distribution = data.get('hour_distribution', {})
        for hour in range(24):
            count = hour_distribution.get(str(hour), 0)
            html += f"<tr><td style='border: 1px solid #ccc; padding: 5px;'>{hour}:00</td><td style='border: 1px solid #ccc; padding: 5px;'>{count}</td></tr>"

        html += "</table>"

        # Топ пользователей
        html += "<h3>Топ пользователей за сегодня:</h3>"
        top_users = data.get('top_users_today', [])
        if top_users:
            html += "<table style='border-collapse: collapse;'>"
            html += "<tr><th style='border: 1px solid #ccc; padding: 5px;'>Пользователь</th><th style='border: 1px solid #ccc; padding: 5px;'>Событий</th></tr>"
            for user in top_users:
                html += f"<tr><td style='border: 1px solid #ccc; padding: 5px;'>{user['username']}</td><td style='border: 1px solid #ccc; padding: 5px;'>{user['event_count']}</td></tr>"
            html += "</table>"
        else:
            html += "<p>Нет данных</p>"

        return format_html(html)

    user_activity_data_display.short_description = 'Данные активности'

    def event_type_data_display(self, obj):
        """Отображение данных по типам событий"""
        data = obj.user_activity_data or {}
        categories = data.get('event_categories', {})

        html = "<h3>Распределение событий по категориям:</h3>"
        html += "<table style='border-collapse: collapse;'>"
        html += "<tr><th style='border: 1px solid #ccc; padding: 5px;'>Категория</th><th style='border: 1px solid #ccc; padding: 5px;'>Количество</th></tr>"

        for category, count in categories.items():
            html += f"<tr><td style='border: 1px solid #ccc; padding: 5px;'>{category}</td><td style='border: 1px solid #ccc; padding: 5px;'>{count}</td></tr>"

        html += "</table>"
        return format_html(html)

    event_type_data_display.short_description = 'Типы событий'

    def daily_summary_display(self, obj):
        """Отображение сводки за день"""
        summary = obj.get_daily_summary()

        html = "<h3>Сводка за день:</h3>"
        html += f"<p><strong>Дата:</strong> {summary['date']}</p>"
        html += f"<p><strong>Новых пользователей:</strong> {summary['new_users']}</p>"
        html += f"<p><strong>Активных пользователей:</strong> {summary['active_users']}</p>"
        html += f"<p><strong>Созданных событий:</strong> {summary['created_events']}</p>"
        html += f"<p><strong>Обновленных событий:</strong> {summary['updated_events']}</p>"
        html += f"<p><strong>Удаленных событий:</strong> {summary['deleted_events']}</p>"
        html += f"<p><strong>Всего команд:</strong> {summary['total_commands']}</p>"

        return format_html(html)

    daily_summary_display.short_description = 'Сводка за день'

    def update_statistics(self, request, queryset):
        """Действие для обновления статистики"""
        for stats in queryset:
            stats.update_daily_stats()
            stats.save()

        self.message_user(request, f"Статистика обновлена для {queryset.count()} записей")

    update_statistics.short_description = "Обновить статистику"


@admin.register(UserInteraction)
class UserInteractionAdmin(admin.ModelAdmin):
    list_display = ['user', 'command', 'created_at', 'parameters_display']
    list_filter = ['command', 'created_at', 'user']
    search_fields = ['user__username', 'user__first_name', 'command']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'

    def parameters_display(self, obj):
        """Отображение параметров"""
        if obj.parameters:
            return str(obj.parameters)
        return "-"

    parameters_display.short_description = 'Параметры'


@admin.register(EventChangeLog)
class EventChangeLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'event', 'created_at']
    list_filter = ['action', 'created_at', 'user']
    search_fields = ['user__username', 'user__first_name', 'event__title']
    readonly_fields = ['created_at', 'old_data_display', 'new_data_display']

    def old_data_display(self, obj):
        """Отображение старых данных"""
        if obj.old_data:
            return format_json(obj.old_data)
        return "-"

    old_data_display.short_description = 'Старые данные'

    def new_data_display(self, obj):
        """Отображение новых данных"""
        if obj.new_data:
            return format_json(obj.new_data)
        return "-"

    new_data_display.short_description = 'Новые данные'


class MeetingParticipantInline(admin.TabularInline):
    """Inline для участников встречи"""
    model = MeetingParticipant
    extra = 1
    readonly_fields = ['invited_at', 'responded_at']
    fields = ['participant', 'status', 'invited_at', 'responded_at']


class MeetingNotificationInline(admin.TabularInline):
    """Inline для уведомлений о встрече"""
    model = MeetingNotification
    extra = 0
    readonly_fields = ['sent_at', 'read_at']
    fields = ['user', 'notification_type', 'message', 'sent_at', 'read_at']
    can_delete = False


class MeetingStatusFilter(admin.SimpleListFilter):
    """Фильтр встреч по статусу"""
    title = 'Статус встречи'
    parameter_name = 'meeting_status'

    def lookups(self, request, model_admin):
        return [
            ('pending', 'Ожидает подтверждения'),
            ('confirmed', 'Подтверждена'),
            ('cancelled', 'Отменена'),
            ('declined', 'Отклонена'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ['title', 'date', 'start_time', 'end_time', 'organizer',
                    'status_display', 'participants_count', 'is_past_display']
    list_filter = [MeetingStatusFilter, 'date', 'created_at']
    search_fields = ['title', 'description', 'organizer__username', 'organizer__first_name']
    readonly_fields = ['created_at', 'updated_at', 'duration_display']
    date_hierarchy = 'date'
    list_per_page = 20

    inlines = [MeetingParticipantInline, MeetingNotificationInline]

    fieldsets = (
        ('Основная информация', {
            'fields': ('title', 'description', 'date', 'start_time', 'end_time', 'organizer', 'status')
        }),
        ('Статистика', {
            'fields': ('duration_display', 'participants_count_display'),
            'classes': ('collapse',)
        }),
        ('Системная информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def status_display(self, obj):
        """Отображение статуса с иконкой"""
        status_icons = {
            'pending': '🟡',
            'confirmed': '🟢',
            'cancelled': '🔴',
            'declined': '⚫',
        }
        icon = status_icons.get(obj.status, '⚪')
        return f"{icon} {obj.get_status_display()}"

    status_display.short_description = 'Статус'

    def participants_count(self, obj):
        """Количество участников"""
        return obj.participants.count()

    participants_count.short_description = 'Участники'

    def participants_count_display(self, obj):
        """Отображение количества участников по статусам"""
        confirmed = obj.get_confirmed_participants().count()
        pending = obj.get_pending_participants().count()
        declined = obj.get_declined_participants().count()
        return f"Всего: {obj.participants.count()} (✅{confirmed} ⏳{pending} ❌{declined})"

    participants_count_display.short_description = 'Статистика участников'

    def duration_display(self, obj):
        """Отображение продолжительности"""
        return f"{obj.duration():.1f} часов"

    duration_display.short_description = 'Продолжительность'

    def is_past_display(self, obj):
        """Отображение статуса встречи (прошла/предстоит)"""
        if obj.is_past():
            return "🔴 Прошла"
        elif obj.is_upcoming():
            return "🟢 Предстоит"
        else:
            return "🟡 Сейчас"

    is_past_display.short_description = 'Время встречи'

    def get_queryset(self, request):
        """Оптимизация запросов"""
        queryset = super().get_queryset(request)
        return queryset.select_related('organizer').prefetch_related('participants')


@admin.register(MeetingParticipant)
class MeetingParticipantAdmin(admin.ModelAdmin):
    list_display = ['meeting', 'participant', 'status_display', 'invited_at', 'responded_at']
    list_filter = ['status', 'invited_at', 'meeting__date']
    search_fields = ['participant__username', 'participant__first_name', 'meeting__title']
    readonly_fields = ['invited_at', 'responded_at']

    def status_display(self, obj):
        """Отображение статуса с иконкой"""
        status_icons = {
            'pending': '🟡',
            'confirmed': '🟢',
            'declined': '🔴',
        }
        icon = status_icons.get(obj.status, '⚪')
        return f"{icon} {obj.get_status_display()}"

    status_display.short_description = 'Статус'


@admin.register(MeetingNotification)
class MeetingNotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'meeting', 'notification_type_display', 'sent_at', 'read_at_display']
    list_filter = ['notification_type', 'sent_at', 'meeting__date']
    search_fields = ['user__username', 'user__first_name', 'meeting__title', 'message']
    readonly_fields = ['sent_at', 'read_at']

    def notification_type_display(self, obj):
        """Отображение типа уведомления"""
        icons = {
            'invitation': '📨',
            'confirmation': '✅',
            'cancellation': '❌',
            'reminder': '⏰',
            'update': '🔄',
        }
        icon = icons.get(obj.notification_type, '📧')
        return f"{icon} {obj.get_notification_type_display()}"

    notification_type_display.short_description = 'Тип уведомления'

    def read_at_display(self, obj):
        """Отображение статуса прочтения"""
        if obj.read_at:
            return f"✅ {obj.read_at.strftime('%d.%m.%Y %H:%M')}"
        return "⏳ Не прочитано"

    read_at_display.short_description = 'Статус прочтения'


def format_json(data):
    """Форматирование JSON для отображения"""
    if not data:
        return "-"

    html = "<div style='background-color: #f5f5f5; padding: 10px; border-radius: 5px;'>"
    html += f"<pre style='margin: 0;'>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>"
    html += "</div>"
    return format_html(html)


# Кастомизация админ-панели
admin.site.site_header = "📊 Администрирование Telegram Календаря"
admin.site.site_title = "Telegram Календарь - Статистика"
admin.site.index_title = "📈 Статистика и управление"