from rest_framework import serializers
from api.models import SoloMatch


class SoloMatchSerializer(serializers.HyperlinkedModelSerializer):
    user_a_name = serializers.SerializerMethodField()
    user_b_name = serializers.SerializerMethodField()
    user_a_photo = serializers.SerializerMethodField()
    user_b_photo = serializers.SerializerMethodField()
    coordination_id = serializers.SerializerMethodField()

    class Meta:
        model = SoloMatch
        fields = [
            'url', 'id', 'user_a', 'user_b',
            'user_a_name', 'user_b_name',
            'user_a_photo', 'user_b_photo',
            'status', 'matched_at', 'expires_at',
            'blitz', 'chat', 'group', 'coordination_id',
            'group_confirmed_a', 'group_confirmed_b',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'user_a', 'user_b', 'status',
            'matched_at', 'blitz', 'chat', 'group',
            'group_confirmed_a', 'group_confirmed_b',
            'created_at', 'updated_at',
        ]

    def get_user_a_name(self, obj):
        u = obj.user_a
        return f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email

    def get_user_b_name(self, obj):
        u = obj.user_b
        return f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email

    def get_user_a_photo(self, obj):
        return getattr(obj.user_a, 'profile_photo', None) or ''

    def get_user_b_photo(self, obj):
        return getattr(obj.user_b, 'profile_photo', None) or ''

    def get_coordination_id(self, obj):
        coord = getattr(obj, 'coordination', None)
        return coord.id if coord else None
