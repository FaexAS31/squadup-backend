"""
WebSocket URL routing for Django Channels.
"""

from django.urls import path

from . import consumers

websocket_urlpatterns = [
    # Chat WebSocket - para mensajes en tiempo real
    path('ws/chat/<int:chat_id>/', consumers.ChatConsumer.as_asgi()),

    # Presence WebSocket - para estado online/offline
    path('ws/presence/', consumers.PresenceConsumer.as_asgi()),

    # Coordination WebSocket - para coordinación Solo Mode en tiempo real
    path('ws/coordination/<int:match_id>/', consumers.CoordinationConsumer.as_asgi()),

    # Blitz Voting WebSocket - para votación democrática en tiempo real
    path('ws/blitz-voting/<int:blitz_id>/', consumers.BlitzVotingConsumer.as_asgi()),
]
