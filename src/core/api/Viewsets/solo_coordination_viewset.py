import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from api.models import (
    SoloCoordination, SoloMatch, Group, GroupMembership, Blitz,
)
from api.Serializers.solo_coordination_serializer import SoloCoordinationSerializer

logger = logging.getLogger('api')


def _get_user_side(coordination, user):
    """Return 'a' or 'b' depending on which side the user is on."""
    sm = coordination.solo_match
    if user.id == sm.user_a_id:
        return 'a'
    elif user.id == sm.user_b_id:
        return 'b'
    return None


def _broadcast_coordination_update(coordination, event_type, data=None):
    """Broadcast update to the coordination WebSocket room."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        room_group = f'coordination_{coordination.solo_match_id}'
        async_to_sync(channel_layer.group_send)(
            room_group,
            {
                'type': 'coordination_update',
                'data': {
                    'event': event_type,
                    'coordination_id': coordination.id,
                    'solo_match_id': coordination.solo_match_id,
                    'status': coordination.status,
                    'user_a_categories': coordination.user_a_categories,
                    'user_a_time': coordination.user_a_time,
                    'user_a_zone': coordination.user_a_zone,
                    'user_a_ready': coordination.user_a_ready,
                    'user_b_categories': coordination.user_b_categories,
                    'user_b_time': coordination.user_b_time,
                    'user_b_zone': coordination.user_b_zone,
                    'user_b_ready': coordination.user_b_ready,
                    **(data or {}),
                },
            },
        )
    except Exception as e:
        logger.warning(f"Failed to broadcast coordination update: {e}")


@extend_schema(tags=['SoloCoordinations'])
class SoloCoordinationViewSet(viewsets.ModelViewSet):
    serializer_class = SoloCoordinationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        return SoloCoordination.objects.filter(
            Q(solo_match__user_a=user) | Q(solo_match__user_b=user)
        ).select_related('solo_match', 'solo_match__user_a', 'solo_match__user_b')

    @extend_schema(description="Update preferences for the coordination room.")
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def update_preferences(self, request, pk=None):
        user = request.user

        with transaction.atomic():
            try:
                coordination = SoloCoordination.objects.select_for_update().get(pk=pk)
            except SoloCoordination.DoesNotExist:
                return Response(
                    {'error': 'Coordination not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Verify the user is a participant
            sm = coordination.solo_match
            if user.id != sm.user_a_id and user.id != sm.user_b_id:
                return Response(
                    {'error': 'Not a participant'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if coordination.status not in ['waiting', 'both_ready']:
                return Response(
                    {'error': 'Coordination is no longer active'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            side = _get_user_side(coordination, user)
            if not side:
                return Response(
                    {'error': 'Not a participant'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Update the user's preferences
            prefix = f'user_{side}_'
            changed = False
            for field in ('categories', 'time', 'zone'):
                value = request.data.get(field)
                if value is not None:
                    setattr(coordination, f'{prefix}{field}', value)
                    changed = True

            if changed:
                # If user was ready and changes prefs, unset ready
                if getattr(coordination, f'{prefix}ready'):
                    setattr(coordination, f'{prefix}ready', False)
                    coordination.status = SoloCoordination.Status.WAITING

                coordination.save()

                # Update parent SoloMatch to coordinating if still matched
                if sm.status == SoloMatch.Status.MATCHED:
                    sm.status = SoloMatch.Status.COORDINATING
                    sm.save()

        _broadcast_coordination_update(coordination, 'preferences_updated') if changed else None

        serializer = self.get_serializer(coordination)
        return Response(serializer.data)

    @extend_schema(description="Mark the current user as ready.")
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def ready(self, request, pk=None):
        user = request.user

        with transaction.atomic():
            try:
                coordination = SoloCoordination.objects.select_for_update().get(pk=pk)
            except SoloCoordination.DoesNotExist:
                return Response(
                    {'error': 'Coordination not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Verify the user is a participant
            sm = coordination.solo_match
            if user.id != sm.user_a_id and user.id != sm.user_b_id:
                return Response(
                    {'error': 'Not a participant'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if coordination.status in ['started', 'expired']:
                return Response(
                    {'error': 'Coordination is no longer active'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            side = _get_user_side(coordination, user)
            if not side:
                return Response(
                    {'error': 'Not a participant'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            setattr(coordination, f'user_{side}_ready', True)

            # Check if both ready
            if coordination.user_a_ready and coordination.user_b_ready:
                coordination.status = SoloCoordination.Status.BOTH_READY
                sm = coordination.solo_match
                sm.status = SoloMatch.Status.READY
                sm.save()

            coordination.save()

        _broadcast_coordination_update(coordination, 'ready_updated')

        serializer = self.get_serializer(coordination)
        return Response(serializer.data)

    @extend_schema(description="Start the Blitz (both must be ready).")
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def start(self, request, pk=None):
        user = request.user

        with transaction.atomic():
            try:
                coordination = SoloCoordination.objects.select_for_update().get(pk=pk)
            except SoloCoordination.DoesNotExist:
                return Response(
                    {'error': 'Coordination not found'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if coordination.status != SoloCoordination.Status.BOTH_READY:
                return Response(
                    {'error': 'Both users must be ready'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            sm = coordination.solo_match
            user_a = sm.user_a
            user_b = sm.user_b

            # Create duo group
            group_name = f"{user_a.first_name or 'User'} & {user_b.first_name or 'User'}"
            group = Group.objects.create(
                name=group_name,
                description='Solo Mode duo',
                is_active=True,
            )
            group.members.add(user_a, user_b)
            GroupMembership.objects.filter(group=group, user=user_a).update(role='admin')

            # Combine categories from both users
            activities = list(set(
                coordination.user_a_categories + coordination.user_b_categories
            ))

            # Create Blitz
            blitz = Blitz.objects.create(
                group=group,
                leader=user,
                activity_type=activities[0] if activities else '',
                metadata={'activities': activities, 'solo_mode': True},
                expires_at=timezone.now() + timedelta(minutes=30),
            )

            # Update statuses
            sm.status = SoloMatch.Status.STARTED
            sm.blitz = blitz
            sm.save()

            coordination.status = SoloCoordination.Status.STARTED
            coordination.save()

        _broadcast_coordination_update(coordination, 'blitz_started', {
            'blitz_id': blitz.id,
            'group_id': group.id,
        })

        logger.info(
            f"Solo Mode Blitz started: {user_a.id} & {user_b.id} → "
            f"Group {group.id}, Blitz {blitz.id}"
        )

        return Response({
            'status': 'started',
            'blitz_id': blitz.id,
            'group_id': group.id,
            'solo_match_id': sm.id,
        })
