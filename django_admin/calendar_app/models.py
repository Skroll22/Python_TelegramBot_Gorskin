from django.db import models
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Sum, Count, Q
import json
from datetime import datetime


class TelegramUser(models.Model):
    """Модель для пользователей Telegram"""
    telegram_id = models.BigIntegerField(unique=True, verbose_name="ID в Telegram")
    username = models.CharField(max_length=255, null=True, blank=True, verbose_name="Username")
    first_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="Имя")
    last_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="Фамилия")
    language_code = models.CharField(max_length=10, null=True, blank=True, verbose_name="Язык")
    registered_at = models.DateTimeField(default=timezone.now, verbose_name="Дата регистрации")
    last_seen = models.DateTimeField(auto_now=True, verbose_name="Последний визит")

    class Meta:
        verbose_name = "Пользователь Telegram"
        verbose_name_plural = "Пользователи Telegram"
        ordering = ['-registered_at']

    def __str__(self):
        if self.username:
            return f"@{self.username} ({self.telegram_id})"
        elif self.first_name:
            return f"{self.first_name} {self.last_name or ''} ({self.telegram_id})"
        return str(self.telegram_id)

    def events_count(self):
        return self.events.count()

    events_count.short_description = "Количество событий"

    def active_days(self):
        """Количество дней с активностью"""
        from django.db.models import Count
        from django.db.models.functions import TruncDate

        active_dates = self.events.annotate(
            date_only=TruncDate('created_at')
        ).values('date_only').distinct().count()
        return active_dates


class CalendarEvent(models.Model):
    """Модель для событий календаря"""
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name="Пользователь"
    )
    date = models.DateField(verbose_name="Дата события")
    title = models.CharField(max_length=255, verbose_name="Название")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    is_public = models.BooleanField(
        default=False,
        verbose_name="Публичное событие",
        help_text="Доступно ли событие другим пользователям"
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата публикации"
    )

    class Meta:
        verbose_name = "Событие календаря"
        verbose_name_plural = "События календаря"
        ordering = ['date', 'created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['is_public']),
        ]

    def __str__(self):
        return f"{self.date}: {self.title}"

    def is_past(self):
        return self.date < timezone.now().date()

    is_past.boolean = True
    is_past.short_description = "Прошедшее"

    def is_today(self):
        return self.date == timezone.now().date()

    is_today.boolean = True
    is_today.short_description = "Сегодня"

    def is_future(self):
        return self.date > timezone.now().date()

    is_future.boolean = True
    is_future.short_description = "Будущее"


class BotStatistics(models.Model):
    """Модель для хранения статистики бота"""
    date = models.DateField(unique=True, default=timezone.now, verbose_name="Дата")

    # Общая статистика
    total_users = models.PositiveIntegerField(default=0, verbose_name="Всего пользователей")
    total_events = models.PositiveIntegerField(default=0, verbose_name="Всего событий")

    # Ежедневная статистика
    daily_new_users = models.PositiveIntegerField(default=0, verbose_name="Новых пользователей за день")
    daily_active_users = models.PositiveIntegerField(default=0, verbose_name="Активных пользователей за день")
    daily_created_events = models.PositiveIntegerField(default=0, verbose_name="Созданных событий за день")
    daily_updated_events = models.PositiveIntegerField(default=0, verbose_name="Обновленных событий за день")
    daily_deleted_events = models.PositiveIntegerField(default=0, verbose_name="Удаленных событий за день")

    # Команды
    daily_start_commands = models.PositiveIntegerField(default=0, verbose_name="Команд /start за день")
    daily_help_commands = models.PositiveIntegerField(default=0, verbose_name="Команд /help за день")
    daily_list_commands = models.PositiveIntegerField(default=0, verbose_name="Команд /list за день")
    daily_today_commands = models.PositiveIntegerField(default=0, verbose_name="Команд /today за день")
    daily_stats_commands = models.PositiveIntegerField(default=0, verbose_name="Команд /stats за день")

    # Хранение детальной статистики в JSON
    user_activity_data = models.JSONField(default=dict, verbose_name="Данные активности пользователей")
    event_type_data = models.JSONField(default=dict, verbose_name="Данные по типам событий")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Статистика бота"
        verbose_name_plural = "Статистика бота"
        ordering = ['-date']

    def __str__(self):
        return f"Статистика за {self.date.strftime('%d.%m.%Y')}"

    def save(self, *args, **kwargs):
        # Автоматически обновляем общую статистику при сохранении
        self.total_users = TelegramUser.objects.count()
        self.total_events = CalendarEvent.objects.count()

        # Обновляем JSON данные
        self.update_json_data()

        super().save(*args, **kwargs)

    def update_json_data(self):
        """Обновление JSON данных статистики"""
        from django.db.models.functions import TruncDate

        # Активность пользователей по часам
        today = timezone.now().date()
        today_events = CalendarEvent.objects.filter(created_at__date=today)

        hour_distribution = {}
        for hour in range(24):
            hour_events = today_events.filter(created_at__hour=hour).count()
            hour_distribution[str(hour)] = hour_events

        self.user_activity_data = {
            'hour_distribution': hour_distribution,
            'top_users_today': self.get_top_users_today(),
            'event_categories': self.get_event_categories(),
        }

    def get_top_users_today(self):
        """Топ пользователей по активности за сегодня"""
        today = timezone.now().date()
        top_users = TelegramUser.objects.filter(
            events__created_at__date=today
        ).annotate(
            event_count=Count('events')
        ).order_by('-event_count')[:10]

        return [
            {
                'user_id': user.telegram_id,
                'username': user.username or f"User{user.telegram_id}",
                'event_count': user.event_count
            }
            for user in top_users
        ]

    def get_event_categories(self):
        """Категоризация событий по названию"""
        # Простая категоризация по ключевым словам
        categories = {
            'встреча': 0,
            'день рождения': 0,
            'дедлайн': 0,
            'задача': 0,
            'праздник': 0,
            'напоминание': 0,
            'другое': 0
        }

        keywords_mapping = {
            'встреча': ['встреча', 'meeting', 'совещание', 'конференция'],
            'день рождения': ['др', 'birthday', 'день рождения'],
            'дедлайн': ['дедлайн', 'deadline', 'срок', 'завершение'],
            'задача': ['задача', 'task', 'todo', 'делать'],
            'праздник': ['праздник', 'holiday', 'отпуск', 'выходной'],
            'напоминание': ['напоминание', 'reminder', 'напомнить'],
        }

        events = CalendarEvent.objects.all()

        for event in events:
            title_lower = event.title.lower()
            categorized = False

            for category, keywords in keywords_mapping.items():
                if any(keyword in title_lower for keyword in keywords):
                    categories[category] += 1
                    categorized = True
                    break

            if not categorized:
                categories['другое'] += 1

        return categories

    @classmethod
    def get_today_statistics(cls):
        """Получить или создать статистику на сегодня"""
        today = timezone.now().date()
        stats, created = cls.objects.get_or_create(date=today)
        return stats

    def update_daily_stats(self):
        """Обновить ежедневную статистику"""
        today = timezone.now().date()
        yesterday = today - timezone.timedelta(days=1)

        # Активные пользователи за сегодня
        active_users_today = TelegramUser.objects.filter(
            Q(events__created_at__date=today) |
            Q(last_seen__date=today)
        ).distinct().count()
        self.daily_active_users = active_users_today

        # Новые пользователи за сегодня
        new_users_today = TelegramUser.objects.filter(
            registered_at__date=today
        ).count()
        self.daily_new_users = new_users_today

        # События за сегодня
        created_today = CalendarEvent.objects.filter(
            created_at__date=today
        ).count()
        self.daily_created_events = created_today

        # Обновленные события за сегодня
        updated_today = CalendarEvent.objects.filter(
            updated_at__date=today,
            created_at__date__lt=today
        ).count()
        self.daily_updated_events = updated_today

        self.save()

    def get_daily_summary(self):
        """Получить сводку за день"""
        return {
            'date': self.date.strftime('%d.%m.%Y'),
            'new_users': self.daily_new_users,
            'active_users': self.daily_active_users,
            'created_events': self.daily_created_events,
            'updated_events': self.daily_updated_events,
            'deleted_events': self.daily_deleted_events,
            'total_commands': sum([
                self.daily_start_commands,
                self.daily_help_commands,
                self.daily_list_commands,
                self.daily_today_commands,
                self.daily_stats_commands,
            ])
        }

    def update_command_stat(self, command):
        """Обновить статистику команд"""
        if command == '/start':
            self.daily_start_commands += 1
        elif command == '/help':
            self.daily_help_commands += 1
        elif command == '/list':
            self.daily_list_commands += 1
        elif command == '/today':
            self.daily_today_commands += 1
        elif command == '/stats':
            self.daily_stats_commands += 1
        self.save()

    def update_event_stat(self, action):
        """Обновить статистику событий"""
        if action == 'create':
            self.daily_created_events += 1
        elif action == 'update':
            self.daily_updated_events += 1
        elif action == 'delete':
            self.daily_deleted_events += 1
        self.save()


class UserInteraction(models.Model):
    """Модель для отслеживания взаимодействий пользователей"""
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='interactions',
        verbose_name="Пользователь"
    )
    command = models.CharField(max_length=50, verbose_name="Команда")
    parameters = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время взаимодействия")

    class Meta:
        verbose_name = "Взаимодействие пользователя"
        verbose_name_plural = "Взаимодействия пользователей"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'command']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.user} - {self.command} - {self.created_at.strftime('%H:%M')}"

    @classmethod
    def log_interaction(cls, telegram_id, command, **kwargs):
        """Запись взаимодействия пользователя"""
        try:
            user = TelegramUser.objects.get(telegram_id=telegram_id)
            interaction = cls.objects.create(
                user=user,
                command=command,
                parameters=kwargs
            )

            # Обновляем статистику
            stats = BotStatistics.get_today_statistics()
            stats.update_command_stat(command)
            stats.update_daily_stats()

            return interaction
        except TelegramUser.DoesNotExist:
            return None


class EventChangeLog(models.Model):
    """Лог изменений событий"""
    ACTION_CHOICES = [
        ('create', 'Создание'),
        ('update', 'Обновление'),
        ('delete', 'Удаление'),
    ]

    event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name='change_logs',
        verbose_name="Событие",
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='event_changes',
        verbose_name="Пользователь"
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, verbose_name="Действие")
    old_data = models.JSONField(default=dict, blank=True, verbose_name="Старые данные")
    new_data = models.JSONField(default=dict, blank=True, verbose_name="Новые данные")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время изменения")

    class Meta:
        verbose_name = "Лог изменения события"
        verbose_name_plural = "Логи изменений событий"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.get_action_display()} - {self.created_at.strftime('%H:%M')}"

    @classmethod
    def log_change(cls, telegram_id, action, event_id=None, old_data=None, new_data=None):
        """Запись изменения события"""
        try:
            user = TelegramUser.objects.get(telegram_id=telegram_id)
            event = CalendarEvent.objects.get(id=event_id) if event_id else None

            log = cls.objects.create(
                event=event,
                user=user,
                action=action,
                old_data=old_data or {},
                new_data=new_data or {}
            )

            # Обновляем статистику
            stats = BotStatistics.get_today_statistics()
            stats.update_event_stat(action)
            stats.update_daily_stats()

            return log
        except (TelegramUser.DoesNotExist, CalendarEvent.DoesNotExist):
            return None


class Meeting(models.Model):
    """Модель для встреч между пользователями"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('confirmed', 'Подтверждена'),
        ('cancelled', 'Отменена'),
        ('declined', 'Отклонена'),
    ]

    title = models.CharField(max_length=255, verbose_name="Название встречи")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    date = models.DateField(verbose_name="Дата встречи")
    start_time = models.TimeField(verbose_name="Время начала")
    end_time = models.TimeField(verbose_name="Время окончания")

    organizer = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='organized_meetings',
        verbose_name="Организатор"
    )

    participants = models.ManyToManyField(
        TelegramUser,
        related_name='meetings',
        through='MeetingParticipant',
        verbose_name="Участники"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Статус"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлена")

    class Meta:
        verbose_name = "Встреча"
        verbose_name_plural = "Встречи"
        ordering = ['date', 'start_time']
        indexes = [
            models.Index(fields=['date', 'status']),
            models.Index(fields=['organizer', 'status']),
        ]

    def __str__(self):
        return f"{self.date} {self.start_time} - {self.title}"

    def duration(self):
        """Продолжительность встречи в часах"""
        from datetime import datetime
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        duration = end - start
        return duration.total_seconds() / 3600

    def is_past(self):
        """Проверка, прошла ли встреча"""
        from django.utils import timezone
        from datetime import datetime
        now = timezone.now()
        meeting_datetime = datetime.combine(self.date, self.end_time)
        meeting_datetime = timezone.make_aware(meeting_datetime, timezone.get_current_timezone())
        return meeting_datetime < now

    def is_upcoming(self):
        """Проверка, предстоит ли встреча"""
        from django.utils import timezone
        from datetime import datetime
        now = timezone.now()
        meeting_datetime = datetime.combine(self.date, self.start_time)
        meeting_datetime = timezone.make_aware(meeting_datetime, timezone.get_current_timezone())
        return meeting_datetime > now

    def is_now(self):
        """Проверка, идет ли встреча сейчас"""
        from django.utils import timezone
        from datetime import datetime
        now = timezone.now()
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        start = timezone.make_aware(start, timezone.get_current_timezone())
        end = timezone.make_aware(end, timezone.get_current_timezone())
        return start <= now <= end

    def get_confirmed_participants(self):
        """Получить подтвердивших участников"""
        return self.meeting_participants.filter(status='confirmed').select_related('participant')

    def get_pending_participants(self):
        """Получить участников, ожидающих подтверждения"""
        return self.meeting_participants.filter(status='pending').select_related('participant')

    def get_declined_participants(self):
        """Получить отказавших участников"""
        return self.meeting_participants.filter(status='declined').select_related('participant')


class MeetingParticipant(models.Model):
    """Промежуточная модель для участников встречи со статусом"""
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('confirmed', 'Подтверждено'),
        ('declined', 'Отклонено'),
    ]

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name='meeting_participants',
        verbose_name="Встреча"
    )

    participant = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='meeting_invitations',
        verbose_name="Участник"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Статус участия"
    )

    invited_at = models.DateTimeField(auto_now_add=True, verbose_name="Приглашен")
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name="Ответил")

    class Meta:
        verbose_name = "Участник встречи"
        verbose_name_plural = "Участники встреч"
        unique_together = ['meeting', 'participant']
        ordering = ['-invited_at']

    def __str__(self):
        return f"{self.participant} - {self.meeting} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """Обновляем время ответа при изменении статуса"""
        if self.pk:
            old_status = MeetingParticipant.objects.get(pk=self.pk).status
            if old_status == 'pending' and self.status != 'pending':
                from django.utils import timezone
                self.responded_at = timezone.now()

        super().save(*args, **kwargs)

        # Обновляем статус встречи, если все ответили
        if self.meeting.meeting_participants.filter(status='pending').count() == 0:
            if self.meeting.meeting_participants.filter(status='confirmed').count() > 0:
                self.meeting.status = 'confirmed'
            else:
                self.meeting.status = 'cancelled'
            self.meeting.save()


class MeetingNotification(models.Model):
    """Модель для уведомлений о встречах"""
    NOTIFICATION_TYPES = [
        ('invitation', 'Приглашение на встречу'),
        ('confirmation', 'Подтверждение встречи'),
        ('cancellation', 'Отмена встречи'),
        ('reminder', 'Напоминание о встрече'),
        ('update', 'Обновление встречи'),
    ]

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name="Встреча"
    )

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='meeting_notifications',
        verbose_name="Пользователь"
    )

    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        verbose_name="Тип уведомления"
    )

    message = models.TextField(verbose_name="Текст уведомления")
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="Отправлено")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="Прочитано")

    class Meta:
        verbose_name = "Уведомление о встрече"
        verbose_name_plural = "Уведомления о встречах"
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.get_notification_type_display()} для {self.user}"

    def mark_as_read(self):
        """Пометить как прочитанное"""
        from django.utils import timezone
        self.read_at = timezone.now()
        self.save()