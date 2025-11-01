# myapp/serializers.py
from rest_framework import serializers
from .models import BotStatistics, Meeting, MeetingInvitation


class BotStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BotStatistics
        fields = '__all__'
        read_only_fields = ('date',)


class MeetingSerializer(serializers.ModelSerializer):
    organizer_username = serializers.CharField(source='organizer.username', read_only=True)

    class Meta:
        model = Meeting
        fields = [
            'id', 'title', 'description', 'meeting_date', 'meeting_time',
            'duration', 'organizer', 'organizer_username', 'participants',
            'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ('created_at', 'updated_at')


class MeetingInvitationSerializer(serializers.ModelSerializer):
    meeting_title = serializers.CharField(source='meeting.title', read_only=True)
    participant_username = serializers.CharField(source='participant.username', read_only=True)

    class Meta:
        model = MeetingInvitation
        fields = [
            'id', 'meeting', 'meeting_title', 'participant', 'participant_username',
            'status', 'responded_at', 'created_at'
        ]
        read_only_fields = ('responded_at', 'created_at')


class EventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_name = serializers.CharField()
    event_date = serializers.CharField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_public = serializers.BooleanField()


class UserSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    username = serializers.CharField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField(allow_null=True)
    is_registered = serializers.BooleanField()