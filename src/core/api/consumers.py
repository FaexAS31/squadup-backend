"""
WebSocket consumers for real-time chat functionality.
"""

import json
import logging
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time chat messaging.

    Handles:
    - Connection to a specific chat room
    - Sending/receiving messages in real-time with persistence
    - Typing indicators
    - Read receipts
    - Image messages
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        self.room_group_name = f'chat_{self.chat_id}'
        self.user = self.scope.get('user')

        # Verify user is authenticated
        if not self.user or not self.user.is_authenticated:
            logger.warning(f"Unauthenticated WebSocket connection attempt to chat {self.chat_id}")
            await self.close()
            return

        # Verify user is participant in this chat
        is_participant = await self.check_chat_participant()
        if not is_participant:
            logger.warning(f"User {self.user.id} tried to access chat {self.chat_id} without being a participant")
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        logger.info(f"User {self.user.id} connected to chat {self.chat_id}")

        # Notify others that user joined
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_joined',
                'user_id': self.user.id,
                'user_name': f"{self.user.first_name} {self.user.last_name}".strip() or self.user.email,
            }
        )

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        # Notify others that user left
        if self.user and self.user.is_authenticated:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_left',
                    'user_id': self.user.id,
                }
            )

        logger.info(f"User disconnected from chat {self.chat_id}")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'chat_message':
                await self.handle_chat_message(data)

            elif message_type == 'typing':
                await self.handle_typing(data)

            elif message_type == 'message_read':
                await self.handle_message_read(data)

        except json.JSONDecodeError:
            logger.error("Invalid JSON received in WebSocket")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format',
            }))
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Server error processing message',
            }))

    async def handle_chat_message(self, data):
        """Handle incoming chat message - persist and broadcast."""
        content = data.get('content', '').strip()
        msg_type = data.get('message_type', 'text')
        metadata = data.get('metadata', {})

        if not content and msg_type == 'text':
            return  # Don't process empty text messages

        # Persist message to database
        message = await self.save_message(content, msg_type, metadata)

        if message:
            # Get sender's profile photo URL if available
            sender_avatar = await self.get_sender_avatar()

            # Broadcast message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message_id': message['id'],
                    'content': message['text'],
                    'message_type': message['message_type'],
                    'metadata': message['metadata'],
                    'sender_id': self.user.id,
                    'sender_name': f"{self.user.first_name} {self.user.last_name}".strip() or self.user.email,
                    'sender_avatar': sender_avatar,
                    'created_at': message['created_at'],
                }
            )

    async def handle_typing(self, data):
        """Handle typing indicator."""
        is_typing = data.get('is_typing', False)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'user_id': self.user.id,
                'user_name': self.user.first_name or self.user.email.split('@')[0],
                'is_typing': is_typing,
            }
        )

    async def handle_message_read(self, data):
        """Handle read receipt - mark messages as read."""
        message_ids = data.get('message_ids', [])

        if not message_ids:
            return

        # Mark messages as read in database
        read_count = await self.mark_messages_read(message_ids)

        if read_count > 0:
            # Broadcast read receipt to room
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_receipt',
                    'user_id': self.user.id,
                    'message_ids': message_ids,
                    'read_at': timezone.now().isoformat(),
                }
            )

    # Channel layer event handlers

    async def chat_message(self, event):
        """Handle chat_message event from channel layer."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message_id': event['message_id'],
            'content': event['content'],
            'message_type': event['message_type'],
            'metadata': event.get('metadata', {}),
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'sender_avatar': event.get('sender_avatar'),
            'created_at': event['created_at'],
        }))

    async def typing_indicator(self, event):
        """Handle typing_indicator event from channel layer."""
        # Don't send typing indicator to the sender
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'user_name': event['user_name'],
                'is_typing': event['is_typing'],
            }))

    async def read_receipt(self, event):
        """Handle read_receipt event from channel layer."""
        # Send to all users so they can update UI
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'user_id': event['user_id'],
            'message_ids': event['message_ids'],
            'read_at': event['read_at'],
        }))

    async def user_joined(self, event):
        """Handle user_joined event from channel layer."""
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'user_joined',
                'user_id': event['user_id'],
                'user_name': event['user_name'],
            }))

    async def user_left(self, event):
        """Handle user_left event from channel layer."""
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'user_left',
                'user_id': event['user_id'],
            }))

    # Database operations

    @database_sync_to_async
    def check_chat_participant(self):
        """Check if user is a participant in the chat."""
        from .models import Chat

        try:
            chat = Chat.objects.get(pk=self.chat_id)
            return chat.participants.filter(pk=self.user.pk).exists()
        except Chat.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, content, message_type, metadata):
        """Save message to database and return message data."""
        from .models import Chat, Message

        try:
            chat = Chat.objects.get(pk=self.chat_id)

            message = Message.objects.create(
                chat=chat,
                sender=self.user,
                text=content,
                message_type=message_type,
                metadata=metadata,
            )

            # Update chat's last activity
            chat.updated_at = timezone.now()
            chat.save(update_fields=['updated_at'])

            return {
                'id': message.id,
                'text': message.text,
                'message_type': message.message_type,
                'metadata': message.metadata,
                'created_at': message.created_at.isoformat(),
            }
        except Chat.DoesNotExist:
            logger.error(f"Chat {self.chat_id} not found when saving message")
            return None
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return None

    @database_sync_to_async
    def mark_messages_read(self, message_ids):
        """Mark messages as read by the current user."""
        from .models import Message

        try:
            # Only mark messages not sent by the current user
            updated = Message.objects.filter(
                id__in=message_ids,
                chat_id=self.chat_id,
                is_read=False
            ).exclude(
                sender=self.user
            ).update(
                is_read=True,
                read_at=timezone.now()
            )
            return updated
        except Exception as e:
            logger.error(f"Error marking messages as read: {e}")
            return 0

    @database_sync_to_async
    def get_sender_avatar(self):
        """Get the sender's profile photo URL."""
        try:
            from .models import Profile
            profile = Profile.objects.filter(user=self.user).first()
            if profile and profile.photo_url:
                return profile.photo_url
            return None
        except Exception:
            return None


class PresenceConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for user presence (online/offline status).

    Broadcasts online user list to all connected clients.
    """

    # Class-level storage for online users
    _online_users = set()

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope.get('user')
        self.room_group_name = 'presence'

        # Verify user is authenticated
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Join presence group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Add user to online set
        PresenceConsumer._online_users.add(str(self.user.id))

        await self.accept()

        # Broadcast updated online users list
        await self.broadcast_online_users()

        logger.info(f"User {self.user.id} is now online")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # Remove user from online set
        if self.user and self.user.is_authenticated:
            PresenceConsumer._online_users.discard(str(self.user.id))

        # Leave presence group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        # Broadcast updated online users list
        await self.broadcast_online_users()

        logger.info(f"User {getattr(self.user, 'id', 'unknown')} is now offline")

    async def receive(self, text_data):
        """Handle incoming messages (heartbeat, etc.)."""
        try:
            data = json.loads(text_data)
            if data.get('type') == 'heartbeat':
                # Client is still alive, update last seen if needed
                pass
        except json.JSONDecodeError:
            pass

    async def broadcast_online_users(self):
        """Broadcast the list of online users to all connected clients."""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'online_users',
                'users': list(PresenceConsumer._online_users),
            }
        )

    async def online_users(self, event):
        """Handle online_users event from channel layer."""
        await self.send(text_data=json.dumps({
            'type': 'online_users',
            'users': event['users'],
        }))


class CoordinationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for Solo Mode coordination rooms.

    Endpoint: /ws/coordination/{solo_match_id}/
    Broadcasts preference updates, ready state, and blitz start events
    to both participants in a solo match.
    """

    async def connect(self):
        self.match_id = self.scope['url_route']['kwargs']['match_id']
        self.room_group_name = f'coordination_{self.match_id}'

        # Verify user is part of this SoloMatch
        user = self.scope.get('user')
        if not user or not await self._is_participant(user.id):
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()
        logger.info(
            f"CoordinationConsumer: user {user.id} connected to room {self.match_id}"
        )

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def coordination_update(self, event):
        """Broadcast coordination state changes to both users."""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def _is_participant(self, user_id):
        from api.models import SoloMatch
        from django.db.models import Q
        return SoloMatch.objects.filter(
            Q(user_a_id=user_id) | Q(user_b_id=user_id),
            pk=self.match_id,
        ).exists()


class BlitzVotingConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for Blitz democratic voting.

    Endpoint: /ws/blitz-voting/{blitz_id}/
    Server-push only: broadcasts vote updates to group members.
    Votes are cast via REST (BlitzVoteViewSet.cast_vote).
    """

    async def connect(self):
        self.blitz_id = self.scope['url_route']['kwargs']['blitz_id']
        self.room_group_name = f'blitz_voting_{self.blitz_id}'
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        if not await self._is_blitz_group_member():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()
        logger.info(
            f"BlitzVotingConsumer: user {self.user.id} connected to blitz {self.blitz_id}"
        )

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    async def vote_update(self, event):
        """Forward vote update events to connected clients."""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def _is_blitz_group_member(self):
        from api.models import Blitz, GroupMembership
        try:
            blitz = Blitz.objects.select_related('group').get(pk=self.blitz_id)
            return GroupMembership.objects.filter(
                group=blitz.group,
                user=self.user,
            ).exists()
        except Blitz.DoesNotExist:
            return False
