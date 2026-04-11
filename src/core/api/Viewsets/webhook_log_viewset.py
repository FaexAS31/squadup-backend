import logging
from rest_framework import viewsets
from api.models import WebhookLog
from api.Serializers.webhook_log_serializer import WebhookLogSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['WebhookLogs'])
class WebhookLogViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para WebhookLogs."""
    queryset = WebhookLog.objects.all()
    serializer_class = WebhookLogSerializer
