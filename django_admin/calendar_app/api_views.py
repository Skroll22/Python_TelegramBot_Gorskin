from rest_framework import viewsets, generics, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone
from datetime import datetime, timedelta
import json

from .models import (
    TelegramUser, CalendarEvent, BotStatistics,
    UserInteraction, EventChangeLog, Meeting,
    MeetingParticipant, MeetingNotification
)
from .serializers import (
    TelegramUserSerializer, CalendarEventSerializer,
    BotStatisticsSerializer, UserInteractionSerializer,
    EventChangeLogSerializer, MeetingSerializer,
    MeetingParticipantSerializer, MeetingNotificationSerializer,
    UserStatsSerializer, EventReportSerializer, MeetingReportSerializer
)


class ReportsViewSet(viewsets.ViewSet):
    """ViewSet для генерации отчетов"""
    permission_classes = [IsAdminUser]

    def list(self, request):
        """Список доступных отчетов"""
        return Response({
            'available_reports': {
                'user_stats': '/api/reports/user_stats/?days=30',
                'event_report': '/api/reports/event_report/?start_date=2024-01-01&end_date=2024-12-31',
                'meeting_report': '/api/reports/meeting_report/?start_date=2024-01-01&end_date=2024-12-31',
            }
        })

    @action(detail=False, methods=['get'])
    def user_stats(self, request):
        """Отчет по пользователям"""
        days = int(request.query_params.get('days', 30))
        since_date = timezone.now() - timedelta(days=days)

        users = TelegramUser.objects.filter(
            registered_at__gte=since_date
        ).annotate(
            events_count=Count('events'),
            meetings_count=Count('meetings') + Count('organized_meetings'),
            public_events_count=Count('events', filter=Q(events__is_public=True))
        )

        serializer = UserStatsSerializer(users, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def event_report(self, request):
        """Отчет по событиям"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date or not end_date:
            return Response(
                {'detail': 'Укажите start_date и end_date'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем события за период
        events = CalendarEvent.objects.filter(
            date__range=[start_date, end_date]
        )

        report_data = {
            'period': f'{start_date} - {end_date}',
            'total_events': events.count(),
            'public_events': events.filter(is_public=True).count(),
            'unique_users': events.values('user').distinct().count(),
            'events_by_date': list(events.values('date').annotate(
                count=Count('id')
            ).order_by('date'))
        }

        return Response(report_data)

    @action(detail=False, methods=['get'])
    def meeting_report(self, request):
        """Отчет по встречам"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date or not end_date:
            return Response(
                {'detail': 'Укажите start_date и end_date'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Получаем встречи за период
        meetings = Meeting.objects.filter(
            date__range=[start_date, end_date]
        )

        report_data = {
            'period': f'{start_date} - {end_date}',
            'total_meetings': meetings.count(),
            'confirmed_meetings': meetings.filter(status='confirmed').count(),
            'pending_meetings': meetings.filter(status='pending').count(),
            'cancelled_meetings': meetings.filter(status='cancelled').count(),
            'avg_participants': meetings.annotate(
                participant_count=Count('participants')
            ).aggregate(
                avg=Avg('participant_count')
            )['avg'] or 0,
            'meetings_by_date': list(meetings.values('date').annotate(
                count=Count('id')
            ).order_by('date'))
        }

        return Response(report_data)

# Кастомная пагинация
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ViewSet для пользователей Telegram
class TelegramUserViewSet(viewsets.ModelViewSet):
    """ViewSet для управления пользователями Telegram"""
    queryset = TelegramUser.objects.all().order_by('-registered_at')
    serializer_class = TelegramUserSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['username', 'first_name', 'last_name']
    search_fields = ['username', 'first_name', 'last_name', 'telegram_id']
    ordering_fields = ['registered_at', 'last_seen', 'telegram_id']

    # Разрешаем доступ только администраторам
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=['get'])
    def events(self, request, pk=None):
        """Получить события пользователя"""
        user = self.get_object()
        events = CalendarEvent.objects.filter(user=user)
        page = self.paginate_queryset(events)

        if page is not None:
            serializer = CalendarEventSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = CalendarEventSerializer(events, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def meetings(self, request, pk=None):
        """Получить встречи пользователя"""
        user = self.get_object()
        meetings = Meeting.objects.filter(
            Q(organizer=user) | Q(participants=user)
        ).distinct()

        page = self.paginate_queryset(meetings)

        if page is not None:
            serializer = MeetingSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = MeetingSerializer(meetings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Получить статистику пользователя"""
        user = self.get_object()

        stats = {
            'telegram_id': user.telegram_id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'total_events': CalendarEvent.objects.filter(user=user).count(),
            'total_meetings': Meeting.objects.filter(
                Q(organizer=user) | Q(participants=user)
            ).distinct().count(),
            'public_events': CalendarEvent.objects.filter(user=user, is_public=True).count(),
            'last_active': user.last_seen,
            'registered_at': user.registered_at,
            'interactions_count': UserInteraction.objects.filter(user=user).count(),
        }

        return Response(stats)

    @action(detail=False, methods=['get'])
    def top_active(self, request):
        """Топ активных пользователей"""
        days = int(request.query_params.get('days', 7))
        since_date = timezone.now() - timedelta(days=days)

        top_users = TelegramUser.objects.filter(
            last_seen__gte=since_date
        ).annotate(
            events_count=Count('events'),
            meetings_count=Count('meetings') + Count('organized_meetings')
        ).order_by('-last_seen')[:10]

        serializer = TelegramUserSerializer(top_users, many=True)
        return Response(serializer.data)


# ViewSet для событий календаря
class CalendarEventViewSet(viewsets.ModelViewSet):
    """ViewSet для управления событиями календаря"""
    queryset = CalendarEvent.objects.all().order_by('-date', '-created_at')
    serializer_class = CalendarEventSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['user', 'date', 'is_public']
    search_fields = ['title', 'description', 'user__username']
    ordering_fields = ['date', 'created_at', 'updated_at']

    # Разрешаем доступ аутентифицированным пользователям
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Фильтрация queryset в зависимости от пользователя"""
        queryset = super().get_queryset()

        # Если пользователь не администратор, показываем только публичные события
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_public=True)

        # Фильтрация по дате
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Опубликовать событие"""
        event = self.get_object()

        if event.is_public:
            return Response(
                {'detail': 'Событие уже опубликовано'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.is_public = True
        event.published_at = timezone.now()
        event.save()

        # Логируем изменение
        EventChangeLog.objects.create(
            event=event,
            user=event.user,
            action='publish',
            new_data={
                'title': event.title,
                'date': event.date.strftime("%d.%m.%Y"),
                'published_at': event.published_at.strftime("%d.%m.%Y %H:%M")
            }
        )

        serializer = self.get_serializer(event)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        """Сделать событие приватным"""
        event = self.get_object()

        if not event.is_public:
            return Response(
                {'detail': 'Событие уже приватное'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.is_public = False
        event.save()

        # Логируем изменение
        EventChangeLog.objects.create(
            event=event,
            user=event.user,
            action='unpublish',
            old_data={
                'title': event.title,
                'date': event.date.strftime("%d.%m.%Y"),
                'published_at': event.published_at.strftime("%d.%m.%Y %H:%M")
            }
        )

        serializer = self.get_serializer(event)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Предстоящие события"""
        today = timezone.now().date()
        events = self.get_queryset().filter(date__gte=today).order_by('date')[:50]

        page = self.paginate_queryset(events)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def today(self, request):
        """События на сегодня"""
        today = timezone.now().date()
        events = self.get_queryset().filter(date=today)

        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)


# ViewSet для статистики бота
class BotStatisticsViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet для просмотра статистики бота"""
    queryset = BotStatistics.objects.all().order_by('-date')
    serializer_class = BotStatisticsSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['date']
    ordering_fields = ['date', 'total_users', 'total_events']

    # Разрешаем доступ только администраторам
    permission_classes = [IsAdminUser]

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Статистика за сегодня"""
        today = timezone.now().date()
        stats, created = BotStatistics.objects.get_or_create(date=today)

        # Обновляем статистику
        stats.update_daily_stats()

        serializer = self.get_serializer(stats)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Сводная статистика"""
        days = int(request.query_params.get('days', 30))
        since_date = timezone.now() - timedelta(days=days)

        stats = BotStatistics.objects.filter(date__gte=since_date.date())

        summary = {
            'period_days': days,
            'total_users': TelegramUser.objects.count(),
            'total_events': CalendarEvent.objects.count(),
            'total_meetings': Meeting.objects.count(),
            'new_users': stats.aggregate(total=Sum('daily_new_users'))['total'] or 0,
            'active_users': stats.aggregate(total=Sum('daily_active_users'))['total'] or 0,
            'created_events': stats.aggregate(total=Sum('daily_created_events'))['total'] or 0,
            'total_commands': sum([
                stats.aggregate(total=Sum('daily_start_commands'))['total'] or 0,
                stats.aggregate(total=Sum('daily_help_commands'))['total'] or 0,
                stats.aggregate(total=Sum('daily_list_commands'))['total'] or 0,
                stats.aggregate(total=Sum('daily_today_commands'))['total'] or 0,
                stats.aggregate(total=Sum('daily_stats_commands'))['total'] or 0,
            ])
        }

        return Response(summary)


# ViewSet для встреч
class MeetingViewSet(viewsets.ModelViewSet):
    """ViewSet для управления встречами"""
    queryset = Meeting.objects.all().order_by('-date', '-created_at')
    serializer_class = MeetingSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['organizer', 'date', 'status']
    search_fields = ['title', 'description', 'organizer__username']
    ordering_fields = ['date', 'start_time', 'created_at']

    # Разрешаем доступ аутентифицированным пользователям
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'])
    def invite_participant(self, request, pk=None):
        """Пригласить участника на встречу"""
        meeting = self.get_object()
        participant_id = request.data.get('participant_id')

        if not participant_id:
            return Response(
                {'detail': 'Не указан ID участника'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            participant = TelegramUser.objects.get(telegram_id=participant_id)
        except TelegramUser.DoesNotExist:
            return Response(
                {'detail': 'Пользователь не найден'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Проверяем, не приглашен ли уже участник
        if MeetingParticipant.objects.filter(meeting=meeting, participant=participant).exists():
            return Response(
                {'detail': 'Участник уже приглашен'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Создаем приглашение
        meeting_participant = MeetingParticipant.objects.create(
            meeting=meeting,
            participant=participant,
            status='pending'
        )

        # Создаем уведомление
        MeetingNotification.objects.create(
            meeting=meeting,
            user=participant,
            notification_type='invitation',
            message=f"Вас пригласили на встречу '{meeting.title}'"
        )

        serializer = MeetingParticipantSerializer(meeting_participant)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def participants(self, request, pk=None):
        """Получить участников встречи"""
        meeting = self.get_object()
        participants = meeting.meeting_participants.all()

        serializer = MeetingParticipantSerializer(participants, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Предстоящие встречи"""
        today = timezone.now().date()
        meetings = self.get_queryset().filter(date__gte=today, status='confirmed').order_by('date', 'start_time')[:50]

        page = self.paginate_queryset(meetings)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(meetings, many=True)
        return Response(serializer.data)


# APIView для публичных эндпоинтов
class PublicAPIView(APIView):
    """Публичные API эндпоинты"""
    permission_classes = [AllowAny]

    def get(self, request):
        """Информация о API"""
        return Response({
            'api_name': 'Telegram Calendar Bot API',
            'version': '1.0.0',
            'description': 'REST API для Telegram календарного бота',
            'endpoints': {
                'users': '/api/users/',
                'events': '/api/events/',
                'meetings': '/api/meetings/',
                'statistics': '/api/statistics/',
                'public_events': '/api/public/events/',
                'public_stats': '/api/public/stats/',
            },
            'documentation': '/api/docs/',
            'browsable_api': '/api/',
        })


class PublicEventsView(generics.ListAPIView):
    """Публичные события"""
    permission_classes = [AllowAny]
    serializer_class = CalendarEventSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """Только публичные события"""
        return CalendarEvent.objects.filter(
            is_public=True,
            date__gte=timezone.now().date()
        ).order_by('date', 'created_at')


class PublicStatsView(APIView):
    """Публичная статистика"""
    permission_classes = [AllowAny]

    def get(self, request):
        """Основная статистика"""
        stats = {
            'total_users': TelegramUser.objects.count(),
            'total_events': CalendarEvent.objects.count(),
            'public_events': CalendarEvent.objects.filter(is_public=True).count(),
            'total_meetings': Meeting.objects.count(),
            'active_today': TelegramUser.objects.filter(
                last_seen__date=timezone.now().date()
            ).count(),
            'new_today': TelegramUser.objects.filter(
                registered_at__date=timezone.now().date()
            ).count(),
        }

        return Response(stats)


# View для отчетов
class ReportsView(APIView):
    """Генерация отчетов"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        """Доступные отчеты"""
        return Response({
            'available_reports': {
                'user_stats': '/api/reports/user_stats/?days=30',
                'event_report': '/api/reports/event_report/?start_date=2024-01-01&end_date=2024-12-31',
                'meeting_report': '/api/reports/meeting_report/?start_date=2024-01-01&end_date=2024-12-31',
            }
        })

    @action(detail=False, methods=['get'])
    def user_stats(self, request):
        """Отчет по пользователям"""
        days = int(request.query_params.get('days', 30))
        since_date = timezone.now() - timedelta(days=days)

        users = TelegramUser.objects.filter(
            registered_at__gte=since_date
        ).annotate(
            events_count=Count('events'),
            meetings_count=Count('meetings') + Count('organized_meetings'),
            public_events_count=Count('events', filter=Q(events__is_public=True))
        )

        serializer = UserStatsSerializer(users, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def event_report(self, request):
        """Отчет по событиям"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if not start_date or not end_date:
            return Response(
                {'detail': 'Укажите start_date и end_date'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({'message': 'Отчет по событиям'})