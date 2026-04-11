from rest_framework import serializers
from api.models import Subscription

class SubscriptionSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = Subscription
        fields = '__all__'