import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from drf_spectacular.utils import extend_schema

from api.models import SoloMatch, SoloCoordination, Friendship, User, Chat, Group, GroupMembership  # noqa: F401
from api.Serializers.solo_match_serializer import SoloMatchSerializer

logger = logging.getLogger('api')


class SoloLikeThrottle(UserRateThrottle):
    rate = '200/day'


@extend_schema(tags=['SoloMatchs'])
class SoloMatchViewSet(viewsets.ModelViewSet):
    serializer_class = SoloMatchSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        qs = SoloMatch.objects.filter(
            Q(user_a=user) | Q(user_b=user)
        ).select_related('user_a', 'user_b', 'blitz')

        # Filter by status
        s = self.request.query_params.get('status')
        if s:
            qs = qs.filter(status=s)

        # Filter by direction
        direction = self.request.query_params.get('direction')
        if direction == 'sent':
            qs = qs.filter(user_a=user)
        elif direction == 'received':
            qs = qs.filter(user_b=user)

        return qs.order_by('-created_at')

    @extend_schema(
        description="Swipe right on a target user (Solo Mode).",
        request=None,
        responses={200: dict},
    )
    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated],
        throttle_classes=[SoloLikeThrottle],
    )
    def swipe(self, request):
        user = request.user

        # --- Freemium: solo connections limit ---
        limit = user.get_feature_limit('max_solo_connections')
        if limit != -1:
            active_count = SoloMatch.objects.filter(
                Q(user_a=user) | Q(user_b=user),
                status__in=['pending', 'matched', 'coordinating', 'ready', 'started'],
            ).count()
            if active_count >= limit:
                return Response(
                    {
                        'error': 'limit_reached',
                        'feature': 'max_solo_connections',
                        'limit': limit,
                        'current': active_count,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        target_id = request.data.get('target_user_id')

        if not target_id:
            return Response(
                {'error': 'target_user_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if str(target_id) == str(user.id):
            return Response(
                {'error': 'Cannot swipe on yourself'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check target exists
        try:
            target = User.objects.get(id=target_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check blocked
        if Friendship.objects.filter(
            Q(user_from=user, user_to=target, status='blocked') |
            Q(user_from=target, user_to=user, status='blocked')
        ).exists():
            return Response(
                {'error': 'Cannot connect with this user'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 7-day cooldown: reject re-swipe if expired SoloMatch exists within 7 days
        cooldown_cutoff = timezone.now() - timedelta(days=7)
        if SoloMatch.objects.filter(
            Q(user_a=user, user_b=target) | Q(user_a=target, user_b=user),
            status__in=['expired', 'cancelled'],
            updated_at__gte=cooldown_cutoff,
        ).exists():
            return Response(
                {'error': 'Please wait before reconnecting with this user'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        with transaction.atomic():
            # Use get_or_create to handle duplicate swipes atomically
            solo_match, created = SoloMatch.objects.get_or_create(
                user_a=user,
                user_b=target,
                status=SoloMatch.Status.PENDING,
                defaults={
                    'expires_at': timezone.now() + timedelta(hours=24),
                }
            )

            if not created:
                # Already swiped — return existing state
                return Response({
                    'is_match': solo_match.status == SoloMatch.Status.MATCHED,
                    'solo_match_id': solo_match.id,
                    'status': solo_match.status,
                })

            # Also check for existing non-pending active match in this direction
            existing_active = SoloMatch.objects.filter(
                user_a=user, user_b=target
            ).exclude(
                status__in=['expired', 'cancelled', 'pending']
            ).exclude(pk=solo_match.pk).first()

            if existing_active:
                # Already have an active connection — roll back the new one
                solo_match.delete()
                return Response(
                    {'error': 'You already have an active connection with this user',
                     'solo_match_id': existing_active.id,
                     'status': existing_active.status},
                    status=status.HTTP_409_CONFLICT,
                )

            # Check for reverse match WITH LOCK to prevent TOCTOU
            reverse = SoloMatch.objects.select_for_update().filter(
                user_a=target,
                user_b=user,
                status=SoloMatch.Status.PENDING,
            ).first()

            is_match = False
            chat_id = None

            if reverse:
                # Mutual match — create chat atomically
                now = timezone.now()

                chat = Chat.objects.create(
                    metadata={'solo_mode': True},
                )
                chat.participants.add(user, target)

                # Keep only the new solo match as the canonical matched record.
                # Delete the reverse pending — both users can see this one
                # via Q(user_a=user) | Q(user_b=user).
                solo_match.status = SoloMatch.Status.MATCHED
                solo_match.matched_at = now
                solo_match.chat = chat
                solo_match.save()

                reverse.delete()

                is_match = True
                chat_id = chat.id
                logger.info(
                    f"Solo Mode mutual match: {user.id} <-> {target.id} "
                    f"(SoloMatch {solo_match.id}, Chat {chat.id})"
                )

        return Response({
            'is_match': is_match,
            'solo_match_id': solo_match.id,
            'status': solo_match.status,
            'chat_id': chat_id,
        })

    @extend_schema(description="Confirm group creation for a matched solo pair.")
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def confirm_group(self, request, pk=None):
        user = request.user
        try:
            solo_match = SoloMatch.objects.get(
                Q(user_a=user) | Q(user_b=user),
                pk=pk,
                status=SoloMatch.Status.MATCHED,
            )
        except SoloMatch.DoesNotExist:
            return Response(
                {'error': 'Matched solo match not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # If group already exists, return it
        if solo_match.group and solo_match.group.description != 'Solo Mode duo':
            return Response({
                'confirmed_a': solo_match.group_confirmed_a,
                'confirmed_b': solo_match.group_confirmed_b,
                'group_created': True,
                'group_id': solo_match.group.id,
            })

        # Set the current user's confirmation flag
        is_user_a = (user.id == solo_match.user_a_id)
        if is_user_a:
            solo_match.group_confirmed_a = True
        else:
            solo_match.group_confirmed_b = True
        solo_match.save(update_fields=['group_confirmed_a', 'group_confirmed_b', 'updated_at'])

        # Check if both confirmed → auto-create group
        group_created = False
        group_id = None
        if solo_match.group_confirmed_a and solo_match.group_confirmed_b:
            target = solo_match.user_b if is_user_a else solo_match.user_a
            group_name = f"{solo_match.user_a.first_name or 'User'} & {solo_match.user_b.first_name or 'User'}"
            group = Group.objects.create(
                name=group_name,
                is_active=True,
            )
            group.members.add(solo_match.user_a, solo_match.user_b)
            GroupMembership.objects.filter(group=group, user=solo_match.user_a).update(role='admin')

            solo_match.group = group
            solo_match.save(update_fields=['group', 'updated_at'])

            group_created = True
            group_id = group.id
            logger.info(
                f"Solo Mode group created: {solo_match.user_a_id} & {solo_match.user_b_id} "
                f"(Group {group.id}, SoloMatch {solo_match.id})"
            )

        return Response({
            'confirmed_a': solo_match.group_confirmed_a,
            'confirmed_b': solo_match.group_confirmed_b,
            'group_created': group_created,
            'group_id': group_id,
        })

    @extend_schema(description="Cancel a solo match.")
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def cancel(self, request, pk=None):
        user = request.user
        try:
            solo_match = SoloMatch.objects.get(
                Q(user_a=user) | Q(user_b=user),
                pk=pk,
            )
        except SoloMatch.DoesNotExist:
            return Response(
                {'error': 'Solo match not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if solo_match.status in ['started', 'expired', 'cancelled']:
            return Response(
                {'error': f'Cannot cancel a {solo_match.status} match'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        solo_match.status = SoloMatch.Status.CANCELLED
        solo_match.save()

        return Response({'status': 'cancelled', 'solo_match_id': solo_match.id})
