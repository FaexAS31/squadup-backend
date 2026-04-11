from rest_framework import serializers
from api.models import WebhookLog

class WebhookLogSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = WebhookLog
        fields = '__all__'