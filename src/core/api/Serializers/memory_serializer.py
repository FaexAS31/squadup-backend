from rest_framework import serializers
from api.models import Memory


class MemorySerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    created_by_name = serializers.SerializerMethodField()
    photo_count = serializers.SerializerMethodField()

    class Meta:
        model = Memory
        fields = '__all__'
        read_only_fields = ['created_by']

    def get_created_by_name(self, obj):
        if obj.created_by:
            name = f'{obj.created_by.first_name} {obj.created_by.last_name}'.strip()
            return name or obj.created_by.email
        return None

    def get_photo_count(self, obj):
        return obj.photo_count
