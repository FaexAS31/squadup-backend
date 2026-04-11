import logging
import math
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q, Count
from django.utils import timezone
from api.models import Blitz, BlitzInteraction, Group, LocationLog, Profile
from api.Serializers.blitz_serializer import BlitzSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')


def _haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lng points in km."""
    R = 6371
    dlat = math.radians(float(lat2) - float(lat1))
    dlon = math.radians(float(lon2) - float(lon1))
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(float(lat1))) *
         math.cos(math.radians(float(lat2))) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@extend_schema(tags=['Blitzs'])
class BlitzViewSet(viewsets.ModelViewSet):
    serializer_class = BlitzSerializer

    def get_queryset(self):
        """A user can only see blitzes belonging to groups they are a member of."""
        user = self.request.user
        user_group_ids = user.groups.values_list('id', flat=True)
        return Blitz.objects.filter(group_id__in=user_group_ids)

    def create(self, request, *args, **kwargs):
        logger.info(f"Initiating Blitz event by user: {request.user}")

        # Check freemium weekly blitz limit
        user = request.user
        limit = user.get_feature_limit('max_blitz_per_week')
        if limit != -1:
            from datetime import timedelta
            week_ago = timezone.now() - timedelta(days=7)
            user_group_ids = list(
                user.groups.filter(is_active=True).values_list('id', flat=True)
            )
            weekly_count = Blitz.objects.filter(
                group_id__in=user_group_ids,
                leader=user,
                created_at__gte=week_ago,
            ).count()
            if weekly_count >= limit:
                from rest_framework import status as http_status
                return Response(
                    {
                        'error': 'limit_reached',
                        'feature': 'max_blitz_per_week',
                        'limit': limit,
                        'current': weekly_count,
                    },
                    status=http_status.HTTP_403_FORBIDDEN,
                )

        # Prevent duplicate active blitzes for the same group
        group_url = request.data.get('group', '')
        group_id = None
        if group_url:
            import re
            pk_match = re.search(r'/(\d+)/?$', str(group_url))
            if pk_match:
                group_id = int(pk_match.group(1))

        if group_id:
            with transaction.atomic():
                # Lock the group row to prevent concurrent blitz creation
                try:
                    Group.objects.select_for_update().get(pk=group_id)
                except Group.DoesNotExist:
                    from rest_framework import status as http_status
                    return Response(
                        {'error': 'Grupo no encontrado.'},
                        status=http_status.HTTP_404_NOT_FOUND,
                    )

                # Check for existing active blitz (now protected by lock)
                existing = Blitz.objects.filter(
                    group_id=group_id,
                    status='active',
                    expires_at__gt=timezone.now(),
                ).first()
                if existing:
                    from rest_framework import status as http_status
                    return Response(
                        {'error': 'Este grupo ya tiene un Blitz activo. Termina o espera a que expire.',
                         'existing_blitz_id': existing.id},
                        status=http_status.HTTP_400_BAD_REQUEST,
                    )

                # Safe to create — still within transaction
                try:
                    response = super().create(request, *args, **kwargs)
                    logger.info(f"Blitz created successfully: ID {response.data.get('id')}")
                    return response
                except Exception as e:
                    logger.error(f"Failed to create Blitz: {str(e)}")
                    from rest_framework import status
                    return Response(
                        {'error': str(e)},
                        status=status.HTTP_400_BAD_REQUEST
                    )
        else:
            # No group specified — let normal validation handle it
            try:
                response = super().create(request, *args, **kwargs)
                logger.info(f"Blitz created successfully: ID {response.data.get('id')}")
                return response
            except Exception as e:
                logger.error(f"Failed to create Blitz: {str(e)}")
                from rest_framework import status
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )

    @extend_schema(
        description="Get the user's currently active blitz (if any). Shared across devices and group members.",
        responses={200: BlitzSerializer},
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_active(self, request):
        """
        GET /api/blitzes/my_active/
        Returns the most recent active, non-expired blitz belonging to any
        of the current user's groups. Returns 204 if none found.
        """
        user = request.user
        user_group_ids = list(
            user.groups.filter(is_active=True).values_list('id', flat=True)
        )
        blitz = Blitz.objects.filter(
            group_id__in=user_group_ids,
            status='active',
            expires_at__gt=timezone.now(),
        ).select_related('group', 'leader').order_by('-started_at').first()

        if not blitz:
            return Response(None, status=204)

        serializer = self.get_serializer(blitz)
        return Response(serializer.data)

    @extend_schema(
        description="Get discoverable blitzes with recommendation scoring.",
        responses={200: BlitzSerializer(many=True)},
    )
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def discoverable(self, request):
        """
        RF-013: Recommendation algorithm.
        Returns active blitzes scored by:
        - Common interests (+10 per match)
        - Activity tag match (+15)
        - Distance proximity (+20 if <2km, +10 if <5km)
        - Group size similarity (+5 if within 1 member)
        """
        user = request.user

        # Get user's group IDs to exclude
        user_group_ids = list(
            user.groups.filter(is_active=True).values_list('id', flat=True)
        )

        # Get IDs of blitzes the user already interacted with
        user_blitz_ids = list(
            Blitz.objects.filter(
                group_id__in=user_group_ids,
                status='active'
            ).values_list('id', flat=True)
        )
        interacted_blitz_ids = set(
            BlitzInteraction.objects.filter(
                from_blitz_id__in=user_blitz_ids
            ).values_list('to_blitz_id', flat=True)
        )

        # Fetch active blitzes excluding user's groups and already-interacted
        active_blitzes = Blitz.objects.filter(
            status='active',
            expires_at__gt=timezone.now(),
        ).exclude(
            group_id__in=user_group_ids
        ).select_related('group', 'leader')

        # Get user's interests
        user_interests = set()
        try:
            profile = Profile.objects.get(user=user)
            user_interests = set(
                i.lower() for i in (profile.interests or [])
            )
        except Profile.DoesNotExist:
            pass

        # Get user's active blitz activity type and location
        user_activity = None
        user_location = None
        user_group_size = 0

        for blitz_id in user_blitz_ids:
            try:
                user_blitz = Blitz.objects.select_related('group').get(id=blitz_id)
                user_activity = user_blitz.activity_type
                user_group_size = user_blitz.group.member_count

                loc = user_blitz.location
                if loc and loc.get('lat') and loc.get('lng'):
                    user_location = (float(loc['lat']), float(loc['lng']))
                break
            except Blitz.DoesNotExist:
                pass

        # Get user's blitz opponent size preferences
        user_min_size = None
        user_max_size = None
        for blitz_id in user_blitz_ids:
            try:
                ub = Blitz.objects.get(id=blitz_id)
                user_min_size = ub.min_opponent_size
                user_max_size = ub.max_opponent_size
                break
            except Blitz.DoesNotExist:
                pass

        # If no location from active blitz, try latest LocationLog
        if user_location is None:
            latest_log = LocationLog.objects.filter(
                blitz_id__in=user_blitz_ids
            ).order_by('-created_at').first()
            if latest_log:
                user_location = (float(latest_log.latitude), float(latest_log.longitude))

        # Annotate active blitzes with real member counts
        active_blitzes = active_blitzes.annotate(
            real_member_count=Count('group__groupmembership')
        )

        # Score each blitz
        scored = []
        for blitz in active_blitzes:
            if blitz.id in interacted_blitz_ids:
                continue

            # Filter by opponent group size if preferences set
            member_count = blitz.real_member_count or blitz.group.member_count
            if user_min_size and member_count < user_min_size:
                continue
            if user_max_size and member_count > user_max_size:
                continue

            score = 0

            # Common interests: +10 per match
            group_interests = set(
                i.lower() for i in (blitz.group.combined_interests or [])
            )
            common = user_interests & group_interests
            score += len(common) * 10

            # Activity tag match: +15
            if (user_activity and blitz.activity_type and
                    user_activity.lower() == blitz.activity_type.lower()):
                score += 15

            # Distance proximity
            if user_location:
                blitz_loc = blitz.location
                if blitz_loc and blitz_loc.get('lat') and blitz_loc.get('lng'):
                    dist = _haversine_km(
                        user_location[0], user_location[1],
                        blitz_loc['lat'], blitz_loc['lng']
                    )
                    if dist < 2:
                        score += 20
                    elif dist < 5:
                        score += 10

            # Group size similarity: +5 if within 1 member
            if user_group_size > 0:
                size_diff = abs(blitz.group.member_count - user_group_size)
                if size_diff <= 1:
                    score += 5

            scored.append((blitz, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Serialize
        serializer = self.get_serializer(
            [b for b, _ in scored], many=True
        )

        # Add scores to response
        data = serializer.data
        for i, (_, score) in enumerate(scored):
            if i < len(data):
                data[i]['recommendation_score'] = score

        return Response(data)
