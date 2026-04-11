import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q, Prefetch, Count, Exists, OuterRef
from drf_spectacular.utils import extend_schema

from django_filters.rest_framework import DjangoFilterBackend

from api.models import Match, MatchMute
from api.Serializers.match_serializer import MatchSerializer
from api.Permissions.permissions import IsMatchParticipant

logger = logging.getLogger('api')


@extend_schema(tags=['Matches'])
class MatchViewSet(viewsets.ModelViewSet):
    """
    Matches entre grupos.
    
    🔒 SEGURIDAD:
    - Un usuario SOLO ve matches donde está en uno de los dos grupos
    - Aislamiento estricto de datos
    
    ⚡ PERFORMANCE:
    - select_related + prefetch_related para evitar N+1 queries
    - Índices en BD para búsquedas frecuentes
    """
    
    serializer_class = MatchSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    def get_queryset(self):
        """
        🔒 AISLAMIENTO CRÍTICO:
        Filtrar por: El usuario pertenece a blitz_1.group O blitz_2.group
        
        ⚡ OPTIMIZACIÓN:
        - select_related: Evitar N+1 en ForeignKeys
        - prefetch_related: Evitar N+1 en ManyToMany y relaciones inversas
        """
        user = self.request.user
        
        queryset = Match.objects.filter(
            Q(blitz_1__group__members=user) | 
            Q(blitz_2__group__members=user)
        ).distinct()
        
        # ⚡ Optimizar queries
        queryset = queryset.select_related(
            'blitz_1',
            'blitz_1__group',
            'blitz_1__leader',
            'blitz_2',
            'blitz_2__group',
            'blitz_2__leader',
            'chat'
        ).prefetch_related(
            'blitz_1__group__members',
            'blitz_2__group__members',
            'chat__participants' if hasattr(Match, 'chat') else None,
            'activities',
            'memories'
        ).annotate(
            message_count=Count('chat__messages'),
            activity_count=Count('activities')
        )
        
        # Limpiar None de prefetch_related
        return queryset.filter(
            Q(blitz_1__group__members=user) | 
            Q(blitz_2__group__members=user)
        ).distinct()
    
    def get_object(self):
        """
        🔒 Validar que el usuario es participante del match.
        """
        obj = super().get_object()
        
        # Verificar participación
        is_participant = (
            obj.blitz_1.group.members.filter(id=self.request.user.id).exists() or
            obj.blitz_2.group.members.filter(id=self.request.user.id).exists()
        )
        
        if not is_participant:
            logger.warning(
                f"Intento de acceso no autorizado a match: "
                f"Usuario {self.request.user.id} no es participante de match {obj.id}"
            )
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("No eres participante de este match")
        
        return obj
    
    def perform_create(self, serializer):
        """
        Registrar creación de match con logging.
        """
        match = serializer.save()
        logger.info(
            f"Nuevo match creado: {match.id} | "
            f"Grupo 1: {match.blitz_1.group.id} vs Grupo 2: {match.blitz_2.group.id}"
        )
    
    def perform_update(self, serializer):
        """
        Registrar actualización de match.
        """
        match = serializer.save()
        logger.info(
            f"Match {match.id} actualizado por usuario {self.request.user.id} | "
            f"Nuevo estado: {match.status}"
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mute(self, request, pk=None):
        """Mute notifications for this match."""
        match = self.get_object()
        _, created = MatchMute.objects.get_or_create(
            user=request.user, match=match
        )
        if created:
            logger.info(f"User {request.user.id} muted match {match.id}")
        return Response({'status': 'muted'})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unmute(self, request, pk=None):
        """Unmute notifications for this match."""
        match = self.get_object()
        deleted, _ = MatchMute.objects.filter(
            user=request.user, match=match
        ).delete()
        if deleted:
            logger.info(f"User {request.user.id} unmuted match {match.id}")
        return Response({'status': 'unmuted'})