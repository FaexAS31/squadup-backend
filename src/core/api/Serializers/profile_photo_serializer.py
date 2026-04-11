"""
ProfilePhoto Serializer
=======================
Serializer for user gallery photos (up to 6 per user).
"""

from rest_framework import serializers
from api.models import ProfilePhoto


class ProfilePhotoSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for ProfilePhoto model.

    - user is read-only (set automatically from request.user)
    - Provides url field for REST navigation
    """
    user = serializers.HyperlinkedRelatedField(
        view_name='user-detail',
        read_only=True
    )

    class Meta:
        model = ProfilePhoto
        fields = [
            'url',
            'id',
            'user',
            'image_url',
            'thumbnail_url',
            'order',
            'caption',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
        extra_kwargs = {
            'url': {'view_name': 'profilephoto-detail'},
        }


class ProfilePhotoReorderSerializer(serializers.Serializer):
    """
    Serializer for reordering photos.
    Accepts a list of photo IDs in the desired order.
    """
    photo_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="List of photo IDs in desired order"
    )
