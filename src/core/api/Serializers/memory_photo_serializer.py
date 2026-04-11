from rest_framework import serializers
from api.models import MemoryPhoto


class MemoryPhotoSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = MemoryPhoto
        fields = '__all__'
        read_only_fields = ['uploaded_by']
