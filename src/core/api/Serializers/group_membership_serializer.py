from rest_framework import serializers
from api.models import GroupMembership, User


class UserInlineSerializer(serializers.ModelSerializer):
    """Lightweight read-only user data embedded in membership responses."""

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'profile_photo']
        read_only_fields = fields


class GroupMembershipSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    user_detail = UserInlineSerializer(source='user', read_only=True)

    class Meta:
        model = GroupMembership
        fields = '__all__'
