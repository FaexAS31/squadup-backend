import logging
from rest_framework import viewsets
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from api.models import Discount
from api.Serializers.discount_serializer import DiscountSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['Discounts'])
class DiscountViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para Discounts."""
    queryset = Discount.objects.all()
    serializer_class = DiscountSerializer
    throttle_classes = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'fuerza_bruta'