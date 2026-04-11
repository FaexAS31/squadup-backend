from rest_framework import serializers
from api.models import Payment

class PaymentSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = Payment
        fields = '__all__'