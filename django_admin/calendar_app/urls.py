from django.urls import path
from . import views

urlpatterns = [
    path('export/<int:telegram_id>/<str:format_type>/', views.export_user_events, name='export_events'),
    path('export/<int:telegram_id>/', views.export_user_events, name='export_events_default'),
    path('token/<int:telegram_id>/', views.generate_export_token, name='generate_export_token'),
]