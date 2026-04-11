import logging
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from api.models import Report
from api.Serializers.report_serializer import ReportSerializer

logger = logging.getLogger('api')


@extend_schema(tags=['Reports'])
class ReportViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Submit and view reports.
    Users can create reports and view their own submitted reports.
    """

    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Report.objects.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        report = serializer.save(reporter=self.request.user)
        logger.info(
            f"Report created: {report.report_type} #{report.target_id} "
            f"by user {self.request.user.id} reason={report.reason}"
        )
