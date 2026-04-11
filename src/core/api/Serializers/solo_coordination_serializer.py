from rest_framework import serializers
from api.models import SoloCoordination


class SoloCoordinationSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = SoloCoordination
        fields = [
            'url', 'id', 'solo_match',
            'user_a_categories', 'user_a_time', 'user_a_zone', 'user_a_ready',
            'user_b_categories', 'user_b_time', 'user_b_zone', 'user_b_ready',
            'status', 'created_at', 'expires_at',
        ]
        read_only_fields = [
            'solo_match', 'status', 'created_at', 'expires_at',
            'user_a_ready', 'user_b_ready',
        ]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request and hasattr(self, 'instance') and self.instance:
            user = request.user
            solo_match = self.instance.solo_match
            # Make the OTHER user's fields read-only
            if user == solo_match.user_a:
                for f in ('user_b_categories', 'user_b_time', 'user_b_zone'):
                    fields[f].read_only = True
            elif user == solo_match.user_b:
                for f in ('user_a_categories', 'user_a_time', 'user_a_zone'):
                    fields[f].read_only = True
        return fields
