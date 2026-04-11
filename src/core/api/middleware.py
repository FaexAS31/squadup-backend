"""
WebSocket middleware for Firebase authentication.
"""

import logging
from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


class FirebaseWebSocketMiddleware(BaseMiddleware):
    """
    Middleware to authenticate WebSocket connections using Firebase JWT tokens.

    The token should be passed as a query parameter: ws://host/path/?token=<firebase_jwt>
    """

    async def __call__(self, scope, receive, send):
        # Extract token from query string
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        if token:
            user = await self.get_user_from_token(token)
            if user:
                scope['user'] = user
                logger.info(f"WebSocket authenticated for user {user.id} ({user.email})")
            else:
                scope['user'] = AnonymousUser()
                logger.warning("WebSocket authentication failed - invalid token")
        else:
            scope['user'] = AnonymousUser()
            logger.debug("WebSocket connection without token")

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def get_user_from_token(self, token):
        """
        Verify Firebase token and return the corresponding Django user.
        Creates the user if they don't exist (same as HTTP auth).
        """
        try:
            from firebase_admin import auth as firebase_auth
            from api.models import User

            # Verify the Firebase token
            decoded_token = firebase_auth.verify_id_token(token)

            uid = decoded_token.get('uid')
            email = decoded_token.get('email', f'{uid}@firebase.com')
            name = decoded_token.get('name', 'User')

            # Get or create user (same logic as HTTP authentication)
            user, created = User.objects.get_or_create(
                firebase_uid=uid,
                defaults={
                    'email': email,
                    'first_name': name.split()[0] if name and name.strip() else 'User',
                    'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else '',
                    'role': User.Roles.REGULAR,
                    'is_active': True,
                    'is_staff': False,
                    'is_superuser': False,
                }
            )

            if created:
                logger.info(f"New user created via WebSocket: {email} (UID: {uid})")

            return user

        except firebase_auth.ExpiredIdTokenError:
            logger.warning("Expired Firebase token in WebSocket connection")
            return None
        except firebase_auth.RevokedIdTokenError:
            logger.warning("Revoked Firebase token in WebSocket connection")
            return None
        except firebase_auth.InvalidIdTokenError as e:
            logger.warning(f"Invalid Firebase token in WebSocket: {e}")
            return None
        except Exception as e:
            logger.error(f"Error verifying Firebase token for WebSocket: {e}")
            return None
