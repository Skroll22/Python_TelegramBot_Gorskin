from django.db import models

# Create your models here.
class Event(models.Model):
    user_id = models.BigIntegerField(verbose_name="ID пользователя")
    event_name = models.CharField(max_length=255, verbose_name="Название события")
    event_date = models.DateField(verbose_name="Дата события")
    is_public = models.BooleanField(default=False, verbose_name="Публичное событие")
    shared_by = models.BigIntegerField(null=True, blank=True, verbose_name="ID пользователя, который поделился")
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name="Создано")

    class Meta:
        db_table = 'events'
        verbose_name = "Событие"
        verbose_name_plural = "События"

    def __str__(self):
        return f"{self.event_name} - {self.event_date}"

class BotStatistics(models.Model):
    date = models.DateField(auto_now_add=True)
    total_users = models.IntegerField(default=0)
    total_events = models.IntegerField(default=0)
    deleted_events = models.IntegerField(default=0)
    edited_events = models.IntegerField(default=0)
    active_users = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Статистика бота"
        verbose_name_plural = "Статистика бота"
        ordering = ['-date']

    def __str__(self):
        return f"Статистика за {self.date}"


class Meeting(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает подтверждения'),
        ('confirmed', 'Подтверждена'),
        ('cancelled', 'Отменена'),
        ('declined', 'Отклонена'),
    ]

    title = models.CharField(max_length=255, verbose_name="Название встречи")
    description = models.TextField(blank=True, verbose_name="Описание")
    meeting_date = models.DateField(verbose_name="Дата встречи")
    meeting_time = models.TimeField(verbose_name="Время встречи")
    duration = models.IntegerField(default=60, verbose_name="Длительность (минуты)")
    organizer = models.BigIntegerField(verbose_name="ID организатора")  # Telegram user_id
    participants = models.JSONField(default=list, verbose_name="Участники")  # Список user_id
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Статус")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлена")

    class Meta:
        verbose_name = "Встреча"
        verbose_name_plural = "Встречи"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.meeting_date} {self.meeting_time}"


class MeetingInvitation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает ответа'),
        ('accepted', 'Принято'),
        ('declined', 'Отклонено'),
    ]

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, verbose_name="Встреча")
    participant_id = models.BigIntegerField(verbose_name="ID участника")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending',
                              verbose_name="Статус приглашения")
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name="Время ответа")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Приглашение на встречу"
        verbose_name_plural = "Приглашения на встречи"
        unique_together = ['meeting', 'participant_id']

    def __str__(self):
        return f"Приглашение для {self.participant_id} на {self.meeting.title}"