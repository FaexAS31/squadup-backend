from rest_framework import serializers
from api.models import MeetupPlan


class MeetupPlanSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    proposed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MeetupPlan
        fields = '__all__'
        read_only_fields = ['proposed_by']

    def get_proposed_by_name(self, obj):
        if obj.proposed_by:
            name = f'{obj.proposed_by.first_name} {obj.proposed_by.last_name}'.strip()
            return name or obj.proposed_by.email
        return None