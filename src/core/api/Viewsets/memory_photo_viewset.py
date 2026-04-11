import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from api.models import MemoryPhoto
from api.Serializers.memory_photo_serializer import MemoryPhotoSerializer

logger = logging.getLogger('api')


@extend_schema(tags=['MemoryPhotos'])
class MemoryPhotoViewSet(viewsets.ModelViewSet):
    """
    ViewSet for MemoryPhotos.

    Supports filtering by:
    - memory: Filter photos by memory ID

    Auto-sets uploaded_by to the requesting user on creation.
    """
    queryset = MemoryPhoto.objects.all()
    serializer_class = MemoryPhotoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['memory']

    def get_queryset(self):
        return MemoryPhoto.objects.all().select_related(
            'memory', 'uploaded_by'
        ).order_by('order', 'created_at')

    def perform_create(self, serializer):
        photo = serializer.save(uploaded_by=self.request.user)
        logger.info(f"MemoryPhoto created: {photo.id} for memory {photo.memory_id} by user {self.request.user.id}")
