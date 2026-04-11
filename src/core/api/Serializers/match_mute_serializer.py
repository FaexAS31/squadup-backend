from rest_framework import serializers
from api.models import MatchMute


class MatchMuteSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = MatchMute
        fields = '__all__'
        read_only_fields = ('user', 'muted_at')

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
