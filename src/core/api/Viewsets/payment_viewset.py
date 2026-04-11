import logging
from rest_framework import viewsets
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from api.models import Payment
from api.Serializers.payment_serializer import PaymentSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['Payments'])
class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet para Payments.
    Logging: create (intento de pago)
    """
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    throttle_classes = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'fuerza_bruta'

    def create(self, request, *args, **kwargs):
        logger.info(
            f"[BILLING] Intento de CREATE en Payment | "
            f"Usuario: {request.user} | Invoice: {request.data.get('invoice')} | "
            f"Amount: {request.data.get('amount')} {request.data.get('currency', 'USD')} | "
            f"Provider: {request.data.get('provider')}"
        )
        try:
            response = super().create(request, *args, **kwargs)
            logger.info(
                f"[BILLING] Payment CREATE exitoso. ID: {response.data.get('id')} | "
                f"Invoice: {response.data.get('invoice')} | "
                f"Status: {response.data.get('status')} | "
                f"Amount: {response.data.get('amount')}"
            )
            return response
        except Exception as e:
            logger.error(f"[BILLING] Error en CREATE de Payment: {str(e)}")
            raise e
