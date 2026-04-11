"""
ProfilePhoto ViewSet
====================
CRUD operations for user gallery photos with max 6 photo limit.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from api.models import ProfilePhoto
from api.Serializers.profile_photo_serializer import (
    ProfilePhotoSerializer,
    ProfilePhotoReorderSerializer,
)


MAX_PHOTOS_PER_USER = 6


class ProfilePhotoViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user gallery photos.

    Users can only see and manage their own photos.
    Maximum of 6 photos per user enforced on create.

    Endpoints:
    - GET /api/profilephotos/ - List current user's photos
    - POST /api/profilephotos/ - Add a new photo (max 6)
    - GET /api/profilephotos/{id}/ - Get photo details
    - PUT/PATCH /api/profilephotos/{id}/ - Update photo (caption, order)
    - DELETE /api/profilephotos/{id}/ - Remove photo
    - POST /api/profilephotos/reorder/ - Reorder all photos
    """
    serializer_class = ProfilePhotoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only photos belonging to the current user."""
        if getattr(self, 'swagger_fake_view', False):
            return ProfilePhoto.objects.none()
        return ProfilePhoto.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """
        Create a new photo for the current user.
        Enforces max 6 photos limit.
        Sets order to next available position.
        """
        user = self.request.user
        current_count = ProfilePhoto.objects.filter(user=user).count()

        if current_count >= MAX_PHOTOS_PER_USER:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                'detail': f'Maximum of {MAX_PHOTOS_PER_USER} photos allowed. '
                          f'Please delete a photo before adding a new one.'
            })

        # Set order to next position if not provided
        if 'order' not in serializer.validated_data:
            max_order = ProfilePhoto.objects.filter(user=user).order_by('-order').first()
            next_order = (max_order.order + 1) if max_order else 0
            serializer.save(user=user, order=next_order)
        else:
            serializer.save(user=user)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """
        Reorder photos by providing list of photo IDs in desired order.

        POST /api/profilephotos/reorder/
        Body: {"photo_ids": [3, 1, 5, 2]}

        Photos will be assigned order 0, 1, 2, 3... based on position in list.
        All photo IDs must belong to the current user.
        """
        serializer = ProfilePhotoReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        photo_ids = serializer.validated_data['photo_ids']
        user = request.user

        # Verify all photos belong to user
        user_photos = ProfilePhoto.objects.filter(user=user, id__in=photo_ids)
        if user_photos.count() != len(photo_ids):
            return Response(
                {'detail': 'One or more photo IDs are invalid or do not belong to you.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update order for each photo
        for new_order, photo_id in enumerate(photo_ids):
            ProfilePhoto.objects.filter(id=photo_id, user=user).update(order=new_order)

        # Return updated list
        updated_photos = ProfilePhoto.objects.filter(user=user).order_by('order')
        response_serializer = ProfilePhotoSerializer(
            updated_photos,
            many=True,
            context={'request': request}
        )
        return Response(response_serializer.data)
