import logging
from rest_framework import viewsets
from api.models import PlanFeature
from api.Serializers.plan_feature_serializer import PlanFeatureSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')

@extend_schema(tags=['PlanFeatures'])
class PlanFeatureViewSet(viewsets.ModelViewSet):
    """ViewSet estándar para PlanFeatures."""
    queryset = PlanFeature.objects.all()
    serializer_class = PlanFeatureSerializer
