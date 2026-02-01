import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import datetime, timedelta
import random

from .models import (
    TelegramUser, CalendarEvent, BotStatistics,
    UserInteraction, EventChangeLog, Meeting,
    MeetingParticipant, MeetingNotification
)


class TelegramUserFactory(DjangoModelFactory):
    class Meta:
        model = TelegramUser
        django_get_or_create = ('telegram_id',)

    telegram_id = factory.Sequence(lambda n: 1000000000 + n)
    username = factory.LazyAttribute(lambda o: f"test_user_{o.telegram_id}")
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    language_code = 'ru'
    registered_at = factory.LazyFunction(timezone.now)
    last_seen = factory.LazyFunction(timezone.now)


class CalendarEventFactory(DjangoModelFactory):
    class Meta:
        model = CalendarEvent

    user = factory.SubFactory(TelegramUserFactory)
    date = factory.LazyFunction(lambda: timezone.now().date() + timedelta(days=random.randint(1, 30)))
    title = factory.Faker('sentence', nb_words=4)
    description = factory.Faker('text', max_nb_chars=200)
    is_public = factory.Faker('boolean', chance_of_getting_true=30)
    created_at = factory.LazyFunction(timezone.now)
    updated_at = factory.LazyFunction(timezone.now)

    @factory.post_generation
    def set_published_at(self, create, extracted, **kwargs):
        if create and self.is_public:
            self.published_at = timezone.now()
            self.save()


class BotStatisticsFactory(DjangoModelFactory):
    class Meta:
        model = BotStatistics

    date = factory.LazyFunction(lambda: timezone.now().date())
    total_users = factory.Faker('random_int', min=1, max=1000)
    total_events = factory.Faker('random_int', min=1, max=5000)
    daily_new_users = factory.Faker('random_int', min=0, max=10)
    daily_active_users = factory.Faker('random_int', min=0, max=50)
    daily_created_events = factory.Faker('random_int', min=0, max=20)
    daily_updated_events = factory.Faker('random_int', min=0, max=10)
    daily_deleted_events = factory.Faker('random_int', min=0, max=5)
    daily_start_commands = factory.Faker('random_int', min=0, max=50)
    daily_help_commands = factory.Faker('random_int', min=0, max=30)
    daily_list_commands = factory.Faker('random_int', min=0, max=40)
    daily_today_commands = factory.Faker('random_int', min=0, max=20)
    daily_stats_commands = factory.Faker('random_int', min=0, max=10)
    user_activity_data = factory.LazyFunction(lambda: {
        'hour_distribution': {str(h): random.randint(0, 10) for h in range(24)},
        'top_users_today': [],
        'event_categories': {}
    })
    event_type_data = factory.LazyFunction(lambda: {
        'встреча': random.randint(0, 10),
        'день рождения': random.randint(0, 5),
        'дедлайн': random.randint(0, 8),
        'задача': random.randint(0, 15),
        'праздник': random.randint(0, 3),
        'напоминание': random.randint(0, 7),
        'другое': random.randint(0, 20)
    })


class UserInteractionFactory(DjangoModelFactory):
    class Meta:
        model = UserInteraction

    user = factory.SubFactory(TelegramUserFactory)
    command = factory.Iterator(['/start', '/help', '/list', '/today', '/create', '/delete'])
    parameters = factory.LazyFunction(lambda: {'param1': 'value1', 'param2': 'value2'})
    created_at = factory.LazyFunction(timezone.now)


class MeetingFactory(DjangoModelFactory):
    class Meta:
        model = Meeting

    title = factory.Faker('sentence', nb_words=5)
    description = factory.Faker('text', max_nb_chars=300)
    date = factory.LazyFunction(lambda: timezone.now().date() + timedelta(days=random.randint(1, 14)))
    start_time = factory.LazyFunction(lambda: datetime.strptime(f"{random.randint(9, 16)}:00", "%H:%M").time())
    end_time = factory.LazyAttribute(lambda o: (
        datetime.combine(datetime.today(), o.start_time) + timedelta(hours=random.randint(1, 3))
    ).time())
    organizer = factory.SubFactory(TelegramUserFactory)
    status = factory.Iterator(['pending', 'confirmed', 'cancelled'])
    created_at = factory.LazyFunction(timezone.now)
    updated_at = factory.LazyFunction(timezone.now)

    @factory.post_generation
    def participants(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for participant in extracted:
                MeetingParticipantFactory(meeting=self, participant=participant)


class MeetingParticipantFactory(DjangoModelFactory):
    class Meta:
        model = MeetingParticipant

    meeting = factory.SubFactory(MeetingFactory)
    participant = factory.SubFactory(TelegramUserFactory)
    status = factory.Iterator(['pending', 'confirmed', 'declined'])
    invited_at = factory.LazyFunction(timezone.now)
    responded_at = factory.LazyAttribute(lambda o: (
        timezone.now() if o.status != 'pending' else None
    ))


class MeetingNotificationFactory(DjangoModelFactory):
    class Meta:
        model = MeetingNotification

    meeting = factory.SubFactory(MeetingFactory)
    user = factory.SubFactory(TelegramUserFactory)
    notification_type = factory.Iterator(['invitation', 'confirmation', 'cancellation', 'reminder', 'update'])
    message = factory.Faker('sentence', nb_words=10)
    sent_at = factory.LazyFunction(timezone.now)
    read_at = factory.LazyAttribute(lambda o: (
        timezone.now() if random.choice([True, False]) else None
    ))