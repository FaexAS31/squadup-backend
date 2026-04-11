import logging
from rest_framework import viewsets
from api.models import InvoiceItem
from api.Serializers.invoice_item_serializer import InvoiceItemSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['InvoiceItems'])
class InvoiceItemViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para InvoiceItems."""
    queryset = InvoiceItem.objects.all()
    serializer_class = InvoiceItemSerializer
