import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from api.models import Friendship, User
from api.Serializers.friendship_serializer import FriendshipSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')


@extend_schema(tags=['Friendships'])
class FriendshipViewSet(viewsets.ModelViewSet):
    """
    ViewSet para Friendships con aislamiento de datos.
    🔒 SEGURIDAD:
    - Un usuario SOLO ve/modifica sus propias friendships
    - No puede ver solicitudes entre otros usuarios
    """
    serializer_class = FriendshipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        🔒 AISLAMIENTO CRÍTICO:
        - user_from: El usuario actual (solicitudes que inició)
        - user_to: El usuario actual (solicitudes que recibió)

        Un usuario NO puede ver solicitudes entre otros usuarios.
        """
        user = self.request.user

        return Friendship.objects.filter(
            Q(user_from=user) | Q(user_to=user)
        ).distinct()

    def perform_create(self, serializer):
        """
        🔒 Inyectar user_from desde el backend.

        No permitir que el cliente establezca user_from.
        """
        serializer.save(user_from=self.request.user)

    @action(detail=False, methods=['post'], url_path='solo_like', permission_classes=[IsAuthenticated])
    def solo_like(self, request):
        """
        POST /api/friendships/solo_like/ — Solo Mode like action.

        Creates a pending friendship or detects mutual match.
        Body: {"user_to_id": 123}
        Returns: {"is_match": bool, "friendship_id": int}
        """
        user = request.user
        target_id = request.data.get('user_to_id')

        if not target_id:
            return Response(
                {'error': 'user_to_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            target = User.objects.get(id=target_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        if target.id == user.id:
            return Response(
                {'error': 'Cannot like yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for blocked relationship
        is_blocked = Friendship.objects.filter(
            Q(user_from=user, user_to=target, status='blocked') |
            Q(user_from=target, user_to=user, status='blocked')
        ).exists()
        if is_blocked:
            return Response(
                {'error': 'Cannot interact with this user'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get or create the forward friendship
        friendship, created = Friendship.objects.get_or_create(
            user_from=user,
            user_to=target,
            defaults={'status': 'pending', 'source': 'solo'}
        )

        # Check for mutual like (reverse direction)
        reverse = Friendship.objects.filter(
            user_from=target,
            user_to=user,
            status='pending'
        ).first()

        if reverse:
            # Mutual match! Accept both directions
            friendship.status = 'accepted'
            friendship.save()
            reverse.status = 'accepted'
            reverse.save()

            logger.info(f"Solo Mode mutual match: {user.id} <-> {target.id}")

            return Response({
                'is_match': True,
                'friendship_id': friendship.id,
                'matched_user': {
                    'id': target.id,
                    'first_name': target.first_name,
                    'profile_photo': target.profile_photo or None,
                },
            })

        logger.info(f"Solo Mode like: {user.id} -> {target.id}")
        return Response({
            'is_match': False,
            'friendship_id': friendship.id,
        })
