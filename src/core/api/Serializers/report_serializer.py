from rest_framework import serializers
from api.models import Report


class ReportSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = Report
        fields = '__all__'
        read_only_fields = ('reporter', 'status', 'reviewed_at', 'reviewed_by')

    def create(self, validated_data):
        validated_data['reporter'] = self.context['request'].user
        return super().create(validated_data)
