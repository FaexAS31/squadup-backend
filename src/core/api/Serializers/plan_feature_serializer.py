from rest_framework import serializers
from api.models import PlanFeature

class PlanFeatureSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = PlanFeature
        fields = '__all__'