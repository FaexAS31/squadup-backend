import logging
from rest_framework import viewsets
from api.models import ZoneStats
from api.Serializers.zone_stats_serializer import ZoneStatsSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['ZoneStats'])
class ZoneStatsViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para ZoneStats (Heat Map aggregations)."""
    queryset = ZoneStats.objects.all()
    serializer_class = ZoneStatsSerializer
