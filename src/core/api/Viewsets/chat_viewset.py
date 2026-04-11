import logging
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from api.models import Chat, Match, Message
from api.Serializers.chat_serializer import ChatSerializer
from api.Serializers.message_serializer import MessageSerializer
from api.Permissions.permissions import IsChatParticipant

logger = logging.getLogger('api')


@extend_schema(tags=['Chats'])
class ChatViewSet(viewsets.ModelViewSet):
    """
    Gestión de chats.
    
    🔒 SEGURIDAD:
    - Un usuario SOLO ve/participa en chats donde está como participante
    - Aislamiento total de chats de otros usuarios
    """
    
    serializer_class = ChatSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        🔒 AISLAMIENTO CRÍTICO:
        El usuario actual es participante del chat.
        """
        user = self.request.user
        return Chat.objects.filter(
            participants=user
        ).select_related(
            'match',
            'match__blitz_1__group',
            'match__blitz_2__group',
        ).prefetch_related(
            'participants',
        ).distinct()
    
    def get_object(self):
        """
        🔒 Validar que el usuario es participante.
        """
        obj = super().get_object()
        
        if not obj.participants.filter(id=self.request.user.id).exists():
            logger.warning(
                f"Intento de acceso no autorizado: "
                f"Usuario {self.request.user.id} no es participante de chat {obj.id}"
            )
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("No eres participante de este chat")
        
        return obj
    
    def perform_create(self, serializer):
        """
        🔒 El usuario que crea el chat es automáticamente participante.
        Si se proporciona un match URL, enlaza el Chat al Match.
        """
        chat = serializer.save()
        chat.participants.add(self.request.user)

        # Link to Match if match URL was provided
        match_url = self.request.data.get('match')
        if match_url:
            try:
                # Extract match ID from hyperlinked URL
                match_id = match_url.rstrip('/').split('/')[-1]
                match_obj = Match.objects.get(pk=match_id)
                if match_obj.chat is None:
                    match_obj.chat = chat
                    match_obj.save(update_fields=['chat'])
                    # Add all match participants to the chat
                    if match_obj.blitz_1 and match_obj.blitz_1.group:
                        member_ids = match_obj.blitz_1.group.members.values_list('id', flat=True)
                        chat.participants.add(*member_ids)
                    if match_obj.blitz_2 and match_obj.blitz_2.group:
                        member_ids = match_obj.blitz_2.group.members.values_list('id', flat=True)
                        chat.participants.add(*member_ids)
                    logger.info(f"Chat {chat.id} linked to Match {match_id}")
            except (Match.DoesNotExist, ValueError):
                logger.warning(f"Could not link chat {chat.id} to match URL: {match_url}")

        logger.info(f"Chat creado: {chat.id} por usuario {self.request.user.id}")

    @action(detail=True, methods=['post'], url_path='mark_read')
    def mark_read(self, request, pk=None):
        """
        Mark all unread messages in this chat as read for the current user.
        Only marks messages NOT sent by the current user.
        """
        chat = self.get_object()
        now = timezone.now()
        updated = chat.messages.filter(
            is_read=False
        ).exclude(
            sender=request.user
        ).update(is_read=True, read_at=now)

        logger.debug(
            f"Marked {updated} messages as read in chat {chat.id} "
            f"for user {request.user.id}"
        )
        return Response({'status': 'ok', 'marked_count': updated})

    @action(detail=True, methods=['get'], url_path='online-count')
    def online_count(self, request, pk=None):
        """
        Returns the count and list of online users for this chat.
        Uses PresenceConsumer's class-level online_users set.
        """
        chat = self.get_object()
        participant_ids = set(
            str(uid) for uid in chat.participants.values_list('id', flat=True)
        )

        # Get online users from PresenceConsumer
        try:
            from api.consumers import PresenceConsumer
            all_online = PresenceConsumer.online_users
        except (ImportError, AttributeError):
            all_online = set()

        online_in_chat = participant_ids & all_online
        total_participants = chat.participants.count()

        return Response({
            'online_count': len(online_in_chat),
            'total_participants': total_participants,
            'online_users': list(online_in_chat),
        })