from django.urls import path
from . import views

urlpatterns = [
    path('export-events/', views.ExportEventsView.as_view(), name='export_events'),
]