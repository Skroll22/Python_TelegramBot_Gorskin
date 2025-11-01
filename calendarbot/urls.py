"""
URL configuration for calendarbot project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from myapp import views

# Создаем router для DRF
router = routers.DefaultRouter()
router.register(r'statistics', views.BotStatisticsViewSet)
router.register(r'meetings', views.MeetingViewSet)
router.register(r'invitations', views.MeetingInvitationViewSet)
router.register(r'events', views.EventViewSet, basename='event')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('export-events/', views.ExportEventsView.as_view(), name='export_events'),
    path('api/', include(router.urls)),
    path('api/users/', views.UsersAPIView.as_view(), name='api_users'),
    path('api/export/', views.ExportEventsAPIView.as_view(), name='api_export'),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]