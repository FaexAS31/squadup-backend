from rest_framework import serializers
from api.models import Match, MatchMute, GroupMembership


class MatchSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Match model.

    Exposes computed properties from the model:
    - days_together: Days since the match was created
    - common_interests: List of shared interests between both groups
    - common_interests_count: Count of common interests
    - is_muted: Whether the current user has muted this match
    - other_group_name: Name of the other group (relative to requesting user)
    - other_group_member_count: Member count of the other group
    """
    id = serializers.ReadOnlyField()
    days_together = serializers.SerializerMethodField()
    common_interests = serializers.SerializerMethodField()
    common_interests_count = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()
    my_group_name = serializers.SerializerMethodField()
    other_group_name = serializers.SerializerMethodField()
    other_group_member_count = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = '__all__'

    def _resolve_groups(self, obj):
        """Return (my_group, other_group) relative to the requesting user."""
        g1 = obj.blitz_1.group if hasattr(obj.blitz_1, 'group') else None
        g2 = obj.blitz_2.group if hasattr(obj.blitz_2, 'group') else None
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return (g1, g2)
        user = request.user
        if g1 and g1.members.filter(id=user.id).exists():
            return (g1, g2)
        return (g2, g1)

    def get_my_group_name(self, obj):
        my_group, _ = self._resolve_groups(obj)
        return my_group.name if my_group else None

    def get_other_group_name(self, obj):
        _, other_group = self._resolve_groups(obj)
        return other_group.name if other_group else None

    def get_other_group_member_count(self, obj):
        _, other_group = self._resolve_groups(obj)
        return other_group.member_count if other_group else 0

    def get_days_together(self, obj):
        """Return days since match was created."""
        return obj.days_together

    def get_common_interests(self, obj):
        """Return list of interests shared by both groups."""
        return obj.common_interests

    def get_common_interests_count(self, obj):
        """Return count of common interests."""
        return obj.common_interests_count

    def get_is_muted(self, obj):
        """Return whether the current user has muted this match."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return MatchMute.objects.filter(user=request.user, match=obj).exists()
