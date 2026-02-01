from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.schemas import get_schema_view
from rest_framework.documentation import include_docs_urls
from django.views.generic import TemplateView

from .api_views import (
    TelegramUserViewSet, CalendarEventViewSet,
    BotStatisticsViewSet, MeetingViewSet,
    PublicAPIView, PublicEventsView, PublicStatsView,
    ReportsViewSet
)

# Создаем router
router = DefaultRouter()
router.register(r'users', TelegramUserViewSet, basename='user')
router.register(r'events', CalendarEventViewSet, basename='event')
router.register(r'statistics', BotStatisticsViewSet, basename='statistic')
router.register(r'meetings', MeetingViewSet, basename='meeting')
router.register(r'reports', ReportsViewSet, basename='report')

# URL patterns
urlpatterns = [
    # API root
    path('', PublicAPIView.as_view(), name='api_root'),

    # Router URLs
    path('', include(router.urls)),

    # Публичные эндпоинты
    path('public/events/', PublicEventsView.as_view(), name='public_events'),
    path('public/stats/', PublicStatsView.as_view(), name='public_stats'),

    # Аутентификация
    path('auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('auth/token/', obtain_auth_token, name='api_token_auth'),

    # Документация
    path('docs/', include_docs_urls(title='Calendar Bot API')),
    path('schema/', get_schema_view(
        title="Calendar Bot API",
        description="API для Telegram календарного бота",
        version="1.0.0"
    ), name='openapi-schema'),
    path('swagger-ui/', TemplateView.as_view(
        template_name='swagger-ui.html',
        extra_context={'schema_url': 'openapi-schema'}
    ), name='swagger-ui'),
]