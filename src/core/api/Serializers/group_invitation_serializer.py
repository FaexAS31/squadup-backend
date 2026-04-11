from rest_framework import serializers
from api.models import GroupInvitation


class GroupInvitationSerializer(serializers.HyperlinkedModelSerializer):
    inviter_name = serializers.SerializerMethodField()
    invitee_name = serializers.SerializerMethodField()
    invitee_id = serializers.IntegerField(source='invitee.id', read_only=True)
    group_name = serializers.SerializerMethodField()

    class Meta:
        model = GroupInvitation
        fields = [
            'url', 'id', 'group', 'inviter', 'invitee', 'invitee_id',
            'inviter_name', 'invitee_name', 'group_name',
            'status', 'created_at', 'responded_at',
        ]
        read_only_fields = [
            'inviter', 'invitee', 'status', 'created_at', 'responded_at',
        ]

    def get_inviter_name(self, obj):
        u = obj.inviter
        return f"{u.first_name} {u.last_name}".strip() or u.email

    def get_invitee_name(self, obj):
        u = obj.invitee
        return f"{u.first_name} {u.last_name}".strip() or u.email

    def get_group_name(self, obj):
        return obj.group.name
