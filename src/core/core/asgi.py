"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# Initialize Django ASGI application early to ensure the app registry is ready
django_asgi_app = get_asgi_application()

# Import websocket_urlpatterns and middleware after Django app is loaded
from api.routing import websocket_urlpatterns  # noqa: E402
from api.middleware import FirebaseWebSocketMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    # HTTP requests
    'http': django_asgi_app,

    # WebSocket connections with Firebase authentication
    'websocket': AllowedHostsOriginValidator(
        FirebaseWebSocketMiddleware(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
