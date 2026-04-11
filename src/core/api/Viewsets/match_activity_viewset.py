import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from api.models import MatchActivity
from api.Serializers.match_activity_serializer import MatchActivitySerializer

logger = logging.getLogger('api')


@extend_schema(tags=['MatchActivities'])
class MatchActivityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for MatchActivity model.

    Supports filtering by:
    - match: Filter activities by match URL or ID
    - activity_type: Filter by activity type

    Example: GET /api/match-activities/?match=1
    """
    queryset = MatchActivity.objects.all()
    serializer_class = MatchActivitySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['match', 'activity_type', 'triggered_by']

    def get_queryset(self):
        """
        Optionally filter by match ID from query params.
        Supports both match ID and match URL filtering.
        """
        queryset = MatchActivity.objects.all().select_related(
            'match', 'triggered_by'
        ).order_by('-created_at')

        # Support filtering by match_id query param as well
        match_id = self.request.query_params.get('match_id')
        if match_id:
            queryset = queryset.filter(match_id=match_id)

        return queryset
