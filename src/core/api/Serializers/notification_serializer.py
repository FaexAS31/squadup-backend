import logging

from rest_framework import serializers
from api.models import Notification, User

logger = logging.getLogger('api')


class NotificationSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    sender_name = serializers.SerializerMethodField()
    sender_photo = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = '__all__'

    def _get_sender(self, obj):
        """Resolve sender User from notification data.sender_id (cached per request)."""
        sender_id = (obj.data or {}).get('sender_id')
        if not sender_id:
            return None
        # Use a request-level cache to avoid N+1 queries
        request = self.context.get('request')
        cache_attr = '_sender_cache'
        if request and hasattr(request, cache_attr):
            cache = getattr(request, cache_attr)
        else:
            cache = {}
            if request:
                setattr(request, cache_attr, cache)
        if sender_id not in cache:
            try:
                cache[sender_id] = User.objects.get(id=sender_id)
            except User.DoesNotExist:
                cache[sender_id] = None
        return cache[sender_id]

    def get_sender_name(self, obj):
        sender = self._get_sender(obj)
        if not sender:
            return None
        return sender.first_name or sender.email.split('@')[0]

    def get_sender_photo(self, obj):
        sender = self._get_sender(obj)
        if not sender:
            return None
        return sender.profile_photo or None
