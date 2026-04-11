from rest_framework import serializers
from api.models import Invoice

class InvoiceSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = Invoice
        fields = '__all__'