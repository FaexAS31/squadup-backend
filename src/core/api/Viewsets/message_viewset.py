import logging
from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from api.models import Chat, Message
from api.Serializers.message_serializer import MessageSerializer
from api.Permissions.permissions import IsChatParticipant

logger = logging.getLogger('api')


@extend_schema(tags=['Messages'])
class MessageViewSet(viewsets.ModelViewSet):
    """
    Mensajes en chats.
    
    🔒 SEGURIDAD:
    - Un usuario SOLO ve mensajes de chats donde es participante
    - El remitente es siempre inyectado desde el backend
    """
    
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsChatParticipant]
    filterset_fields = ['chat', 'message_type']

    def get_queryset(self):
        """
        🔒 AISLAMIENTO CRÍTICO:
        Solo mensajes de chats donde el usuario es participante.
        
        ⚡ Optimizar con select_related para evitar N+1.
        """
        user = self.request.user
        return Message.objects.filter(
            chat__participants=user
        ).select_related(
            'sender',
            'chat'
        ).order_by('created_at')
    
    def perform_create(self, serializer):
        """
        🔒 El remitente es siempre el usuario actual.

        No permitir que el cliente especifique 'sender'.
        """
        # Validar que el usuario es participante del chat
        chat = serializer.validated_data.get('chat')
        if not chat.participants.filter(id=self.request.user.id).exists():
            logger.warning(
                f"Intento de mensaje en chat no autorizado: "
                f"Usuario {self.request.user.id} no es participante de chat {chat.id}"
            )
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("No eres participante de este chat")

        with transaction.atomic():
            message = serializer.save(sender=self.request.user)

            # Lock the chat before updating last_message fields
            chat = Chat.objects.select_for_update().get(pk=message.chat_id)

            # Only update if this message is actually newer
            if chat.last_message_at is None or message.created_at >= chat.last_message_at:
                preview = (message.text or '')[:100]
                if not preview:
                    if message.message_type == 'image':
                        preview = '📷 Imagen'
                    elif message.message_type in ('audio', 'voice'):
                        preview = '🎤 Audio'
                chat.last_message_preview = preview
                chat.last_message_at = message.created_at
                chat.save(update_fields=['last_message_preview', 'last_message_at'])

        logger.debug(
            f"Mensaje creado por usuario {self.request.user.id} "
            f"en chat {chat.id} | Tipo: {message.message_type}"
        )