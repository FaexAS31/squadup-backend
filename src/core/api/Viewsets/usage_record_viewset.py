import logging
from rest_framework import viewsets
from api.models import UsageRecord
from api.Serializers.usage_record_serializer import UsageRecordSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['UsageRecords'])
class UsageRecordViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para UsageRecords."""
    queryset = UsageRecord.objects.all()
    serializer_class = UsageRecordSerializer
