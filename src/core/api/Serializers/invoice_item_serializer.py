from rest_framework import serializers
from api.models import InvoiceItem

class InvoiceItemSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = InvoiceItem
        fields = '__all__'