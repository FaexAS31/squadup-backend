from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from django.utils import timezone

from ..models import DeviceToken
from ..Serializers.device_token_serializer import (
    DeviceTokenSerializer,
    DeviceTokenCreateSerializer,
)


class DeviceTokenViewSet(ModelViewSet):
    """
    ViewSet for managing FCM device tokens.

    Users can only see and manage their own device tokens.

    Endpoints:
    - GET /devicetokens/ - List user's tokens
    - POST /devicetokens/ - Register new token
    - DELETE /devicetokens/{id}/ - Remove token
    - POST /devicetokens/register/ - Register/update token (upsert)
    """
    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter to only show current user's tokens."""
        return DeviceToken.objects.filter(user=self.request.user, is_active=True)

    def get_serializer_class(self):
        if self.action == 'create' or self.action == 'register':
            return DeviceTokenCreateSerializer
        return DeviceTokenSerializer

    def perform_create(self, serializer):
        """Associate token with current user."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['post'], url_path='register')
    def register(self, request):
        """
        Register or update a device token (upsert operation).

        If the token already exists:
        - If it belongs to another user, transfer it to current user
        - If it belongs to current user, update last_used_at

        Request body:
        {
            "token": "fcm_token_string",
            "platform": "ios" | "android" | "web",
            "device_id": "optional_device_identifier"
        }
        """
        serializer = DeviceTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data['token']
        platform = serializer.validated_data.get('platform', 'ios')
        device_id = serializer.validated_data.get('device_id', '')

        # Try to find existing token
        existing = DeviceToken.objects.filter(token=token).first()

        if existing:
            # Token exists - update it
            if existing.user != request.user:
                # Transfer token to current user (device changed hands)
                existing.user = request.user
            existing.platform = platform
            existing.device_id = device_id
            existing.is_active = True
            existing.last_used_at = timezone.now()
            existing.save()

            response_serializer = DeviceTokenSerializer(
                existing,
                context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        else:
            # Create new token
            device_token = DeviceToken.objects.create(
                user=request.user,
                token=token,
                platform=platform,
                device_id=device_id,
                last_used_at=timezone.now(),
            )
            response_serializer = DeviceTokenSerializer(
                device_token,
                context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['delete'], url_path='unregister')
    def unregister(self, request):
        """
        Unregister a device token (logout/disable notifications).

        Request body:
        {
            "token": "fcm_token_string"
        }
        """
        token = request.data.get('token')
        if not token:
            return Response(
                {'error': 'Token is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Deactivate the token instead of deleting (for audit trail)
        updated = DeviceToken.objects.filter(
            token=token,
            user=request.user
        ).update(is_active=False)

        if updated:
            return Response({'status': 'Token unregistered'}, status=status.HTTP_200_OK)
        else:
            return Response(
                {'error': 'Token not found'},
                status=status.HTTP_404_NOT_FOUND
            )
