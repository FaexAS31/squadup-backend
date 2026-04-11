from rest_framework import serializers
from api.models import Friendship, User


class UserInlineSerializer(serializers.ModelSerializer):
    """Lightweight read-only user data embedded in friendship responses."""

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'profile_photo']
        read_only_fields = fields


class FriendshipSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    user_from_detail = UserInlineSerializer(source='user_from', read_only=True)
    user_to_detail = UserInlineSerializer(source='user_to', read_only=True)

    class Meta:
        model = Friendship
        fields = '__all__'
