from rest_framework import serializers
from api.models import Group

class GroupSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    # Read-only computed fields
    member_count = serializers.IntegerField(read_only=True)
    combined_interests = serializers.ListField(read_only=True)
    total_matches = serializers.IntegerField(read_only=True)
    total_outings = serializers.IntegerField(read_only=True)
    total_memories = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = '__all__'
        read_only_fields = ['invite_code']  # Auto-generated, can't be set by client