from rest_framework.serializers import HyperlinkedModelSerializer, CharField
from ..models import DeviceToken


class DeviceTokenSerializer(HyperlinkedModelSerializer):
    """Serializer for FCM device tokens."""

    # Token is write-only for security
    token = CharField(max_length=500, write_only=False)

    class Meta:
        model = DeviceToken
        fields = [
            'url',
            'token',
            'platform',
            'device_id',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['url', 'created_at', 'updated_at']
        extra_kwargs = {
            'url': {'view_name': 'devicetoken-detail'},
        }


class DeviceTokenCreateSerializer(HyperlinkedModelSerializer):
    """Serializer for registering a new device token."""

    # Override token to remove the auto-generated UniqueValidator.
    # The register action handles upsert logic itself.
    token = CharField(max_length=500)

    class Meta:
        model = DeviceToken
        fields = [
            'token',
            'platform',
            'device_id',
        ]
