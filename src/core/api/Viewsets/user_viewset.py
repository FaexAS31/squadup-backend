import logging
import math
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError

from api.models import User, Profile, ProfilePhoto, Friendship, SoloMatch, Blitz, BlitzInteraction, Match, MeetupPlan
from api.Serializers.user_serializer import UserSerializer
from api.Authentication.authentication import FirebaseAuthentication

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


@extend_schema(tags=['Users'])
class UserViewSet(viewsets.ModelViewSet):
    """
    Gestión de usuarios.
    
    🔒 SEGURIDAD ESTRICTA:
    - Un usuario SOLO ve/modifica su propio perfil
    - Solo ADMIN ve/modifica otros usuarios
    - No permitir crear/eliminar usuarios vía API (solo Firebase → sync)
    - El rol por defecto es REGULAR
    """
    
    serializer_class = UserSerializer
    authentication_classes = [FirebaseAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        🔒 AISLAMIENTO CRÍTICO:
        - Usuario REGULAR: Solo su propio perfil
        - Usuario ADMIN: Todos los usuarios
        """
        user = self.request.user
        
        if user.role == User.Roles.ADMIN:
            # ADMIN ve todos los usuarios
            return User.objects.all()
        else:
            # Usuario regular SOLO ve a sí mismo
            return User.objects.filter(id=user.id)
    
    def get_object(self):
        """
        🔒 Protección adicional: Un usuario NO puede acceder a otros.
        """
        obj = super().get_object()
        
        # Un usuario regular SOLO puede acceder a su propio perfil
        if self.request.user.role != User.Roles.ADMIN:
            if obj.id != self.request.user.id:
                logger.warning(
                    f"Intento de acceso no autorizado: "
                    f"Usuario {self.request.user.id} intentó acceder a {obj.id}"
                )
                raise PermissionDenied(
                    "No tienes acceso a este usuario"
                )
        
        return obj
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """
        GET /api/users/me/ → Obtener perfil del usuario actual.

        Útil para obtener datos sin conocer el ID.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        """
        🔒 BLOQUEADO: No permitir creación de usuarios vía API.
        
        Los usuarios se crean automáticamente vía Firebase Authentication
        cuando se autentican por primera vez.
        """
        logger.warning(
            f"Intento de crear usuario vía API desde usuario {request.user.id}"
        )
        return Response(
            {"detail": "Los usuarios se crean automáticamente vía Firebase Authentication"},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def perform_update(self, serializer):
        """
        🔒 Validaciones de seguridad antes de actualizar.
        """
        user = self.request.user
        instance = self.get_object()
        
        # Bloquear cambios peligrosos
        if 'is_staff' in serializer.validated_data:
            logger.warning(
                f"Intento de cambiar is_staff para usuario {instance.id}"
            )
            raise PermissionDenied("No puedes cambiar is_staff")
        
        if 'is_superuser' in serializer.validated_data:
            logger.warning(
                f"Intento de cambiar is_superuser para usuario {instance.id}"
            )
            raise PermissionDenied("No puedes cambiar is_superuser")
        
        serializer.save()
        logger.info(
            f"Usuario {instance.id} actualizado por {user.id}"
        )
    
    def destroy(self, request, *args, **kwargs):
        """
        🔒 BLOQUEADO: No permitir eliminar usuarios vía API.
        
        Usar la acción 'deactivate' para desactivar usuarios (soft delete).
        """
        logger.warning(
            f"Intento de eliminar usuario vía API desde {request.user.id}"
        )
        return Response(
            {"detail": "No se pueden eliminar usuarios. Usa /deactivate para desactivar."},
            status=status.HTTP_403_FORBIDDEN
        )
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def search(self, request):
        """
        GET /api/users/search/?q=<query> → Search users by email, phone, or name.

        Used for adding friends. Returns limited public info only.
        Excludes the current user from results.

        Query can be:
        - Email address (exact match)
        - Phone number (exact match, with or without country code)
        - Name (partial match on first_name or last_name)
        """
        query = request.query_params.get('q', '').strip()
        if not query or len(query) < 2:
            return Response({
                "results": [],
                "message": "Query must be at least 2 characters"
            })

        from django.db.models import Q

        # Build search query
        # Exact match for email and phone, partial match for names
        search_filter = (
            Q(email__iexact=query) |
            Q(phone__iexact=query) |
            Q(phone__iexact=query.lstrip('+')) |  # Strip + for phone matching
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

        # Gather blocked user IDs (both directions)
        blocked_ids = set()
        for f in Friendship.objects.filter(
            Q(user_from=request.user, status='blocked') |
            Q(user_to=request.user, status='blocked')
        ).values_list('user_from_id', 'user_to_id'):
            blocked_ids.update(f)
        blocked_ids.discard(request.user.id)

        # Find matching users, excluding self, inactive, and blocked
        users = User.objects.filter(
            search_filter,
            is_active=True
        ).exclude(
            id=request.user.id
        ).exclude(
            id__in=blocked_ids
        ).only(
            'id', 'first_name', 'last_name', 'profile_photo'
        )[:20]  # Limit results

        # Build friendship status lookup for current user
        user_ids = [u.id for u in users]
        friendship_map = {}
        if user_ids:
            for f in Friendship.objects.filter(
                Q(user_from=request.user, user_to_id__in=user_ids) |
                Q(user_to=request.user, user_from_id__in=user_ids)
            ).values('user_from_id', 'user_to_id', 'status'):
                other_id = f['user_to_id'] if f['user_from_id'] == request.user.id else f['user_from_id']
                friendship_map[other_id] = f['status']

        # Return limited public info with friendship status
        results = []
        for u in users:
            results.append({
                "id": u.id,
                "url": request.build_absolute_uri(f"/api/users/{u.id}/"),
                "first_name": u.first_name,
                "last_name": u.last_name,
                "profile_photo": u.profile_photo if u.profile_photo else None,
                "friendship_status": friendship_map.get(u.id),
            })

        return Response({"results": results})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def discoverable(self, request):
        """
        GET /api/users/discoverable/ — Solo Mode user discovery.

        Returns scored user recommendations for 1-on-1 matching.
        Excludes: self, existing friends, blocked users, pending requests.
        Scores by: interest overlap, profile completeness, location proximity, activity recency.
        """
        user = request.user

        # Gather friendship IDs to exclude (accepted, blocked, pending — both directions)
        exclude_ids = set()
        exclude_ids.add(user.id)
        for f in Friendship.objects.filter(user_from=user):
            exclude_ids.add(f.user_to_id)
        for f in Friendship.objects.filter(user_to=user):
            exclude_ids.add(f.user_from_id)

        # Exclude users I already swiped on (any active status)
        active_solo_statuses = ['pending', 'matched', 'coordinating', 'ready', 'started']
        for sm in SoloMatch.objects.filter(
            user_a=user, status__in=active_solo_statuses
        ).values_list('user_b_id', flat=True):
            exclude_ids.add(sm)
        # Exclude users already in coordination/blitz with me (but NOT pending —
        # pending means they liked me first, so I should still see them to swipe back)
        in_progress_statuses = ['matched', 'coordinating', 'ready', 'started']
        for sm in SoloMatch.objects.filter(
            user_b=user, status__in=in_progress_statuses
        ).values_list('user_a_id', flat=True):
            exclude_ids.add(sm)

        # Fetch candidate users
        candidates = User.objects.filter(
            is_active=True
        ).exclude(
            id__in=exclude_ids
        ).select_related('profile')[:200]

        # Get current user's profile
        user_interests = set()
        user_location = None
        try:
            user_profile = Profile.objects.get(user=user)
            user_interests = set(i.lower() for i in (user_profile.interests or []))
            loc = user_profile.default_location
            if loc and loc.get('lat') and loc.get('lng'):
                user_location = (float(loc['lat']), float(loc['lng']))
        except Profile.DoesNotExist:
            pass

        # Score each candidate
        scored = []
        seven_days_ago = timezone.now() - timezone.timedelta(days=7)
        for candidate in candidates:
            score = 0
            candidate_interests = set()
            common = set()
            profile_data = {}

            try:
                cp = candidate.profile
                candidate_interests = set(i.lower() for i in (cp.interests or []))
                common = user_interests & candidate_interests

                # Interest overlap: +10 per common interest
                score += len(common) * 10

                # Profile completeness: +5 each
                if cp.bio:
                    score += 5
                if cp.age:
                    score += 5
                if candidate.profile_photo:
                    score += 5

                # Location proximity
                if user_location:
                    loc = cp.default_location
                    if loc and loc.get('lat') and loc.get('lng'):
                        dist = _haversine_km(
                            user_location[0], user_location[1],
                            float(loc['lat']), float(loc['lng'])
                        )
                        if dist < 5:
                            score += 20
                        elif dist < 10:
                            score += 10

                profile_data = {
                    'bio': cp.bio or '',
                    'interests': cp.interests or [],
                    'age': cp.age,
                    'gender': cp.gender or '',
                    'default_location': cp.default_location or {},
                }
            except Profile.DoesNotExist:
                pass

            # Activity recency: +10 if updated within 7 days
            if candidate.updated_at and candidate.updated_at >= seven_days_ago:
                score += 10

            # Gallery photos (up to 6)
            gallery = ProfilePhoto.objects.filter(
                user=candidate
            ).order_by('order')[:6]
            gallery_photos = [
                {'url': p.image_url, 'thumbnail': p.thumbnail_url}
                for p in gallery
            ]

            # Location city
            location_city = ''
            default_loc = profile_data.get('default_location') or {}
            if default_loc:
                location_city = default_loc.get('city', '') or ''

            scored.append({
                'id': candidate.id,
                'url': request.build_absolute_uri(f'/api/users/{candidate.id}/'),
                'first_name': candidate.first_name,
                'last_name': candidate.last_name[:1] + '.' if candidate.last_name else '',
                'profile_photo': candidate.profile_photo or None,
                'gallery_photos': gallery_photos,
                # Flattened profile fields for frontend convenience
                'bio': profile_data.get('bio', ''),
                'age': profile_data.get('age'),
                'gender': profile_data.get('gender', ''),
                'interests': profile_data.get('interests', []),
                'location_city': location_city,
                'recommendation_score': score,
                'common_interests': sorted(common),
                'common_interests_count': len(common),
                'recently_active': candidate.updated_at and candidate.updated_at >= seven_days_ago,
            })

        # Sort by score descending, limit 50
        scored.sort(key=lambda x: x['recommendation_score'], reverse=True)
        return Response({'results': scored[:50]})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def detailed_stats(self, request):
        """
        GET /api/users/detailed_stats/ → Detailed statistics for premium users.

        Returns computed stats: total blitzes, swipes, matches, match rate, meetups, solo connections.
        """
        from django.db.models import Q

        user = request.user
        user_groups = user.groups.filter(is_active=True)
        user_blitzes = Blitz.objects.filter(group__in=user_groups)

        # Total blitz sessions participated in
        total_blitzes = user_blitzes.exclude(status='cancelled').distinct().count()

        # Swipe stats
        total_likes = BlitzInteraction.objects.filter(
            from_blitz__in=user_blitzes, interaction_type='like'
        ).count()
        total_skips = BlitzInteraction.objects.filter(
            from_blitz__in=user_blitzes, interaction_type='skip'
        ).count()

        # Matches (group blitz matches)
        total_matches = Match.objects.filter(
            Q(blitz_1__group__in=user_groups) | Q(blitz_2__group__in=user_groups)
        ).distinct().count()

        # Match rate
        match_rate = round((total_matches / total_blitzes * 100) if total_blitzes > 0 else 0)

        # Meetups planned
        total_meetups = MeetupPlan.objects.filter(
            Q(match__blitz_1__group__in=user_groups) | Q(match__blitz_2__group__in=user_groups)
        ).distinct().count()

        # Solo connections
        solo_connections = SoloMatch.objects.filter(
            Q(user_a=user) | Q(user_b=user),
            status__in=['matched', 'coordinating', 'ready', 'started']
        ).count()

        return Response({
            'total_blitzes': total_blitzes,
            'total_likes': total_likes,
            'total_skips': total_skips,
            'total_swipes': total_likes + total_skips,
            'total_matches': total_matches,
            'match_rate': match_rate,
            'total_meetups': total_meetups,
            'solo_connections': solo_connections,
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def deactivate(self, request, pk=None):
        """
        POST /api/users/{id}/deactivate/ → Desactivar usuario (soft delete).

        Solo ADMIN o el usuario mismo puede desactivarse.
        """
        user = request.user
        target = self.get_object()

        # Solo ADMIN o el usuario mismo puede desactivarse
        if user.role != User.Roles.ADMIN and user.id != target.id:
            logger.warning(
                f"Intento no autorizado de desactivar usuario {target.id} "
                f"por usuario {user.id}"
            )
            raise PermissionDenied(
                "No puedes desactivar este usuario"
            )

        target.is_active = False
        target.save()

        logger.info(f"Usuario {target.id} desactivado por {user.id}")

        return Response({
            "status": "Usuario desactivado",
            "user_id": target.id
        })