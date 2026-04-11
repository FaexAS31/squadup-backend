import logging
from rest_framework import viewsets
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from api.models import PaymentMethod
from api.Serializers.payment_method_serializer import PaymentMethodSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['PaymentMethods'])
class PaymentMethodViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para PaymentMethods."""
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    throttle_classes = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'fuerza_bruta'