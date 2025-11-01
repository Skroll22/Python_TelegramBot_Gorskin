from django.contrib import admin

from myapp.models import Event, BotStatistics, Meeting, MeetingInvitation


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['event_name', 'event_date', 'user_id', 'is_public', 'shared_by']
    list_filter = ['event_date', 'is_public', 'user_id']
    search_fields = ['event_name', 'user_id']
    readonly_fields = ['id', 'user_id', 'event_name', 'event_date', 'is_public', 'shared_by']

    def has_add_permission(self, request):
        return True

@admin.register(BotStatistics)
class BotStatisticsAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_users', 'total_events', 'deleted_events', 'edited_events', 'active_users']
    list_filter = ['date']
    readonly_fields = ['date', 'total_users', 'total_events', 'deleted_events', 'edited_events', 'active_users']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ['title', 'meeting_date', 'meeting_time', 'organizer', 'status', 'created_at']
    list_filter = ['status', 'meeting_date', 'created_at']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'meeting_date'

@admin.register(MeetingInvitation)
class MeetingInvitationAdmin(admin.ModelAdmin):
    list_display = ['meeting', 'participant_id', 'status', 'created_at', 'responded_at']
    list_filter = ['status', 'created_at']
    search_fields = ['meeting__title', 'participant_id']
    readonly_fields = ['created_at']