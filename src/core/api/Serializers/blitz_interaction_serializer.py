from rest_framework import serializers
from api.models import BlitzInteraction

class BlitzInteractionSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    consensus_status = serializers.SerializerMethodField()

    class Meta:
        model = BlitzInteraction
        fields = '__all__'

    def get_consensus_status(self, obj):
        try:
            return obj.consensus_status
        except Exception:
            return 'approved'