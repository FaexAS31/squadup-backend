import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter

from django.db.models import Q, Exists, OuterRef, Subquery

from api.models import Blitz, BlitzInteraction, BlitzVote, GroupMembership, Notification, Match, Chat, MatchActivity
from api.Serializers.blitz_interaction_serializer import BlitzInteractionSerializer

logger = logging.getLogger('api')


def _broadcast_vote_update(blitz_id, interaction, event_type='vote_update'):
    """Broadcast a vote update to the blitz voting WebSocket room."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        room_group = f'blitz_voting_{blitz_id}'
        votes = interaction.votes.select_related('user').all()
        async_to_sync(channel_layer.group_send)(
            room_group,
            {
                'type': 'vote_update',
                'data': {
                    'event': event_type,
                    'interaction_id': interaction.id,
                    'to_blitz_id': interaction.to_blitz_id,
                    'consensus_status': interaction.consensus_status,
                    'votes': [
                        {
                            'id': v.id,
                            'user_id': v.user_id,
                            'user_name': v.user.first_name or v.user.email,
                            'vote': v.vote,
                        }
                        for v in votes
                    ],
                },
            },
        )
    except Exception as e:
        logger.warning(f"Failed to broadcast vote update: {e}")


@extend_schema(tags=['Blitzs Interactions'])
class BlitzInteractionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for BlitzInteraction model.

    Supports filtering by:
    - from_blitz: The blitz that initiated the interaction
    - to_blitz: The blitz that received the interaction
    - interaction_type: Type of action (like, skip)
    - requires_consensus: Whether group consensus is required

    Example queries:
    - GET /api/blitzinteractions/?from_blitz=1&to_blitz=2
    - GET /api/blitzinteractions/?interaction_type=like
    """
    queryset = BlitzInteraction.objects.all()
    serializer_class = BlitzInteractionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['from_blitz', 'to_blitz', 'interaction_type', 'requires_consensus']

    def get_queryset(self):
        return BlitzInteraction.objects.all().select_related(
            'from_blitz', 'from_blitz__group',
            'to_blitz', 'to_blitz__group'
        )

    def create(self, request, *args, **kwargs):
        logger.info(f"Initiating Blitz interaction event by user: {request.user}")

        # Check freemium swipe limit per blitz
        user = request.user
        limit = user.get_feature_limit('max_swipes_per_blitz')
        if limit != -1:
            from_blitz_url = request.data.get('from_blitz', '')
            if from_blitz_url:
                import re
                pk_match = re.search(r'/(\d+)/?$', str(from_blitz_url))
                if pk_match:
                    from_blitz_id = int(pk_match.group(1))
                    swipe_count = BlitzInteraction.objects.filter(
                        from_blitz_id=from_blitz_id,
                    ).count()
                    if swipe_count >= limit:
                        from rest_framework import status as http_status
                        return Response(
                            {
                                'error': 'limit_reached',
                                'feature': 'max_swipes_per_blitz',
                                'limit': limit,
                                'current': swipe_count,
                            },
                            status=http_status.HTTP_403_FORBIDDEN,
                        )

        try:
            response = super().create(request, *args, **kwargs)
            # HyperlinkedModelSerializer returns 'url' not 'id' — extract pk from URL
            interaction_url = response.data.get('url', '')
            import re
            pk_match = re.search(r'/(\d+)/$', interaction_url)
            interaction_pk = int(pk_match.group(1)) if pk_match else None
            if not interaction_pk:
                logger.error(f"Could not extract ID from interaction URL: {interaction_url}")
                return response
            interaction = BlitzInteraction.objects.select_related(
                'from_blitz', 'from_blitz__group',
            ).get(pk=interaction_pk)

            blitz = interaction.from_blitz
            is_democratic_like = (
                blitz.swipe_mode == Blitz.SwipeMode.DEMOCRATIC
                and interaction.interaction_type == 'like'
            )

            if is_democratic_like:
                interaction.requires_consensus = True
                interaction.save(update_fields=['requires_consensus'])

                # Create votes for all group members
                members = GroupMembership.objects.filter(
                    group=blitz.group,
                ).select_related('user')
                proposer = request.user
                vote_objects = []
                for m in members:
                    vote_objects.append(BlitzVote(
                        interaction=interaction,
                        user=m.user,
                        vote='approved' if m.user_id == proposer.id else 'pending',
                        voted_at=timezone.now() if m.user_id == proposer.id else None,
                    ))
                BlitzVote.objects.bulk_create(vote_objects)

                # Broadcast via WebSocket
                _broadcast_vote_update(blitz.id, interaction, 'vote_requested')

                # Send push notifications to other group members
                for m in members:
                    if m.user_id != proposer.id:
                        Notification.objects.create(
                            user=m.user,
                            notification_type='blitz_vote_request',
                            title='Votación de Blitz',
                            body=f'{proposer.first_name} propuso conectar con un grupo. ¡Vota ahora!',
                            data={
                                'interaction_id': interaction.id,
                                'blitz_id': blitz.id,
                                'action': 'open_blitz',
                                'sender_id': proposer.id,
                            },
                        )

                # Refresh response data with updated fields
                response.data['requires_consensus'] = True
                response.data['consensus_status'] = interaction.consensus_status

            # Always include 'id' in response (HyperlinkedModelSerializer only returns 'url')
            response.data['id'] = interaction.id
            logger.info(f"Blitz interaction created successfully: ID {interaction.id}")
            return response
        except Exception as e:
            logger.error(f"Failed to create Blitz interaction: {str(e)}")
            raise e

    @extend_schema(
        parameters=[
            OpenApiParameter(name='our_blitz', description='Our blitz ID', required=True, type=int),
            OpenApiParameter(name='their_blitz', description='Their blitz ID', required=True, type=int),
        ],
        responses={200: {'type': 'object', 'properties': {
            'is_mutual': {'type': 'boolean'},
            'our_interaction': {'type': 'object'},
            'their_interaction': {'type': 'object'},
        }}}
    )
    @action(detail=False, methods=['get'])
    def check_mutual(self, request):
        """
        Check if two blitzes have mutual likes with approved consensus.

        Query params:
        - our_blitz: ID of our blitz
        - their_blitz: ID of the other blitz

        Returns:
        - is_mutual: True if both have liked each other with approved consensus
        - our_interaction: Our interaction details (if exists)
        - their_interaction: Their interaction details (if exists)
        """
        our_blitz_id = request.query_params.get('our_blitz')
        their_blitz_id = request.query_params.get('their_blitz')

        if not our_blitz_id or not their_blitz_id:
            return Response({
                'error': 'Both our_blitz and their_blitz parameters are required'
            }, status=400)

        # Check our like towards them
        our_interaction = BlitzInteraction.objects.filter(
            from_blitz_id=our_blitz_id,
            to_blitz_id=their_blitz_id,
            interaction_type='like',
        ).select_related('from_blitz', 'to_blitz').first()

        # Check their like towards us
        their_interaction = BlitzInteraction.objects.filter(
            from_blitz_id=their_blitz_id,
            to_blitz_id=our_blitz_id,
            interaction_type='like',
        ).select_related('from_blitz', 'to_blitz').first()

        # Check if both interactions exist and have approved consensus
        our_approved = (
            our_interaction is not None and
            our_interaction.consensus_status == 'approved'
        )
        their_approved = (
            their_interaction is not None and
            their_interaction.consensus_status == 'approved'
        )

        is_mutual = our_approved and their_approved

        return Response({
            'is_mutual': is_mutual,
            'our_interaction': BlitzInteractionSerializer(
                our_interaction,
                context={'request': request}
            ).data if our_interaction else None,
            'our_consensus_status': our_interaction.consensus_status if our_interaction else None,
            'their_interaction': BlitzInteractionSerializer(
                their_interaction,
                context={'request': request}
            ).data if their_interaction else None,
            'their_consensus_status': their_interaction.consensus_status if their_interaction else None,
        })

    @extend_schema(
        request={'type': 'object', 'properties': {
            'our_blitz': {'type': 'integer'},
            'their_blitz': {'type': 'integer'},
        }},
        responses={200: {'type': 'object', 'properties': {
            'match_id': {'type': 'integer'},
            'chat_id': {'type': 'integer'},
            'created': {'type': 'boolean'},
        }}}
    )
    @action(detail=False, methods=['post'], url_path='confirm-match')
    def confirm_match(self, request):
        """
        Create a Match + Chat after a mutual like is detected.

        Idempotent: if the match already exists, returns the existing IDs
        with created=false.
        """
        our_blitz_id = request.data.get('our_blitz')
        their_blitz_id = request.data.get('their_blitz')

        if not our_blitz_id or not their_blitz_id:
            return Response(
                {'error': 'Both our_blitz and their_blitz are required'},
                status=400,
            )

        # Verify both interactions exist and are approved
        # NOTE: consensus_status is a @property, not a DB field — must check in Python
        our_interaction = BlitzInteraction.objects.filter(
            from_blitz_id=our_blitz_id,
            to_blitz_id=their_blitz_id,
            interaction_type='like',
        ).prefetch_related('votes').first()
        their_interaction = BlitzInteraction.objects.filter(
            from_blitz_id=their_blitz_id,
            to_blitz_id=our_blitz_id,
            interaction_type='like',
        ).prefetch_related('votes').first()

        if (
            not our_interaction or not their_interaction
            or our_interaction.consensus_status != 'approved'
            or their_interaction.consensus_status != 'approved'
        ):
            return Response(
                {'error': 'Mutual approved interactions not found'},
                status=400,
            )

        # Normalize ordering (lower ID = blitz_1) to prevent duplicates
        blitz_a_id = min(int(our_blitz_id), int(their_blitz_id))
        blitz_b_id = max(int(our_blitz_id), int(their_blitz_id))

        with transaction.atomic():
            # Lock the blitzes to prevent concurrent match creation
            blitz_a = Blitz.objects.select_for_update().select_related('group').get(pk=blitz_a_id)
            blitz_b = Blitz.objects.select_for_update().select_related('group').get(pk=blitz_b_id)

            match, created = Match.objects.get_or_create(
                blitz_1_id=blitz_a_id,
                blitz_2_id=blitz_b_id,
                defaults={'status': 'active'},
            )

            if not created:
                # Match already exists (concurrent request created it first)
                # Return the existing match data instead of creating duplicates
                return Response({
                    'match_id': match.id,
                    'chat_id': match.chat_id,
                    'created': False,
                })

            # Only create Chat if we created the Match (first request wins)
            chat = Chat.objects.create()

            member_user_ids = set()
            for grp in [blitz_a.group, blitz_b.group]:
                if grp:
                    ids = GroupMembership.objects.filter(group=grp).values_list('user_id', flat=True)
                    member_user_ids.update(ids)

            if member_user_ids:
                chat.participants.add(*member_user_ids)

            match.chat = chat
            match.save(update_fields=['chat'])

            # Auto-create timeline activity
            MatchActivity.objects.create(
                match=match,
                activity_type='match_created',
                triggered_by=request.user,
                description=f'Match creado entre {blitz_a.group.name} y {blitz_b.group.name}',
            )
            MatchActivity.objects.create(
                match=match,
                activity_type='chat_started',
                triggered_by=request.user,
                description='Chat del grupo creado',
            )

            # Notify all members about the new match
            for user_id in member_user_ids:
                if user_id != request.user.id:
                    # Determine the "other" group name for this user
                    is_in_a = blitz_a.group and blitz_a.group.members.filter(id=user_id).exists()
                    other_name = blitz_b.group.name if is_in_a else blitz_a.group.name
                    Notification.objects.create(
                        user_id=user_id,
                        notification_type='blitz_match',
                        title='¡Nuevo Match!',
                        body=f'Hicieron match con {other_name}. ¡Salúdalos!',
                        data={'match_id': match.id, 'action': 'open_match'},
                    )

        return Response({
            'match_id': match.id,
            'chat_id': match.chat_id,
            'created': created,
        })

    @extend_schema(
        responses={200: {'type': 'array', 'items': {'type': 'object', 'properties': {
            'id': {'type': 'integer'},
            'to_group_name': {'type': 'string'},
            'to_group_member_count': {'type': 'integer'},
            'created_at': {'type': 'string', 'format': 'date-time'},
            'from_blitz_id': {'type': 'integer'},
            'to_blitz_id': {'type': 'integer'},
        }}}}
    )
    @action(detail=False, methods=['get'], url_path='pending-likes')
    def pending_likes(self, request):
        """
        Returns sent likes from the current user's blitzes that have NOT
        been reciprocated (no matching like back, and no Match created).
        """
        user = request.user

        # Subquery: reciprocal like exists?
        reciprocal = BlitzInteraction.objects.filter(
            from_blitz_id=OuterRef('to_blitz_id'),
            to_blitz_id=OuterRef('from_blitz_id'),
            interaction_type='like',
        )

        # Subquery: match already created for this blitz pair?
        match_exists = Match.objects.filter(
            Q(blitz_1_id=OuterRef('from_blitz_id'), blitz_2_id=OuterRef('to_blitz_id')) |
            Q(blitz_1_id=OuterRef('to_blitz_id'), blitz_2_id=OuterRef('from_blitz_id'))
        )

        interactions = (
            BlitzInteraction.objects
            .filter(
                from_blitz__group__members=user,
                interaction_type='like',
            )
            .exclude(Exists(match_exists))
            .annotate(has_reciprocal=Exists(reciprocal))
            .filter(has_reciprocal=False)
            .select_related('to_blitz__group')
            .order_by('-created_at')
        )

        results = []
        for i in interactions:
            group = i.to_blitz.group
            results.append({
                'id': i.id,
                'to_group_name': group.name if group else 'Grupo',
                'to_group_member_count': group.member_count if group else 0,
                'created_at': i.created_at.isoformat(),
                'from_blitz_id': i.from_blitz_id,
                'to_blitz_id': i.to_blitz_id,
            })

        return Response(results)
