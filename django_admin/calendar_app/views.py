from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
import json
import csv
import datetime
from io import StringIO, BytesIO
import zipfile

from .models import TelegramUser, CalendarEvent, Meeting, MeetingParticipant


@csrf_exempt
@require_GET
def export_user_events(request, telegram_id, format_type='json'):
    """Экспорт событий пользователя"""
    try:
        auth_token = request.GET.get('token', '')
        # Получаем пользователя
        try:
            user = TelegramUser.objects.get(telegram_id=telegram_id)
        except TelegramUser.DoesNotExist:
            return JsonResponse({
                'error': 'Пользователь не найден',
                'code': 'user_not_found'
            }, status=404)

        # Получаем параметры запроса
        date_from = request.GET.get('from')
        date_to = request.GET.get('to')
        event_type = request.GET.get('type', 'all')  # all, calendar, meetings

        # Фильтруем события
        calendar_events = CalendarEvent.objects.filter(user=user)
        meetings = Meeting.objects.filter(
            Q(organizer=user) | Q(participants=user)
        ).distinct()

        # Применяем фильтры по дате
        if date_from:
            try:
                date_from_obj = datetime.datetime.strptime(date_from, '%Y-%m-%d').date()
                calendar_events = calendar_events.filter(date__gte=date_from_obj)
                meetings = meetings.filter(date__gte=date_from_obj)
            except ValueError:
                pass

        if date_to:
            try:
                date_to_obj = datetime.datetime.strptime(date_to, '%Y-%m-%d').date()
                calendar_events = calendar_events.filter(date__lte=date_to_obj)
                meetings = meetings.filter(date__lte=date_to_obj)
            except ValueError:
                pass

        # Подготавливаем данные
        if event_type == 'calendar':
            data = prepare_calendar_events_data(calendar_events)
        elif event_type == 'meetings':
            data = prepare_meetings_data(meetings, user)
        else:  # all
            data = {
                'calendar_events': prepare_calendar_events_data(calendar_events),
                'meetings': prepare_meetings_data(meetings, user)
            }

        # Возвращаем в нужном формате
        if format_type == 'csv':
            return export_to_csv(data, user)
        elif format_type == 'json':
            return export_to_json(data, user)
        elif format_type == 'ical':
            return export_to_ical(data, user)
        else:
            return JsonResponse({
                'error': 'Неподдерживаемый формат',
                'supported_formats': ['json', 'csv', 'ical'],
                'code': 'unsupported_format'
            }, status=400)

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'code': 'server_error'
        }, status=500)


def prepare_calendar_events_data(events_queryset):
    """Подготовка данных календарных событий"""
    events = []
    for event in events_queryset:
        events.append({
            'id': event.id,
            'type': 'calendar_event',
            'title': event.title,
            'description': event.description or '',
            'date': event.date.strftime('%Y-%m-%d'),
            'is_public': event.is_public,
            'created_at': event.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': event.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return events


def prepare_meetings_data(meetings_queryset, user):
    """Подготовка данных встреч"""
    meetings_list = []
    for meeting in meetings_queryset:
        # Получаем статус участия пользователя
        participant_status = None
        try:
            participant = MeetingParticipant.objects.get(
                meeting=meeting,
                participant=user
            )
            participant_status = participant.status
        except MeetingParticipant.DoesNotExist:
            pass

        meetings_list.append({
            'id': meeting.id,
            'type': 'meeting',
            'title': meeting.title,
            'description': meeting.description or '',
            'date': meeting.date.strftime('%Y-%m-%d'),
            'start_time': meeting.start_time.strftime('%H:%M:%S'),
            'end_time': meeting.end_time.strftime('%H:%M:%S'),
            'organizer_id': meeting.organizer.telegram_id,
            'organizer_name': meeting.organizer.first_name or meeting.organizer.username,
            'status': meeting.status,
            'participant_status': participant_status,
            'created_at': meeting.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': meeting.updated_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return meetings_list


def export_to_json(data, user):
    """Экспорт в JSON"""
    response_data = {
        'user_id': user.telegram_id,
        'username': user.username or '',
        'first_name': user.first_name or '',
        'export_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'events_count': {
            'calendar': len(data.get('calendar_events', [])) if isinstance(data, dict) else len(data),
            'meetings': len(data.get('meetings', [])) if isinstance(data, dict) else 0
        },
        'data': data
    }

    response = JsonResponse(response_data, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response[
        'Content-Disposition'] = f'attachment; filename="events_export_{user.telegram_id}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
    return response


def export_to_csv(data, user):
    """Экспорт в CSV"""
    # Создаем строковый буфер
    output = StringIO()
    writer = csv.writer(output, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)

    # Записываем заголовок
    writer.writerow(
        ['Тип события', 'Название', 'Описание', 'Дата', 'Время начала', 'Время окончания', 'Статус', 'Создано'])

    # Записываем календарные события
    if isinstance(data, dict):
        calendar_events = data.get('calendar_events', [])
        meetings = data.get('meetings', [])
    else:
        calendar_events = data
        meetings = []

    for event in calendar_events:
        writer.writerow([
            'Календарное событие',
            event['title'],
            event['description'],
            event['date'],
            '',  # время начала
            '',  # время окончания
            'Публичное' if event['is_public'] else 'Приватное',
            event['created_at']
        ])

    # Записываем встречи
    for meeting in meetings:
        writer.writerow([
            'Встреча',
            meeting['title'],
            meeting['description'],
            meeting['date'],
            meeting['start_time'],
            meeting['end_time'],
            meeting['status'],
            meeting['created_at']
        ])

    # Возвращаем CSV файл
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response[
        'Content-Disposition'] = f'attachment; filename="events_export_{user.telegram_id}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    return response


def export_to_ical(data, user):
    """Экспорт в iCalendar format"""
    ical_content = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Telegram Calendar Bot//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
"""

    # Добавляем календарные события
    if isinstance(data, dict):
        calendar_events = data.get('calendar_events', [])
        meetings = data.get('meetings', [])
    else:
        calendar_events = data
        meetings = []

    all_events = calendar_events + meetings

    for idx, event in enumerate(all_events):
        event_type = event.get('type', '')

        # Форматируем дату
        if 'date' in event:
            date_str = event['date'].replace('-', '')
        else:
            date_str = datetime.datetime.now().strftime('%Y%m%d')

        # Формируем время
        dtstart = f"{date_str}"
        dtend = f"{date_str}"

        # Для встреч добавляем время
        if 'start_time' in event and event['start_time']:
            start_time = event['start_time'].replace(':', '')
            dtstart = f"{date_str}T{start_time}00"

        if 'end_time' in event and event['end_time']:
            end_time = event['end_time'].replace(':', '')
            dtend = f"{date_str}T{end_time}00"

        # Добавляем событие
        ical_content += f"""BEGIN:VEVENT
UID:{user.telegram_id}_{event.get('id', idx)}_{date_str}
DTSTAMP:{datetime.datetime.now().strftime('%Y%m%dT%H%M%SZ')}
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:{event.get('title', 'Без названия')}
DESCRIPTION:{event.get('description', '')}
END:VEVENT
"""

    ical_content += "END:VCALENDAR"

    response = HttpResponse(ical_content, content_type='text/calendar; charset=utf-8')
    response[
        'Content-Disposition'] = f'attachment; filename="calendar_export_{user.telegram_id}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.ics"'
    return response


@csrf_exempt
@require_POST
def generate_export_token(request, telegram_id):
    """Генерация токена для экспорта"""
    try:
        import hashlib
        import time

        # Проверяем существование пользователя
        try:
            user = TelegramUser.objects.get(telegram_id=telegram_id)
        except TelegramUser.DoesNotExist:
            return JsonResponse({
                'error': 'Пользователь не найден',
                'code': 'user_not_found'
            }, status=404)

        # Генерируем токен
        timestamp = str(int(time.time()))
        token_string = f"{telegram_id}{timestamp}{user.username or ''}"
        token = hashlib.md5(token_string.encode()).hexdigest()

        return JsonResponse({
            'token': token,
            'expires_in': 3600,  # 1 час
            'expires_at': datetime.datetime.now() + datetime.timedelta(hours=1)
        })

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'code': 'server_error'
        }, status=500)