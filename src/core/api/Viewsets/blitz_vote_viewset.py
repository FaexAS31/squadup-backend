import logging
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from drf_spectacular.utils import extend_schema

from api.models import BlitzVote, GroupMembership
from api.Serializers.blitz_vote_serializer import BlitzVoteSerializer
from api.Viewsets.blitz_interaction_viewset import _broadcast_vote_update

logger = logging.getLogger('api')


@extend_schema(tags=['BlitzVotes'])
class BlitzVoteViewSet(viewsets.ModelViewSet):
    """
    ViewSet for BlitzVote model.

    Supports filtering by:
    - interaction: The interaction this vote belongs to
    - vote: Vote status (pending, approved, rejected)
    - interaction__from_blitz: Filter by blitz ID

    Returns ALL votes for interactions where the current user is a member
    of the from_blitz group, so the consensus screen can display group progress.
    """
    serializer_class = BlitzVoteSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['interaction', 'vote', 'interaction__from_blitz']

    def get_queryset(self):
        user = self.request.user
        # Return all votes for interactions where the user is a group member,
        # so the consensus screen can show every member's vote status.
        user_group_ids = GroupMembership.objects.filter(
            user=user,
        ).values_list('group_id', flat=True)
        return BlitzVote.objects.filter(
            interaction__from_blitz__group_id__in=user_group_ids,
        ).select_related(
            'interaction',
            'interaction__from_blitz',
            'interaction__from_blitz__group',
            'interaction__to_blitz',
            'interaction__to_blitz__group',
            'user',
        )

    @extend_schema(
        request={'type': 'object', 'properties': {
            'vote': {'type': 'string', 'enum': ['approved', 'rejected']},
        }},
        responses={200: BlitzVoteSerializer},
    )
    @action(detail=True, methods=['post'])
    def cast_vote(self, request, pk=None):
        """
        Cast a vote on a BlitzInteraction.

        POST body:
        - vote: 'approved' or 'rejected'
        """
        vote_value = request.data.get('vote')
        if vote_value not in ('approved', 'rejected'):
            return Response(
                {'error': 'vote must be "approved" or "rejected"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            try:
                vote_obj = BlitzVote.objects.select_for_update().select_related(
                    'interaction',
                    'interaction__from_blitz',
                    'interaction__from_blitz__group',
                    'interaction__to_blitz',
                    'interaction__to_blitz__group',
                    'user',
                ).get(pk=pk, user=self.request.user)
            except BlitzVote.DoesNotExist:
                return Response(
                    {'error': 'Vote not found or not yours'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if vote_obj.vote != 'pending':
                return Response(
                    {'error': 'Vote already cast'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check blitz not expired
            blitz = vote_obj.interaction.from_blitz
            if blitz.is_expired:
                return Response(
                    {'error': 'Blitz session has expired'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vote_obj.vote = vote_value
            vote_obj.voted_at = timezone.now()
            vote_obj.save(update_fields=['vote', 'voted_at'])

        # Broadcast updated state (outside transaction to avoid holding lock)
        _broadcast_vote_update(blitz.id, vote_obj.interaction, 'vote_cast')

        serializer = self.get_serializer(vote_obj)
        data = serializer.data
        data['consensus_status'] = vote_obj.interaction.consensus_status
        return Response(data)
