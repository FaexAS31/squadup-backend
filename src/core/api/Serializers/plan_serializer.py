from rest_framework import serializers
from api.models import Plan

class PlanSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = Plan
        fields = '__all__'