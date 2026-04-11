import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from api.models import Memory, MatchActivity, Notification, GroupMembership
from api.Serializers.memory_serializer import MemorySerializer

logger = logging.getLogger('api')


@extend_schema(tags=['Memories'])
class MemoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Memories.

    Supports filtering by:
    - match: Filter memories by match ID
    - memory_type: Filter by type (outing, photo, note)

    Auto-sets created_by to the requesting user on creation.
    """
    queryset = Memory.objects.all()
    serializer_class = MemorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['match', 'memory_type']

    def get_queryset(self):
        return Memory.objects.all().select_related(
            'match', 'created_by'
        ).prefetch_related('photos').order_by('-event_date')

    def perform_create(self, serializer):
        memory = serializer.save(created_by=self.request.user)
        # Refetch with related objects for notification queries
        memory = Memory.objects.select_related(
            'match', 'match__blitz_1', 'match__blitz_2',
            'match__blitz_1__group', 'match__blitz_2__group',
        ).get(pk=memory.pk)

        user = self.request.user
        name = user.first_name or user.email

        # Auto-create timeline activity
        MatchActivity.objects.create(
            match=memory.match,
            activity_type='memory_added',
            triggered_by=user,
            description=f'{name} agregó: {memory.title}',
        )
        # Notify match members
        member_ids = set()
        for blitz in [memory.match.blitz_1, memory.match.blitz_2]:
            if blitz and blitz.group:
                member_ids.update(
                    GroupMembership.objects.filter(group=blitz.group)
                    .values_list('user_id', flat=True)
                )
        for uid in member_ids:
            if uid != user.id:
                Notification.objects.create(
                    user_id=uid,
                    notification_type='memory_added',
                    title='Nuevo recuerdo',
                    body=f'{name} agregó un recuerdo: {memory.title}',
                    data={
                        'match_id': memory.match_id,
                        'action': 'open_match',
                        'sender_id': user.id,
                    },
                )

        logger.info(f"Memory created: {memory.id} for match {memory.match_id} by user {self.request.user.id}")
