import logging
from rest_framework import viewsets
from api.models import Plan
from api.Serializers.plan_serializer import PlanSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['Plans'])
class PlanViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para Plans."""
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
