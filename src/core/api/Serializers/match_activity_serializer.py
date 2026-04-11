from rest_framework import serializers
from api.models import MatchActivity


class MatchActivitySerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    triggered_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MatchActivity
        fields = '__all__'

    def get_triggered_by_name(self, obj):
        if obj.triggered_by:
            name = f'{obj.triggered_by.first_name} {obj.triggered_by.last_name}'.strip()
            return name or obj.triggered_by.email
        return None