import logging
from rest_framework import viewsets
from api.models import Invoice
from api.Serializers.invoice_serializer import InvoiceSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['Invoices'])
class InvoiceViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para Invoices."""
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
