import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter

from api.models import Notification
from api.Serializers.notification_serializer import NotificationSerializer

logger = logging.getLogger('api')


@extend_schema(tags=['Notifications'])
class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user notifications.

    Users can only see their own notifications.

    Endpoints:
    - GET /notifications/ - List user's notifications
    - GET /notifications/{id}/ - Get notification detail
    - DELETE /notifications/{id}/ - Delete notification
    - POST /notifications/{id}/mark-read/ - Mark as read
    - POST /notifications/mark-all-read/ - Mark all as read
    - GET /notifications/unread-count/ - Get unread count
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter to only show current user's notifications."""
        user = self.request.user
        queryset = Notification.objects.filter(user=user)

        # Optional filters
        is_read = self.request.query_params.get('is_read')
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')

        notification_type = self.request.query_params.get('type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type.upper())

        return queryset.order_by('-created_at')

    @extend_schema(
        description="Mark a notification as read",
        responses={200: NotificationSerializer}
    )
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """Mark a single notification as read."""
        notification = self.get_object()

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])

        serializer = self.get_serializer(notification)
        return Response(serializer.data)

    @extend_schema(
        description="Mark all notifications as read",
        responses={200: {'type': 'object', 'properties': {'updated_count': {'type': 'integer'}}}}
    )
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """Mark all user's unread notifications as read."""
        updated_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )

        return Response({'updated_count': updated_count})

    @extend_schema(
        description="Get count of unread notifications",
        responses={200: {'type': 'object', 'properties': {'unread_count': {'type': 'integer'}}}}
    )
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        """Get the count of unread notifications."""
        count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()

        return Response({'unread_count': count})

    def perform_destroy(self, instance):
        """Only allow deleting own notifications."""
        if instance.user != self.request.user:
            return Response(
                {'error': 'Cannot delete notifications belonging to other users'},
                status=status.HTTP_403_FORBIDDEN
            )
        instance.delete()