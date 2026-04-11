import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from api.models import MatchMute
from api.Serializers.match_mute_serializer import MatchMuteSerializer

logger = logging.getLogger('api')


@extend_schema(tags=['Match Mutes'])
class MatchMuteViewSet(viewsets.ModelViewSet):
    """User's muted matches."""

    serializer_class = MatchMuteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return MatchMute.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        mute = serializer.save(user=self.request.user)
        logger.info(f"User {self.request.user.id} muted match {mute.match_id}")
