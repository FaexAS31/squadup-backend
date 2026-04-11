import logging
from rest_framework import viewsets
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from api.models import Coupon
from api.Serializers.coupon_serializer import CouponSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['Coupons'])
class CouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    throttle_classes = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'fuerza_bruta'

    def create(self, request, *args, **kwargs):
        logger.info(f"Initiating Coupon creation by user: {request.user}")
        try:
            response = super().create(request, *args, **kwargs)
            logger.info(f"Coupon created successfully: ID {response.data.get('id')}")
            return response
        except Exception as e:
            logger.error(f"Failed to create Coupon: {str(e)}")
            raise e