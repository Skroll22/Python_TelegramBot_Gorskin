# myapp/views.py
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views import View
import json
import csv

from rest_framework.permissions import AllowAny

from . import models
from .models import Event, BotStatistics, Meeting, MeetingInvitation
from datetime import datetime

# Импорты для DRF
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import connection
from .serializers import (
    BotStatisticsSerializer, MeetingSerializer,
    MeetingInvitationSerializer, EventSerializer, UserSerializer
)


# Существующий класс для экспорта
@method_decorator(csrf_exempt, name='dispatch')
class ExportEventsView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            user_id = data.get('user_id')
            format_type = data.get('format', 'json')  # json или csv

            if not user_id:
                return JsonResponse({'error': 'user_id обязателен'}, status=400)

            # Получаем события пользователя
            events = Event.objects.filter(user_id=user_id).order_by('event_date')

            if format_type == 'csv':
                return self.export_csv(events, user_id)
            else:
                return self.export_json(events, user_id)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Неверный формат JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    def export_json(self, events, user_id):
        events_data = []
        for event in events:
            events_data.append({
                'id': event.id,
                'event_name': event.event_name,
                'event_date': event.event_date.strftime('%d.%m.%Y'),
                'is_public': event.is_public,
                'created_at': event.created_at.strftime('%d.%m.%Y %H:%M:%S') if event.created_at else None
            })

        response_data = {
            'user_id': user_id,
            'exported_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
            'total_events': len(events_data),
            'events': events_data
        }

        return JsonResponse(response_data)

    def export_csv(self, events, user_id):
        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="events_{user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', 'Название события', 'Дата события', 'Публичное', 'Создано'])

        for event in events:
            writer.writerow([
                event.id,
                event.event_name,
                event.event_date.strftime('%d.%m.%Y'),
                'Да' if event.is_public else 'Нет',
                event.created_at.strftime('%d.%m.%Y %H:%M:%S') if event.created_at else ''
            ])

        return response


# Новые классы API для DRF

class BotStatisticsViewSet(viewsets.ModelViewSet):
    queryset = BotStatistics.objects.all().order_by('-date')
    serializer_class = BotStatisticsSerializer

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Получить последнюю статистику"""
        latest_stats = BotStatistics.objects.order_by('-date').first()
        if latest_stats:
            serializer = self.get_serializer(latest_stats)
            return Response(serializer.data)
        return Response({"detail": "Статистика не найдена"}, status=status.HTTP_404_NOT_FOUND)


class MeetingViewSet(viewsets.ModelViewSet):
    queryset = Meeting.objects.all().order_by('-created_at')
    serializer_class = MeetingSerializer

    def get_queryset(self):
        """Фильтрация встреч по пользователю"""
        queryset = Meeting.objects.all().order_by('-created_at')
        user_id = self.request.query_params.get('user_id')
        status_filter = self.request.query_params.get('status')

        if user_id:
            queryset = queryset.filter(
                models.Q(organizer=user_id) |
                models.Q(participants__contains=[int(user_id)])
            )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Обновить статус встречи"""
        meeting = self.get_object()
        new_status = request.data.get('status')

        if new_status in ['pending', 'confirmed', 'cancelled', 'declined']:
            meeting.status = new_status
            meeting.save()
            serializer = self.get_serializer(meeting)
            return Response(serializer.data)
        else:
            return Response(
                {"error": "Неверный статус"},
                status=status.HTTP_400_BAD_REQUEST
            )


class MeetingInvitationViewSet(viewsets.ModelViewSet):
    queryset = MeetingInvitation.objects.all().order_by('-created_at')
    serializer_class = MeetingInvitationSerializer

    def get_queryset(self):
        """Фильтрация приглашений по пользователю"""
        queryset = MeetingInvitation.objects.all().order_by('-created_at')
        participant_id = self.request.query_params.get('participant_id')
        status_filter = self.request.query_params.get('status')

        if participant_id:
            queryset = queryset.filter(participant_id=participant_id)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset


class EventViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        """Получить все события"""
        user_id = request.query_params.get('user_id')
        public_only = request.query_params.get('public_only', 'false').lower() == 'true'

        try:
            with connection.cursor() as cursor:
                if user_id:
                    cursor.execute('''
                        SELECT e.id, e.event_name, TO_CHAR(e.event_date, 'DD.MM.YYYY'), 
                               e.user_id, u.username, u.first_name, u.last_name, e.is_public
                        FROM events e
                        JOIN users u ON e.user_id = u.user_id
                        WHERE e.user_id = %s
                        ORDER BY e.event_date
                    ''', [user_id])
                elif public_only:
                    cursor.execute('''
                        SELECT e.id, e.event_name, TO_CHAR(e.event_date, 'DD.MM.YYYY'), 
                               e.user_id, u.username, u.first_name, u.last_name, e.is_public
                        FROM events e
                        JOIN users u ON e.user_id = u.user_id
                        WHERE e.is_public = true
                        ORDER BY e.event_date
                    ''')
                else:
                    cursor.execute('''
                        SELECT e.id, e.event_name, TO_CHAR(e.event_date, 'DD.MM.YYYY'), 
                               e.user_id, u.username, u.first_name, u.last_name, e.is_public
                        FROM events e
                        JOIN users u ON e.user_id = u.user_id
                        ORDER BY e.event_date
                    ''')

                events_data = cursor.fetchall()

            events = []
            for row in events_data:
                event_dict = {
                    'id': row[0],
                    'event_name': row[1],
                    'event_date': row[2],
                    'user_id': row[3],
                    'username': row[4] or '',
                    'first_name': row[5] or '',
                    'last_name': row[6] or '',
                    'is_public': row[7]
                }
                events.append(event_dict)

            serializer = EventSerializer(events, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {"error": f"Ошибка получения событий: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UsersAPIView(APIView):
    """API для работы с пользователями"""

    def get(self, request):
        """Получить пользователей"""
        try:
            with connection.cursor() as cursor:
                cursor.execute('''
                    SELECT user_id, username, first_name, last_name, 
                           CASE WHEN password IS NOT NULL THEN true ELSE false END as is_registered
                    FROM users
                    ORDER BY user_id
                ''')
                users_data = cursor.fetchall()

            # Преобразуем данные в список словарей
            users = []
            for row in users_data:
                user_dict = {
                    'user_id': row[0],
                    'username': row[1],
                    'first_name': row[2] or '',
                    'last_name': row[3] or '',
                    'is_registered': row[4]
                }
                users.append(user_dict)

            serializer = UserSerializer(users, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {"error": f"Ошибка получения пользователей: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Дополнительный APIView для экспорта через DRF
class ExportEventsAPIView(APIView):
    """API для экспорта событий через DRF"""

    def post(self, request):
        user_id = request.data.get('user_id')
        format_type = request.data.get('format', 'json')

        if not user_id:
            return Response(
                {"error": "user_id обязателен"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with connection.cursor() as cursor:
                cursor.execute('''
                    SELECT event_name, TO_CHAR(event_date, 'DD.MM.YYYY'), is_public
                    FROM events
                    WHERE user_id = %s
                    ORDER BY event_date
                ''', [user_id])

                events = cursor.fetchall()

            if format_type == 'csv':
                # Генерация CSV
                import csv
                from django.http import HttpResponse

                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="events_{user_id}.csv"'

                writer = csv.writer(response)
                writer.writerow(['Event Name', 'Date', 'Is Public'])

                for event in events:
                    writer.writerow(event)

                return response
            else:
                # JSON формат
                events_list = []
                for event in events:
                    events_list.append({
                        'event_name': event[0],
                        'event_date': event[1],
                        'is_public': event[2]
                    })

                return Response({
                    'user_id': user_id,
                    'events_count': len(events_list),
                    'events': events_list
                })

        except Exception as e:
            return Response(
                {"error": f"Ошибка экспорта: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )